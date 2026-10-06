"""Sparse review, source safety and bounded calls, without provider traffic."""

import json
from unittest.mock import Mock

import pytest

from app.parsing import ai_review, llm_table_classifier
from app.parsing.ai_review import Correction, Issue, ReviewBatch, review_document
from app.parsing.llm_client import LlmUnavailable
from app.parsing.service import parse_upload
from app.parsing.table_parser import parse_table_rows
from app.parsing.types import ParsedDocument, ParsedLineItem
from tests.test_llm_table_classifier import NAMES, QUANTITIES, build_rfq_pdf, rfq_mapping


def checked(prompt, schema):
    data = json.loads(prompt.rsplit("\n", 1)[1])
    patches = []
    for row in data["rows"]:
        for field, value in [("domain", "equipment"), ("unit", "pcs")]:
            patches.append(
                Correction(
                    row_id=row["row_id"],
                    field=field,
                    value=value,
                    inferred=True,
                    evidence=row["copied"]["name"],
                )
            )
    return ReviewBatch(
        completed=True, reviewed_count=len(data["rows"]), corrections=patches, issues=[]
    )


def device(quantity=2, name="Diagnostic scanner model A"):
    return parse_table_rows([["Product", "Quantity", "Unit"], [name, quantity, ""]])


def install(monkeypatch, response=checked):
    call = Mock(
        side_effect=response if callable(response) else None,
        return_value=response if not callable(response) else None,
    )
    monkeypatch.setattr(ai_review, "call_llm", call)
    return call


def patch(field, value, *, inferred=False, evidence="Diagnostic scanner model A", row_id="0"):
    return Correction(row_id=row_id, field=field, value=value, inferred=inferred, evidence=evidence)


def response(corrections=(), issues=(), *, completed=True, count=1):
    return ReviewBatch(
        completed=completed,
        reviewed_count=count,
        corrections=list(corrections),
        issues=list(issues),
    )


def test_anonymized_pdf_needs_only_final_confirmation(monkeypatch):
    mapping = Mock(return_value=rfq_mapping())
    monkeypatch.setattr(llm_table_classifier, "call_llm", mapping)
    doc = parse_upload(filename="request.pdf", content=build_rfq_pdf())
    call = install(monkeypatch)
    review_document(doc)
    assert [item.name.replace("\n", " ") for item in doc.items] == NAMES
    assert [item.quantity for item in doc.items] == QUANTITIES
    assert all(item.domain == "equipment" and item.unit == "pcs" for item in doc.items)
    assert all(item.status == "verified" and item.verification_source == "ai" for item in doc.items)
    assert all(set(item.inferred_fields) == {"type", "unit"} for item in doc.items)
    assert mapping.call_count == 1 and call.call_count == 1
    assert doc.review_summary["unresolved"] == 0
    sent = json.loads(call.call_args.args[0].rsplit("\n", 1)[1])
    assert all(set(row["source"]["cells"]) <= {"0", "1", "2", "3", "4"} for row in sent["rows"])


def test_completed_compact_acknowledgement_approves_complete_rows(monkeypatch):
    doc = device()
    doc.items[0].domain, doc.items[0].unit = "equipment", "pcs"
    install(monkeypatch, response())
    review_document(doc)
    assert doc.items[0].status == "verified"
    assert doc.items[0].verification_source == "ai"


@pytest.mark.parametrize(
    "result",
    [
        response(completed=False),
        response(count=0),
        response([patch("domain", "equipment", inferred=True, row_id="unknown")]),
        response(
            [
                patch("domain", "equipment", inferred=True),
                patch("domain", "medicine", inferred=True),
            ]
        ),
    ],
)
def test_invalid_or_incomplete_batch_never_claims_ai_check(monkeypatch, result):
    doc = device()
    install(monkeypatch, result)
    review_document(doc)
    assert doc.review_summary["status"] == "unavailable"
    assert doc.items[0].domain is None
    assert doc.items[0].verification_source is None


def test_provider_unavailable_keeps_copied_values(monkeypatch):
    doc = device()
    install(monkeypatch, lambda *_: (_ for _ in ()).throw(LlmUnavailable("provider details")))
    review_document(doc)
    assert doc.items[0].name == "Diagnostic scanner model A"
    assert doc.items[0].quantity == 2
    assert doc.review_summary["status"] == "unavailable"
    assert "provider details" not in doc.review_summary["message"]


