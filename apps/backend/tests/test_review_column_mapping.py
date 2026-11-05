"""Human mapping changes use only stored request cells and remain reversible."""

import copy

import pytest
from fastapi import HTTPException

from app.review.engine import project, synchronize
from app.review.service import evaluate, restore_snapshot
from tests.test_grouped_review import operation, review_fixture


def mapping_fixture():
    request = review_fixture(3)
    for index, item in enumerate(request.items):
        item.domain = "equipment"
        source = request.ai_review["sources"][str(item.id)]
        source.update(
            {
                "worksheet": "Corrected table" if index < 2 else "Other table",
                "headers": {
                    "0": "Product",
                    "1": "Old amount",
                    "2": "Requested amount",
                    "3": "Unit",
                },
                "roles": {"0": "name", "1": "quantity", "3": "unit"},
                "cells": {"0": item.name, "1": "10", "2": str(20 + index), "3": "pcs"},
                "mappingUncertain": index < 2,
            }
        )
    issue = next(i for i in synchronize(request)["issues"] if i["code"] == "mapping_uncertain")
    return request, issue


ROLES = {"0": "name", "1": "attribute", "2": "quantity", "3": "unit"}


def test_remapping_previews_copied_values_and_changes_only_the_affected_table():
    request, issue = mapping_fixture()
    original = copy.deepcopy(request.ai_review)
    state, before, _, preview = evaluate(
        request,
        operation(
            request,
            "column_mapping",
            [1, 2],
            issueIds=[issue["id"]],
            columnRoles=ROLES,
        ),
    )
    assert request.ai_review == original
    assert [item.quantity for item in state.items] == [20, 21, 10]
    assert state.ai_review["sources"]["3"] == original["sources"]["3"]
    assert preview["changes"][0]["fields"]["quantity"] == {"before": 10, "after": 20}
    assert preview["tableDecision"]["affectedItems"] == 2
    assert not any(
        i["code"] == "mapping_uncertain" and i["state"] == "open" for i in project(state)["issues"]
    )
    restore_snapshot(state, before)
    assert state.ai_review == original
    assert [item.quantity for item in state.items] == [10, 10, 10]
    assert any(
        i["code"] == "mapping_uncertain" and i["state"] == "open" for i in project(state)["issues"]
    )


def test_remapping_preserves_manual_fields_and_keeps_their_source_conflict_open():
    request, issue = mapping_fixture()
    request.items[0].quantity = 77
    request.items[0].protected_fields = ["quantity"]
    state, _, _, preview = evaluate(
        request,
        operation(
            request,
            "column_mapping",
            [],
            issueIds=[issue["id"]],
            columnRoles=ROLES,
        ),
    )
    assert state.items[0].quantity == 77
    assert "quantity" not in preview["changes"][0]["fields"]
    assert any(
        i["itemId"] == 1 and i["code"] == "quantity_conflict" and i["state"] == "open"
        for i in project(state)["issues"]
    )


@pytest.mark.parametrize(
    "roles,ids",
    [
        ({**ROLES, "99": "unit"}, []),
        ({**ROLES, "1": "quantity"}, []),
        ({**ROLES, "0": "attribute"}, []),
        ({**ROLES, "3": "supplier_quantity"}, []),
        (ROLES, [1]),
    ],
)
def test_invalid_or_partial_table_changes_do_not_mutate_the_request(roles, ids):
    request, issue = mapping_fixture()
    original = copy.deepcopy(request.ai_review)
    with pytest.raises(HTTPException):
        evaluate(
            request,
            operation(request, "column_mapping", ids, issueIds=[issue["id"]], columnRoles=roles),
        )
    assert request.ai_review == original
    assert [item.quantity for item in request.items] == [10, 10, 10]
