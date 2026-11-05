"""Verification flags discrepancies and only fills confident, genuinely empty fields."""

import json

import pytest

from app.parsing import ai_review
from app.parsing.ai_review import Correction, Inference, ReviewBatch
from app.parsing.table_parser import parse_table_rows


def verify(monkeypatch, document, *, inferences=(), corrections=()):
    monkeypatch.setattr(ai_review, "call_llm", lambda *_: ReviewBatch(
        completed=True, reviewed_count=len(document.items), confidence=95,
        inferences=list(inferences), corrections=list(corrections), issues=[],
    ))
    return ai_review.review_document(document)


def row():
    return parse_table_rows([["Product", "Quantity", "Unit"], ["Clinical supply A", 12, "pcs"]])


def test_provider_contract_contains_no_corrections_or_column_patches():
    schema = json.dumps(ai_review.ReviewBatch.model_json_schema())
    assert '"corrections"' not in schema
    assert "source_column" not in schema
    assert "inferences" in schema


@pytest.mark.parametrize("field,value", [
    ("name", "Other product"), ("quantity", 99), ("unit", "boxes"),
    ("domain", "medicine"), ("notes", "Different note"),
    ("item_number", "NEW-ID"), ("shelf_life", "36 months"),
])
def test_existing_values_are_never_changed_even_by_legacy_corrections(monkeypatch, field, value):
    doc = row()
    item = doc.items[0]
    item.domain, item.notes, item.item_number, item.shelf_life = "equipment", "Keep note", "OLD-ID", "12 months"
    before = {field: getattr(item, field) for field in ai_review.FIELDS}
    verify(monkeypatch, doc, corrections=[Correction(
        row_id="row-0001", field=field, value=value, inferred=False,
        evidence="", source_column=999,
    )])
    assert {field: getattr(item, field) for field in ai_review.FIELDS} == before
    assert item.status == "needs_review"
    assert all("unsupported source column" not in message for message in item.review_reasons)
    assert doc.review_summary["corrected"] == 0
    assert doc.review_summary["failures"] == {}


@pytest.mark.parametrize("confidence,filled", [(89, False), (90, True), (99, True)])
def test_only_confident_missing_types_are_filled(monkeypatch, confidence, filled):
    doc = row()
    doc.items[0].domain = None
    verify(monkeypatch, doc, inferences=[Inference(
        row_id="row-0001", field="domain", value="equipment", confidence=confidence,
        evidence="Clinical supply A",
    )])
    assert doc.items[0].domain == ("equipment" if filled else None)
    assert doc.review_summary["filled"] == int(filled)
    assert doc.review_summary["corrected"] == 0


@pytest.mark.parametrize("evidence", ["Unstated product", "   "])
def test_inferences_require_literal_source_support(monkeypatch, evidence):
    doc = row()
    doc.items[0].domain = None
    verify(monkeypatch, doc, inferences=[Inference(
        row_id="row-0001", field="domain", value="equipment", confidence=99, evidence=evidence,
    )])
    assert doc.items[0].domain is None
    assert doc.items[0].status == "needs_review"


def test_confident_device_unit_can_fill_an_empty_field(monkeypatch):
    doc = row()
    doc.items[0].unit, doc.items[0].domain = "", "equipment"
    verify(monkeypatch, doc, inferences=[Inference(
        row_id="row-0001", field="unit", value="pcs", confidence=95, evidence="Clinical supply A",
    )])
    assert doc.items[0].unit == "pcs"
    assert doc.items[0].quantity == 12


def test_ambiguous_medicine_packaging_stays_empty(monkeypatch):
    doc = parse_table_rows([["Product", "Quantity"], ["Paracetamol 500 mg tablets", 10]])
    doc.items[0].unit, doc.items[0].domain = "", "medicine"
    verify(monkeypatch, doc, inferences=[Inference(
        row_id="row-0001", field="unit", value="packs", confidence=99,
        evidence="Paracetamol 500 mg tablets",
    )])
    assert doc.items[0].unit == ""
    assert doc.items[0].status == "needs_review"


def test_existing_default_units_are_not_replaced(monkeypatch):
    doc = parse_table_rows([["Product", "Quantity"], ["Diagnostic scanner", 10]])
    doc.items[0].domain = "equipment"
    assert doc.items[0].unit == "Stück"
    verify(monkeypatch, doc, inferences=[Inference(
        row_id="row-0001", field="unit", value="pcs", confidence=99, evidence="Diagnostic scanner",
    )])
    assert doc.items[0].unit == "Stück"
    assert doc.items[0].status == "needs_review"
