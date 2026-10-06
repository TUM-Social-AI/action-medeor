"""Synthetic cover-sheet layout: copy the real table before reviewing its items."""

import json
from unittest.mock import Mock

from app.parsing import ai_review, llm_table_classifier
from app.parsing.ai_review import Correction, Issue, PartnerReviewBatch, review_document
from app.parsing.llm_table_classifier import ColumnMapping, TableMapping
from app.parsing.service import parse_upload
from tests.test_parsing import build_xlsx


def covered_request_rows():
    return [
        ["Emergency Medical Supply Request"],
        ["Generated anonymous regression fixture"],
        [],
        ["Partner", "Example Relief", None, "Request ID", "EXAMPLE-123", None, "Priority", "Emergency"],
        ["Region", "Example Region", None, "Request Date", "2024-06-11", None, "Required Delivery", "Soon"],
        ["Contact", "Test Coordinator", None, "Destination Hub", "Example pharmacy"],
        ["File Name", "example.xlsx", None, "Program", "Response"],
        [],
        ["Partner note: Please review uncertain product specifications"],
        [],
        ["#", "Original request text", "Qty", "Unit", "Specification / notes from field", "Urgency", "Destination", "Reviewer note"],
        [1, "Example antibiotic 250mg capsules", 7, "caps", "Preserve blister presentation", "Critical", "Example hub", "Clear request"],
        [2, "Example pain relief 250mg tablets", 14, "tabs", "Generic acceptable", "High", "Example hub", "Clear request"],
        [3, "ORS sachets standard formula", 21, "sachets", "Oral rehydration salts", "High", "Example hub", "Clear request"],
        [4, "Sodium chloride IV infusion bags 250ml", 28, "bags", "Sterile infusion solution", "Critical", "Example hub", "Clear request"],
        [5, "Sterile wound dressing pads", 35, "pcs", "Dressing specification is unclear", "Medium", "Example hub", "Check dressing specification"],
        [6, "Example antibiotic injection vials", 42, "vials", "For clinical administration", "Critical", "Example hub", "Clear request"],
        [7, "Surgical gloves medium latex-free", 49, "pairs", "Individually wrapped", "Medium", "Example hub", "Clear request"],
        [8, "Example medicine tablets", 56, "tabs", "Strength is unclear", "High", "Example hub", "Confirm strength"],
    ]


def covered_request_mapping():
    roles = {0: "ordinal", 1: "name", 2: "quantity", 3: "unit", 4: "notes", 5: "priority", 6: "attribute", 7: "attribute"}
    return TableMapping(header_row_index=10, columns=[
        ColumnMapping(column_index=index, role=role, scope="request")
        for index, role in roles.items()
    ])


def checked_covered_request(prompt, schema):
    payload = json.loads(prompt.rsplit("\n", 1)[1])
    assert len(payload["rows"]) == 8
    assert [row["row"] for row in payload["rows"]] == list(range(12, 20))
    return PartnerReviewBatch(
        completed=True, reviewed_count=8, confidence=96, partner_json='{"partner":null,"region":null,"contact":null}',
        corrections=[Correction(
            row_id=row["row_id"], field="domain", value="equipment" if index in {4, 6} else "medicine",
            inferred=True, evidence="", source_column=1,
        ) for index, row in enumerate(payload["rows"])],
        issues=[Issue(row_id=payload["rows"][index]["row_id"], reason=reason) for index, reason in [
            (4, "Dressing specification is unclear"), (7, "Medicine strength needs confirmation"),
        ]],
    )


def test_balanced_reviews_real_rows_after_cover_metadata_and_preserves_copy(monkeypatch):
    rows = covered_request_rows()
    mapping = Mock(return_value=covered_request_mapping())
    review = Mock(side_effect=checked_covered_request)
    monkeypatch.setattr(llm_table_classifier, "call_llm", mapping)
    monkeypatch.setattr(ai_review, "call_llm", review)
    document = parse_upload(filename="example.xlsx", content=build_xlsx(rows))
    document.extraction_mode = "balanced"
    review_document(document)
    assert [(item.name, item.quantity, item.unit, item.notes) for item in document.items] == [
        (row[1], row[2], row[3], row[4]) for row in rows[11:]
    ]
    assert mapping.call_count == 1 and review.call_count == 1
    assert document.review_summary["checked"] == 8
    assert document.review_summary["unresolved"] == 2
    assert sum(item.verification_source == "ai" for item in document.items) == 6
    assert all(item.domain for item in document.items)
    assert document.partner == {"partner": "Example Relief", "region": "Example Region", "contact": "Test Coordinator"}
    assert not any("Conflicting requester" in warning for warning in document.warnings)