@pytest.mark.parametrize(
    "field,value,inferred,evidence",
    [
        ("quantity", 999, False, "2"),
        ("quantity", "2", False, "2"),
        ("domain", "other", True, "Diagnostic scanner model A"),
        ("name", "Made up name", False, "2"),
        ("name", "Diagnostic scanner", False, "Diagnostic scanner model A"),
        ("quantity", 2, True, "2"),
        ("unit", "litres", True, "Diagnostic scanner model A"),
        ("unit", "pcs", True, "Nonexistent source evidence"),
    ],
)
def test_unsupported_corrections_require_human_review(
    monkeypatch, field, value, inferred, evidence
):
    doc = device()
    doc.items[0].domain = "equipment"
    install(monkeypatch, response([patch(field, value, inferred=inferred, evidence=evidence)]))
    review_document(doc)
    assert doc.items[0].status == "needs_review"
    assert doc.items[0].verification_source is None
    assert doc.items[0].review_reasons
    assert doc.review_summary["status"] == "unavailable"
    assert doc.items[0].quantity == 2
    assert doc.items[0].name == "Diagnostic scanner model A"


def test_source_supported_quantity_correction(monkeypatch):
    doc = device(15)
    doc.items[0].quantity = 5
    install(
        monkeypatch,
        response(
            [
                patch("quantity", 15, evidence="15"),
                patch("domain", "equipment", inferred=True),
                patch("unit", "pcs", inferred=True),
            ]
        ),
    )
    review_document(doc)
    assert doc.items[0].quantity == 15
    assert doc.items[0].status == "verified"
    assert doc.review_summary["corrected"] == 1


@pytest.mark.parametrize("protected", [["quantity"], None])
def test_human_and_legacy_nonempty_values_are_protected(monkeypatch, protected):
    doc = device(15)
    doc.items[0].quantity = 5
    doc.items[0].protected_fields = protected
    install(
        monkeypatch,
        response(
            [
                patch("quantity", 15, evidence="15"),
                patch("domain", "equipment", inferred=True),
                patch("unit", "pcs", inferred=True),
            ]
        ),
    )
    review_document(doc)
    assert doc.items[0].quantity == 5
    assert doc.items[0].domain == "equipment" and doc.items[0].unit == "pcs"
    assert doc.items[0].status == "needs_review"
    assert any("protected quantity" in reason for reason in doc.items[0].review_reasons)


def test_ambiguous_medicine_packaging_not_inferred(monkeypatch):
    doc = device(name="Antibiotic 500mg vial")
    install(
        monkeypatch,
        response(
            [
                patch("domain", "medicine", inferred=True, evidence="Antibiotic 500mg vial"),
                patch("unit", "pcs", inferred=True, evidence="Antibiotic 500mg vial"),
            ]
        ),
    )
    review_document(doc)
    assert doc.items[0].domain == "medicine"
    assert doc.items[0].unit == "" and doc.items[0].status == "needs_review"


def test_pack_arithmetic_conflict_remains_unresolved(monkeypatch):
    doc = device()
    doc.items[0].review_source["roles"].update({"3": "quantity_packs", "4": "units_per_pack"})
    doc.items[0].review_source["cells"].update({"3": "3", "4": "1"})
    install(monkeypatch)
    review_document(doc)
    assert doc.items[0].quantity == 2
    assert any("conflicts" in reason for reason in doc.items[0].review_reasons)


def test_batches_cover_every_row_and_keep_successful_batch(monkeypatch):
    monkeypatch.setattr(ai_review, "MAX_CHARACTERS", 200_000)
    doc = ParsedDocument(items=[device().items[0] for _ in range(205)])
    seen = []

    def call(prompt, schema):
        batch = json.loads(prompt.rsplit("\n", 1)[1])["rows"]
        seen.extend(row["row_id"] for row in batch)
        assert len(prompt) <= ai_review.MAX_CHARACTERS
        assert len(batch) <= 100
        if len(seen) > 200:
            raise LlmUnavailable("failed final batch")
        return checked(prompt, schema)

    install(monkeypatch, call)
    review_document(doc)
    assert seen == list(map(str, range(205)))
    assert doc.review_summary["checked"] == 200
    assert doc.review_summary["status"] == "partial"
    assert all(item.status == "verified" for item in doc.items[:200])
    assert all(item.verification_source is None for item in doc.items[200:])


