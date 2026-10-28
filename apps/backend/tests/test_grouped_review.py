"""Shared review rules exercised without providers or persistence."""

import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.review.contracts import ReviewOperation
from app.review.engine import project, synchronize
from app.review.service import State, evaluate


def review_fixture(count=48):
    request = State(
        request_id="review-fixture",
        workflow_status="review",
        review_revision=0,
        selected_sheet="Request",
        selected_sheets=["Request"],
        parser_warnings=[],
        ai_review={"sources": {}},
        items=[],
        review_issues=[],
    )
    for i in range(1, count + 1):
        name = (
            "Thermometer"
            if i <= 6
            else "Amoxicillin 500mg tablets"
            if i <= 8
            else f"Clinical supply {i}"
        )
        item = SimpleNamespace(
            id=i,
            name=name,
            quantity=10,
            unit="pcs",
            notes="",
            item_number="",
            shelf_life="",
            attributes={},
            priority="medium",
            confidence=95,
            status="verified",
            domain=None if i <= 8 else "equipment",
            manual=False,
            verification_source="ai",
            inferred_fields={},
            protected_fields=[],
            field_reviews={},
            review_findings=[],
            review_reasons=[],
            removed_at=None,
            removed_by=None,
            source_active=True,
            source_reference=SimpleNamespace(page=0, row=i + 1, excerpt=f"{name} | source row {i}"),
        )
        cells = {"0": name, "1": "10", "2": "", "3": ""}
        if 8 <= i <= 11:
            item.quantity = 800
            cells.update({"1": "800", "2": "10", "3": "100"})
        if i in (12, 13):
            item.quantity = None
            cells["1"] = ""
        if i in (14, 15):
            item.unit = "?"
        if i == 16:
            item.review_findings = [
                {
                    "code": "other",
                    "fields": [],
                    "message": "Inspect the presentation",
                    "origin": "ai",
                }
            ]
        request.items.append(item)
        request.ai_review["sources"][str(i)] = {
            "worksheet": "Request",
            "headers": {"0": "Product", "1": "Quantity", "2": "Packs", "3": "Units per pack"},
            "roles": {"0": "name", "1": "quantity", "2": "quantity_packs", "3": "units_per_pack"},
            "cells": cells,
        }
    return request


def operation(request, action, ids, **extra):
    return ReviewOperation(
        operationId="test-op",
        expectedRevision=request.review_revision,
        action=action,
        itemIds=ids,
        **extra,
    )


def test_reference_dataset_and_overlapping_issues():
    request = review_fixture()
    initial = synchronize(request)
    assert initial["reviewCounts"] == {
        "active": 48,
        "ready": 32,
        "affected": 16,
        "issues": 17,
        "removed": 0,
    }
    assert len(initial["tasks"]) == 6
    state, _, _, preview = evaluate(
        request, operation(request, "edit", [8], changes={"domain": "medicine"})
    )
    result = project(state)
    assert result["reviewCounts"]["issues"] == 16
    assert result["reviewCounts"]["affected"] == 16
    assert 8 not in result["readyIds"]
    assert preview["blockers"] == []
    assert request.items[7].domain is None  # previews never mutate the request


def test_quantity_rule_keeps_different_row_values_and_records_conflict_decision():
    request = review_fixture()
    synchronize(request)
    state, _, _, _ = evaluate(
        request, operation(request, "quantity_rule", [9, 10], rule="pack_calculation")
    )
    assert state.items[8].quantity == 1000
    assert 9 in project(state)["readyIds"]
    assert 10 in project(state)["readyIds"]
    assert request.items[8].quantity == 800


def test_unit_label_change_never_changes_quantity():
    request = review_fixture()
    synchronize(request)
    state, _, _, _ = evaluate(
        request, operation(request, "edit", [14, 15], changes={"unit": "pieces"})
    )
    assert [state.items[i - 1].quantity for i in (14, 15)] == [10, 10]
    assert {14, 15} <= set(project(state)["readyIds"])


def test_acceptance_reopens_when_evidence_changes_but_not_unrelated_rows():
    request = review_fixture()
    projection = synchronize(request)
    issue = next(i for i in projection["issues"] if i["itemId"] == 16)
    state, _, _, _ = evaluate(request, operation(request, "accept", [16], issueIds=[issue["id"]]))
    assert 16 in project(state)["readyIds"]
    state.items[15].attributes = {"Newly extracted column": "Unrelated metadata"}
    assert 16 in project(state)["readyIds"]
    state.items[20].notes = "Unrelated edit"
    assert 16 in project(state)["readyIds"]
    state.ai_review["sources"]["16"]["cells"]["0"] = "Changed source identity"
    assert 16 not in project(state)["readyIds"]


def test_required_values_cannot_be_accepted_and_invalid_batches_do_not_mutate():
    request = review_fixture()
    projection = synchronize(request)
    before = copy.deepcopy(request.items[20].__dict__)
    with pytest.raises(HTTPException) as error:
        evaluate(
            request,
            operation(
                request, "edit", [21, 22], itemChanges={21: {"quantity": 20}, 22: {"quantity": 0}}
            ),
        )
    assert error.value.status_code == 422
    assert request.items[20].__dict__ == before
    issue = next(i for i in projection["issues"] if i["code"] == "quantity_invalid")
    with pytest.raises(HTTPException):
        evaluate(request, operation(request, "accept", [], issueIds=[issue["id"]]))


def test_mixed_verification_selection_and_stale_revision():
    request = review_fixture()
    synchronize(request)
    _, _, _, preview = evaluate(request, operation(request, "verify", [8, 21]))
    assert preview["eligibleItemIds"] == [21]
    assert preview["blockers"][0]["itemId"] == 8
    request.review_revision = 1
    with pytest.raises(HTTPException) as error:
        evaluate(
            request,
            ReviewOperation(operationId="stale", expectedRevision=0, action="remove", itemIds=[21]),
        )
    assert error.value.status_code == 409


def test_removal_and_restoration_recalculate_issues_without_losing_evidence():
    request = review_fixture()
    synchronize(request)
    state, _, _, _ = evaluate(request, operation(request, "remove", [8]))
    assert project(state)["reviewCounts"]["issues"] == 15
    assert project(state)["reviewCounts"]["removed"] == 1
    state.workflow_status, state.review_revision = "review", 0
    restored, _, _, _ = evaluate(state, operation(state, "restore", [8]))
    assert project(restored)["reviewCounts"]["issues"] == 17
    assert restored.items[7].source_reference.excerpt == request.items[7].source_reference.excerpt


def test_large_import_groups_locally_and_stably_without_provider_calls():
    request = review_fixture(2000)
    first = project(request)
    assert first["tasks"] == project(request)["tasks"]
    assert first["reviewCounts"]["active"] == 2000
    assert len(first["tasks"]) == 6


def test_equivalent_ai_and_rule_findings_are_deduplicated():
    request = review_fixture()
    request.items[8].review_findings = [
        {
            "code": "pack_total_conflict",
            "fields": ["quantity"],
            "message": "Source pack factors disagree with total",
            "origin": "ai",
        }
    ]
    result = project(request)
    findings = [
        i for i in result["issues"] if i["itemId"] == 9 and i["code"] == "pack_total_conflict"
    ]
    assert len(findings) == 1
    assert findings[0]["origins"] == ["ai", "rules"]


def test_document_coverage_requires_explicit_reconciliation_after_manual_additions():
    request = review_fixture()
    request.parser_warnings = [
        "No requested line items could be extracted; check the source table or add items manually"
    ]
    result = project(request)
    assert any(i["itemId"] is None and i["state"] == "open" for i in result["issues"])
