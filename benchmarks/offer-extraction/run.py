"""Evaluate local offer extraction against source-reviewed labels; never writes to the DB."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.offers.extraction import PROMPT_VERSION, extract_offers  # noqa: E402

FIELDS = (
    "supplier",
    "item_description",
    "offer_reference",
    "offer_date",
    "date_kind",
    "valid_until",
    "validity_text",
    "price_text",
    "price_amount",
    "currency",
    "price_basis",
    "price_conflict",
)
CRITICAL = (
    "supplier",
    "item_description",
    "offer_date",
    "valid_until",
    "price_amount",
    "currency",
    "price_basis",
    "price_conflict",
)


def normalized(value: object, field: str) -> object:
    if value is None or isinstance(value, bool):
        return value
    if field == "price_amount":
        return Decimal(str(value))
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
    if field == "price_basis":
        text = text.lstrip("/ ")
        text = re.sub(r"\b(stück|pieces|pcs|piece)\b", "piece", text)
        text = re.sub(r"\b(tabletten|tablets|tablet)\b", "tablet", text)
        text = re.sub(r"\b(capsules|capsule)\b", "capsule", text)
        text = re.sub(r"\b(sachets|sachet)\b", "sachet", text)
    if field == "item_description":
        text = re.sub(r"^(alternativ[e]?:\s*)", "", text).strip('" ')
    return text


def identity(offer: dict) -> tuple[str, int]:
    return offer["source_id"], offer["alternative_index"]


def score(expected: list[dict], actual: list[dict]) -> dict:
    gold = {identity(offer): offer for offer in expected}
    predicted = {identity(offer): offer for offer in actual}
    shared = gold.keys() & predicted.keys()
    fields = {
        field: {
            "populated_correct": 0,
            "populated_total": 0,
            "missing_correct": 0,
            "missing_total": 0,
        }
        for field in FIELDS
    }
    differences = []
    for key, wanted in gold.items():
        got = predicted.get(key)
        for field in FIELDS:
            category = "missing" if wanted[field] is None else "populated"
            fields[field][f"{category}_total"] += 1
            if got is not None and normalized(wanted[field], field) == normalized(
                got[field], field
            ):
                fields[field][f"{category}_correct"] += 1
            else:
                differences.append(
                    {
                        "source_id": key[0],
                        "alternative_index": key[1],
                        "field": field,
                        "expected": wanted[field],
                        "actual": got[field] if got else "<offer missing>",
                        "expected_evidence": wanted.get("source_evidence", {}),
                        "actual_evidence": got.get("evidence", []) if got else [],
                    }
                )
    synthetic_critical = not (gold.keys() ^ predicted.keys()) and all(
        normalized(gold[key][field], field) == normalized(predicted[key][field], field)
        for key in shared
        for field in CRITICAL
    )
    return {
        "expected_offers": len(gold),
        "actual_offers": len(actual),
        "true_positives": len(shared),
        "false_positives": len(predicted.keys() - gold.keys())
        + len(actual)
        - len(predicted),
        "false_negatives": len(gold.keys() - predicted.keys()),
        "fields": fields,
        "missing_offers": [list(key) for key in sorted(gold.keys() - predicted.keys())],
        "extra_offers": [list(key) for key in sorted(predicted.keys() - gold.keys())],
        "differences": differences,
        "synthetic_critical_pass": synthetic_critical,
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(results: list[dict]) -> dict:
    counts = Counter()
    fields = {f: Counter() for f in FIELDS}
    for result in results:
        scoring = result["score"]
        counts.update(
            {
                k: scoring[k]
                for k in ("true_positives", "false_positives", "false_negatives")
            }
        )
        for field, values in scoring["fields"].items():
            fields[field].update(values)
    present_correct = sum(v["populated_correct"] for v in fields.values())
    present_total = sum(v["populated_total"] for v in fields.values())
    missing_correct = sum(v["missing_correct"] for v in fields.values())
    missing_total = sum(v["missing_total"] for v in fields.values())
    populated_accuracy = ratio(present_correct, present_total)
    synthetic_pass = all(
        r["score"]["synthetic_critical_pass"] and not r["extraction"]["failures"]
        for r in results
        if r["synthetic"]
    )
    return {
        "precision": ratio(
            counts["true_positives"],
            counts["true_positives"] + counts["false_positives"],
        ),
        "recall": ratio(
            counts["true_positives"],
            counts["true_positives"] + counts["false_negatives"],
        ),
        "counts": dict(counts),
        "populated_accuracy": populated_accuracy,
        "missing_accuracy": ratio(missing_correct, missing_total),
        "fields": {
            f: {
                **dict(v),
                "populated_accuracy": ratio(
                    v["populated_correct"], v["populated_total"]
                ),
                "missing_accuracy": ratio(v["missing_correct"], v["missing_total"]),
            }
            for f, v in fields.items()
        },
        "synthetic_critical_pass": synthetic_pass,
        "failed_documents": sum(bool(r["extraction"]["failures"]) for r in results),
        "quality_target_pass": populated_accuracy is not None
        and populated_accuracy >= 0.95
        and synthetic_pass
        and not any(r["extraction"]["failures"] for r in results),
    }


def evaluate(path: Path, label: dict, pass_number: int) -> dict:
    print(f"Pass {pass_number}: starting {path.name}", flush=True)
    started = time.monotonic()
    result = extract_offers(path.read_bytes(), path.name)
    extraction = result.model_dump(mode="json")
    outcome = {
        "filename": path.name,
        "synthetic": label["synthetic"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "extraction": extraction,
        "score": score(label["offers"], extraction["offers"]),
    }
    print(
        f"Pass {pass_number}: finished {path.name}: {len(result.offers)} offers, "
        f"{len(outcome['score']['differences'])} field differences, "
        f"{len(result.failures)} failures ({outcome['elapsed_seconds']}s)",
        flush=True,
    )
    return outcome


def consistency(passes: list[list[dict]]) -> dict:
    if len(passes) < 2:
        return {
            "compared_documents": 0,
            "identical_documents": 0,
            "changed_documents": [],
        }
    previous = {r["filename"]: r for r in passes[0]}
    changed = []
    compared = 0
    for pass_index, results in enumerate(passes[1:], 2):
        for result in results:
            compared += 1
            old = previous[result["filename"]]["extraction"]
            new = result["extraction"]
            old_by_id = {identity(o): o for o in old["offers"]}
            new_by_id = {identity(o): o for o in new["offers"]}
            if (
                old_by_id.keys() != new_by_id.keys()
                or any(
                    normalized(old_by_id[key][field], field)
                    != normalized(new_by_id[key][field], field)
                    for key in old_by_id.keys() & new_by_id.keys()
                    for field in FIELDS
                )
                or bool(old["failures"]) != bool(new["failures"])
            ):
                changed.append({"filename": result["filename"], "pass": pass_index})
    return {
        "compared_documents": compared,
        "identical_documents": compared - len(changed),
        "changed_documents": changed,
    }


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def report_markdown(report: dict) -> str:
    lines = [
        "# Supplier offer extraction evaluation",
        "",
        f"Run: {report['created_at']} · provider: `{report['provider']}` · "
        f"deployment: `{report['deployment']}` · prompt: `{report['prompt_version']}`",
        "",
        "Scores use normalized exact matching. Missing offers count as incorrect fields; "
        "populated and missing values are scored separately. Price amounts are compared "
        "as exact decimals, without conversion. Evidence and source locations are in results.json.",
        "",
        "| Pass | Precision | Recall | Populated fields | Missing values | Synthetic critical | Target |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for index, summary in enumerate(report["summaries"], 1):
        lines.append(
            f"| {index} | {pct(summary['precision'])} | {pct(summary['recall'])} | "
            f"{pct(summary['populated_accuracy'])} | {pct(summary['missing_accuracy'])} | "
            f"{'PASS' if summary['synthetic_critical_pass'] else 'FAIL'} | "
            f"{'PASS' if summary['quality_target_pass'] else 'FAIL'} |"
        )
    stable = report["consistency"]
    lines.extend(
        [
            "",
            f"Consistency: {stable['identical_documents']}/{stable['compared_documents']} "
            "documents have identical scored fields across passes (source excerpts excluded).",
            "",
            "## Per-field accuracy, final pass",
            "",
            "| Field | Populated correct/total | Accuracy | Missing correct/total | Accuracy |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for field, values in report["summaries"][-1]["fields"].items():
        lines.append(
            f"| {field} | {values['populated_correct']}/{values['populated_total']} | "
            f"{pct(values['populated_accuracy'])} | {values['missing_correct']}/{values['missing_total']} | "
            f"{pct(values['missing_accuracy'])} |"
        )
    lines.extend(["", "## Documents and representative differences", ""])
    for index, results in enumerate(report["passes"], 1):
        lines.extend([f"### Pass {index}", ""])
        for result in results:
            scored = result["score"]
            extraction = result["extraction"]
            lines.extend(
                [
                    f"**{result['filename']}**: {scored['actual_offers']}/{scored['expected_offers']} "
                    f"offers; {result['elapsed_seconds']}s; "
                    f"{len(scored['differences'])} field differences.",
                    "",
                ]
            )
            for failure in extraction["failures"]:
                lines.extend([f"- Failure: {failure}", ""])
            if scored["missing_offers"] or scored["extra_offers"]:
                lines.extend(
                    [
                        f"- Missing: {scored['missing_offers']}; extra: {scored['extra_offers']}",
                        "",
                    ]
                )
            for diff in scored["differences"][:5]:
                lines.append(
                    f"- `{diff['source_id']}` alternative {diff['alternative_index']} "
                    f"`{diff['field']}`: expected `{diff['expected']}`, got `{diff['actual']}`."
                )
                evidence = [
                    e
                    for e in diff["actual_evidence"]
                    if e["field"] == diff["field"]
                    or diff["field"].startswith("price")
                    and e["field"] == "price"
                ]
                if evidence:
                    excerpt = json.dumps(evidence[0], ensure_ascii=False)
                    lines.append(f"  Source evidence: {excerpt}")
            lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "The initial target is 95% populated-field accuracy and all synthetic critical "
            "checks passing. Critical checks cover supplier/item association, dates, quoted "
            "amount/currency/basis and price conflicts. This small corpus estimates prototype "
            "quality; it does not establish production readiness. No emails, scanned PDFs, "
            "live SharePoint metadata fallback or persistence were evaluated.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT / "data" / "anonymized data"
    )
    parser.add_argument("--labels", type=Path)
    parser.add_argument(
        "--documents",
        nargs="+",
        help="Filename glob(s); quote patterns containing spaces",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "reports" / "luna-v3"
    )
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.passes < 1 or args.workers < 1:
        parser.error("--passes and --workers must be positive")
    args.data_dir = args.data_dir.resolve()
    output = args.output_dir.resolve()
    labels = json.loads(
        (args.labels or args.data_dir / "offer-extraction-labels.json").read_text()
    )
    documents = {
        name: label
        for name, label in labels["documents"].items()
        if not args.documents
        or any(fnmatch.fnmatch(name, pattern) for pattern in args.documents)
    }
    if not documents:
        parser.error("No labelled documents selected")
    for name, label in documents.items():
        digest = hashlib.sha256((args.data_dir / name).read_bytes()).hexdigest()
        if digest != label["sha256"]:
            parser.error(f"Source changed since labels were prepared: {name}")
    # Settings resolve .env relative to CWD; make this runner independent of launch directory.
    os.chdir(BACKEND)
    settings = get_settings()
    deployment = (
        settings.azure_openai_deployment
        if settings.llm_provider == "azure_openai"
        else getattr(settings, f"{settings.llm_provider}_extraction_model")
    )
    if deployment != "gpt-6-luna":
        parser.error(
            f"This evaluation requires gpt-6-luna, configured deployment is {deployment!r}"
        )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "provider": settings.llm_provider,
        "deployment": deployment,
        "prompt_version": PROMPT_VERSION,
        "label_version": labels["label_version"],
        "source_hashes": {name: label["sha256"] for name, label in documents.items()},
        "passes": [],
        "summaries": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    for pass_number in range(1, args.passes + 1):
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(evaluate, args.data_dir / name, label, pass_number)
                for name, label in documents.items()
            ]
            for future in as_completed(futures):
                results.append(future.result())
                # Incremental checkpoint: interrupted runs retain completed document results.
                (output / f"pass-{pass_number}.json").write_text(
                    json.dumps(
                        sorted(results, key=lambda r: r["filename"]),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
        results.sort(key=lambda r: r["filename"])
        report["passes"].append(results)
        report["summaries"].append(summarize(results))
        report["consistency"] = consistency(report["passes"])
        (output / "results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        (output / "report.md").write_text(report_markdown(report))
        print(
            f"Pass {pass_number} summary: {json.dumps(report['summaries'][-1], ensure_ascii=False)}",
            flush=True,
        )
    print(f"Reports written to {output}")


if __name__ == "__main__":
    main()