def test_character_batches_and_oversized_source_are_explicit(monkeypatch):
    doc = ParsedDocument(
        items=[device(name="Diagnostic scanner " + "x" * 5000).items[0] for _ in range(5)]
    )
    call = install(monkeypatch)
    review_document(doc)
    assert call.call_count > 1
    assert all(len(c.args[0]) <= ai_review.MAX_CHARACTERS for c in call.call_args_list)
    huge = device(name="Scanner " + "x" * 40_000)
    review_document(huge)
    assert huge.review_summary["status"] == "unavailable"
    assert any("size limit" in r for r in huge.items[0].review_reasons)


def test_manual_rows_are_not_sent_or_changed(monkeypatch):
    doc = device()
    doc.items[0].manual = True
    call = install(monkeypatch)
    review_document(doc)
    assert call.call_count == 0
    assert doc.items[0].unit == ""


def test_missing_or_extra_rows_are_reported_without_changing_count(monkeypatch):
    doc = device()
    install(
        monkeypatch,
        response(issues=[Issue(row_id="0", reason="Another source row may be missing")]),
    )
    review_document(doc)
    assert len(doc.items) == 1
    assert doc.items[0].status == "needs_review"
    assert "missing" in doc.items[0].review_reasons[0]


def test_large_free_text_retains_complete_source_rows_in_bounded_batches(monkeypatch):
    from app.parsing.review_context import text_review_source

    lines = [f"Diagnostic scanner model {index}: 2 pcs" for index in range(1000)]
    text = "\n".join(lines)
    items = [
        ParsedLineItem(
            name=f"Diagnostic scanner model {index}",
            quantity=2,
            unit="pcs",
            domain="equipment",
            excerpt=line,
        )
        for index, line in enumerate(lines)
    ]
    for item in items:
        item.review_source = text_review_source(text, item)
        assert item.excerpt in item.review_source["text"]
    doc = ParsedDocument(items=items)
    calls = install(
        monkeypatch,
        lambda prompt, schema: response(count=len(json.loads(prompt.rsplit("\n", 1)[1])["rows"])),
    )
    review_document(doc)
    assert doc.review_summary["checked"] == 1000
    assert doc.review_summary["unresolved"] == 0
    assert all(len(call.args[0]) <= ai_review.MAX_CHARACTERS for call in calls.call_args_list)


def test_explicit_type_cannot_be_overridden_by_an_inference(monkeypatch):
    doc = device()
    item = doc.items[0]
    item.review_source["roles"]["3"] = "domain"
    item.review_source["cells"]["3"] = "Medicine"
    install(monkeypatch)
    review_document(doc)
    assert item.status == "needs_review"
    assert item.domain is None


def test_human_confirmation_keeps_inference_provenance(monkeypatch):
    doc = device()
    item = doc.items[0]
    item.domain, item.unit = "equipment", "pcs"
    item.protected_fields = ["domain", "unit"]
    item.inferred_fields = {"unit": "Original evidence"}
    item.verification_source = "human"
    install(monkeypatch)
    review_document(doc)
    assert item.inferred_fields == {"unit": "Original evidence"}
    assert item.verification_source == "human"
    assert item.status == "verified"


def test_packaging_noun_is_not_a_source_stated_requested_unit(monkeypatch):
    doc = device(name="Antibiotic vial 500mg")
    doc.items[0].domain = "medicine"
    install(monkeypatch, response([patch("unit", "vial", evidence="vial")]))
    review_document(doc)
    assert doc.items[0].unit == ""
    assert doc.items[0].status == "needs_review"
    assert doc.review_summary["status"] == "unavailable"


def test_unit_in_an_explicit_requested_quantity_is_source_stated(monkeypatch):
    doc = parse_table_rows([["Product", "Quantity"], ["Antibiotic", "3 vials"]])
    install(monkeypatch, response([patch("unit", "vials", evidence="3 vials")]))
    review_document(doc)
    assert doc.items[0].unit == "vials"
    assert doc.items[0].status == "verified"
    assert "unit" not in doc.items[0].inferred_fields
