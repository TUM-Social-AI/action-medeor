"""Benchmark free multilingual embedding models against the private ERP exports."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

from app.catalog.embeddings import (  # noqa: E402
    CatalogEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from app.catalog.foundry_embeddings import (  # noqa: E402
    AzureCohereEmbeddingProvider,
    AzureOpenAIEmbeddingProvider,
)
from app.matching.representation import normalize_text  # noqa: E402

DEFAULT_SENTENCE_TRANSFORMER_MODELS = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large-instruct",
)

DEFAULT_FOUNDRY_MODELS = (
    "text-embedding-3-small",
    "text-embedding-3-large",
)

DEFAULT_COHERE_MODELS = ("Cohere-embed-v3-multilingual",)

# User-supplied Foundry prices, normalized to USD per 1,000,000 input tokens.
DEFAULT_API_PRICES_PER_MILLION = {
    ("azure-openai", "text-embedding-3-small"): 0.02,
    ("azure-openai", "text-embedding-3-large"): 0.14,
    ("azure-cohere", "Cohere-embed-v3-multilingual"): 0.10,
}


@dataclass(frozen=True)
class Candidate:
    item_number: str
    domain: str
    text: str


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    expected_item_number: str
    domain: str
    language: str


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key.strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle, delimiter=";")
        ]


def build_evaluation_set(
    article_path: Path,
    translation_path: Path,
    *,
    labels_path: Path | None = None,
) -> tuple[list[Candidate], list[Query]]:
    articles = _read(article_path)
    candidates: list[Candidate] = []
    domain_by_item: dict[str, str] = {}
    for row in articles:
        category = row["Artikelkategoriencode"]
        domain = "medicine" if category.startswith("2") else "equipment" if category.startswith("4") else ""
        description = " ".join(
            value for value in (row["Beschreibung"], row["Beschreibung 2"]) if value
        )
        item_number = row["Nr."]
        master_item = item_number.endswith("000") and not row["Nummer 2"]
        if not domain or not description or master_item:
            continue
        text = normalize_text(
            f"{description}; category={category}; base_unit={row['Basiseinheit']}"
        )
        candidates.append(Candidate(item_number=item_number, domain=domain, text=text))
        domain_by_item[item_number] = domain

    queries: list[Query] = []
    for index, row in enumerate(_read(translation_path), start=2):
        item_number = row["Artikelnr."]
        language = row["Sprachcode"].upper()
        # French is the genuinely cross-lingual ERP signal; many base descriptions are English.
        if language not in {"FRA", "FRS"} or item_number not in domain_by_item:
            continue
        text = " ".join(value for value in (row["Beschreibung"], row["Beschreibung 2"]) if value)
        if text:
            queries.append(
                Query(
                    query_id=f"translation:{index}",
                    text=text,
                    expected_item_number=item_number,
                    domain=domain_by_item[item_number],
                    language="fr",
                )
            )

    if labels_path:
        with labels_path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                expected_item = value["expected_item_number"]
                expected_domain = domain_by_item.get(expected_item)
                if expected_domain is None:
                    raise ValueError(
                        f"Label {index} references a non-offerable or unknown article: "
                        f"{expected_item}"
                    )
                if value["domain"] != expected_domain:
                    raise ValueError(
                        f"Label {index} uses domain {value['domain']!r}, but article "
                        f"{expected_item} belongs to {expected_domain!r}"
                    )
                queries.append(
                    Query(
                        query_id=value.get("query_id", f"label:{index}"),
                        text=value["text"],
                        expected_item_number=expected_item,
                        domain=value["domain"],
                        language=value.get("language", "unknown"),
                    )
                )
    return candidates, queries


async def benchmark_model(
    provider: CatalogEmbeddingProvider,
    candidates: list[Candidate],
    queries: list[Query],
    *,
    batch_size: int,
    compute_cost_per_hour: float | None,
    price_per_million_tokens: float | None,
) -> dict[str, object]:
    spec = await provider.spec()
    started = time.perf_counter()
    candidate_vectors = np.asarray(
        await provider.embed_documents([candidate.text for candidate in candidates]),
        dtype=np.float32,
    )
    catalog_seconds = time.perf_counter() - started
    started = time.perf_counter()
    query_vectors = np.asarray(
        await provider.embed_queries([query.text for query in queries]),
        dtype=np.float32,
    )
    query_seconds = time.perf_counter() - started

    indices_by_domain = {
        domain: np.asarray(
            [index for index, candidate in enumerate(candidates) if candidate.domain == domain]
        )
        for domain in {candidate.domain for candidate in candidates}
    }
    hits = {1: 0, 3: 0, 10: 0}
    reciprocal_rank = 0.0
    failures: list[dict[str, object]] = []
    for query, vector in zip(queries, query_vectors, strict=True):
        indices = indices_by_domain[query.domain]
        scores = candidate_vectors[indices] @ vector
        ranking = indices[np.argsort(-scores)]
        ranked_items = [candidates[int(index)].item_number for index in ranking]
        try:
            rank = ranked_items.index(query.expected_item_number) + 1
        except ValueError:
            rank = None
        if rank is not None:
            reciprocal_rank += 1 / rank
            for k in hits:
                hits[k] += int(rank <= k)
        if rank is None or rank > 10:
            failures.append(
                {
                    "query_id": query.query_id,
                    "expected": query.expected_item_number,
                    "rank": rank,
                    "top_10": ranked_items[:10],
                }
            )
    count = len(queries)
    input_tokens = getattr(provider, "input_tokens_used", None)
    return {
        "model": asdict(spec),
        "dataset": {"candidates": len(candidates), "queries": count},
        "metrics": {
            "recall_at_1": hits[1] / count if count else 0,
            "recall_at_3": hits[3] / count if count else 0,
            "recall_at_10": hits[10] / count if count else 0,
            "mean_reciprocal_rank": reciprocal_rank / count if count else 0,
        },
        "performance": {
            "catalog_embedding_seconds": catalog_seconds,
            "query_embedding_seconds": query_seconds,
            "queries_per_second": count / query_seconds if query_seconds else None,
            "vector_storage_bytes": int(candidate_vectors.nbytes),
            "batch_size": batch_size,
            "estimated_compute_cost": (
                (catalog_seconds + query_seconds) / 3600 * compute_cost_per_hour
                if compute_cost_per_hour is not None
                else None
            ),
            "compute_cost_per_hour": compute_cost_per_hour,
            "input_tokens": input_tokens,
            "price_per_million_tokens": price_per_million_tokens,
            "estimated_api_cost": (
                input_tokens / 1_000_000 * price_per_million_tokens
                if input_tokens is not None and price_per_million_tokens is not None
                else None
            ),
        },
        "failures": failures[:100],
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    candidates, queries = build_evaluation_set(
        args.articles,
        args.translations,
        labels_path=args.labels,
    )
    if args.limit_queries:
        queries = queries[: args.limit_queries]
    if not candidates:
        raise ValueError("No offerable catalog candidates were found")
    if not queries:
        raise ValueError("No evaluation queries were found")
    reports = []
    deployments = args.deployments or [""] * len(args.models)
    dimensions = args.dimensions or [None] * len(args.models)
    for model, deployment, model_dimensions in zip(
        args.models, deployments, dimensions, strict=True
    ):
        provider: CatalogEmbeddingProvider | None = None
        try:
            if args.provider == "sentence-transformers":
                provider = SentenceTransformerEmbeddingProvider(
                    model,
                    revision=args.revision,
                    batch_size=args.batch_size,
                )
            elif args.provider == "azure-openai":
                endpoint = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
                api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
                provider = AzureOpenAIEmbeddingProvider(
                    endpoint=endpoint,
                    deployment=deployment,
                    model_name=model,
                    model_version=args.model_version,
                    dimensions=model_dimensions,
                    api_key=api_key,
                    batch_size=args.batch_size,
                )
            else:
                endpoint = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
                api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
                provider = AzureCohereEmbeddingProvider(
                    endpoint=endpoint,
                    deployment=deployment,
                    model_name=model,
                    model_version=args.model_version,
                    dimensions=model_dimensions,
                    api_key=api_key,
                    batch_size=args.batch_size,
                )
            reports.append(
                await benchmark_model(
                    provider,
                    candidates,
                    queries,
                    batch_size=args.batch_size,
                    compute_cost_per_hour=args.compute_cost_per_hour,
                    price_per_million_tokens=(
                        args.price_per_million_tokens
                        if args.price_per_million_tokens is not None
                        else DEFAULT_API_PRICES_PER_MILLION.get(
                            (args.provider, model)
                        )
                    ),
                )
            )
        except Exception as exc:
            version = (
                args.revision
                if args.provider == "sentence-transformers"
                else args.model_version
            )
            message = str(exc) or "request timed out"
            reports.append(
                {
                    "model": {"name": model, "version": version},
                    "error": f"{type(exc).__name__}: {message}",
                    "partial_progress": (
                        getattr(provider, "diagnostics", None)
                        if provider is not None
                        else None
                    ),
                }
            )
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input_files": {
            "articles": args.articles.name,
            "translations": args.translations.name,
            "labels": args.labels.name if args.labels else None,
        },
        "reports": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, required=True)
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument(
        "--provider",
        choices=("sentence-transformers", "azure-openai", "azure-cohere"),
        default="azure-openai",
    )
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--deployments", nargs="+")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--dimensions", nargs="+", type=int)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--compute-cost-per-hour",
        type=float,
        help="Optional Azure/job price used to estimate the measured benchmark run cost",
    )
    parser.add_argument(
        "--price-per-million-tokens",
        type=float,
        help="Override the built-in model price in USD per 1,000,000 input tokens",
    )
    parser.add_argument("--limit-queries", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.models is None:
        if args.provider == "azure-openai":
            args.models = list(DEFAULT_FOUNDRY_MODELS)
        elif args.provider == "azure-cohere":
            args.models = list(DEFAULT_COHERE_MODELS)
        else:
            args.models = list(DEFAULT_SENTENCE_TRANSFORMER_MODELS)
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.compute_cost_per_hour is not None and args.compute_cost_per_hour < 0:
        parser.error("--compute-cost-per-hour cannot be negative")
    if args.price_per_million_tokens is not None and args.price_per_million_tokens < 0:
        parser.error("--price-per-million-tokens cannot be negative")
    if args.provider in {"azure-openai", "azure-cohere"}:
        if not args.deployments:
            parser.error("--deployments is required for Foundry API providers")
        if len(args.deployments) != len(args.models):
            parser.error("--deployments must contain one value for every --models value")
        if not args.model_version:
            parser.error("--model-version is required for Foundry API providers")
        if not args.dimensions or len(args.dimensions) != len(args.models):
            parser.error("--dimensions must contain one value for every --models value")
        if any(value < 1 for value in args.dimensions):
            parser.error("all --dimensions values must be positive")
        if not os.environ.get("AZURE_FOUNDRY_ENDPOINT"):
            parser.error("AZURE_FOUNDRY_ENDPOINT is required for Foundry API providers")
        if not os.environ.get("AZURE_FOUNDRY_API_KEY"):
            parser.error("AZURE_FOUNDRY_API_KEY is required for Foundry API providers")
    elif args.deployments or args.dimensions:
        parser.error(
            "--deployments and --dimensions are only valid with --provider azure-openai"
        )
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
