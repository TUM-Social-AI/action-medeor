"""Tests for the LLM-assisted quantity gap-filler.

Only engages when the heuristic scoped columns as part of the partner's request but found no
quantity signal among them at all - the merge logic (_apply_gap_fill) is pure and tested
directly without any network call. The "no key configured" path is exercised end to end through
parse_table_rows, mirroring force_llm_unavailable's use elsewhere in this suite.
"""

from app.parsing.llm_table_classifier import (
    _apply_gap_fill,
    _QuantityColumnClassification,
    _QuantityGapResult,
)
from app.parsing.table_parser import HeaderLayout, parse_table_rows
from tests.test_parsing import force_llm_unavailable


def _layout_with_gap() -> HeaderLayout:
    return HeaderLayout(
        row_index=0,
        roles={0: "name"},
        extras={1: "Packs Requested", 2: "Units Per Pack", 3: "Manufacturer"},
        labels={0: "Product", 1: "Packs Requested", 2: "Units Per Pack", 3: "Manufacturer"},
    )


def test_apply_gap_fill_promotes_pack_pair_to_roles() -> None:
    result = _QuantityGapResult(
        columns=[
            _QuantityColumnClassification(column_index=1, role="quantity_packs"),
            _QuantityColumnClassification(column_index=2, role="units_per_pack"),
            _QuantityColumnClassification(column_index=3, role="none"),
        ]
    )

    updated = _apply_gap_fill(_layout_with_gap(), candidate_columns=[1, 2, 3], result=result)

    assert updated.roles[1] == "quantity_packs"
    assert updated.roles[2] == "units_per_pack"
    assert 1 not in updated.extras
    assert 2 not in updated.extras
    assert 3 in updated.extras  # "none" stays an attribute, not dropped


def test_apply_gap_fill_ignores_duplicate_role_assignment() -> None:
    # If the model assigns quantity_packs to two columns, the first (lowest index) wins.
    result = _QuantityGapResult(
        columns=[
            _QuantityColumnClassification(column_index=1, role="quantity_packs"),
            _QuantityColumnClassification(column_index=2, role="quantity_packs"),
        ]
    )

    updated = _apply_gap_fill(_layout_with_gap(), candidate_columns=[1, 2], result=result)

    assert updated.roles[1] == "quantity_packs"
    assert 2 not in updated.roles
    assert 2 in updated.extras


def test_apply_gap_fill_original_layout_untouched() -> None:
    original = _layout_with_gap()
    result = _QuantityGapResult(
        columns=[_QuantityColumnClassification(column_index=1, role="quantity_packs")]
    )

    _apply_gap_fill(original, candidate_columns=[1], result=result)

    # The function must return a new layout, not mutate the one it was given.
    assert 1 not in original.roles


def test_parse_table_rows_recognizes_common_pack_phrasing_without_any_llm_call() -> None:
    # "Packs Requested" / "Units Per Pack" are common enough phrasings to be worth naming
    # directly in keywords.py (QUANTITY_PACKS_KEYWORDS/UNITS_PER_PACK_KEYWORDS) - deterministic,
    # free, and it also keeps "Units Per Pack" from being misread as the generic unit-of-measure
    # role (it contains "unit"), which would otherwise make it unavailable as a gap-fill
    # candidate for less predictable phrasings of the same pattern.
    rows = [
        ["Product", "Packs Requested", "Units Per Pack"],
        ["Item one", 15, 100],
    ]

    result = parse_table_rows(rows)
    item = result.items[0]

    assert result.used_llm_fallback is False
    assert item.quantity == 1500
    assert item.attributes["Packs requested"] == "15"
    assert item.attributes["Units per pack"] == "100"


def test_parse_table_rows_leaves_quantity_missing_for_novel_phrasing_without_llm_key(
    monkeypatch,
) -> None:
    force_llm_unavailable(monkeypatch)

    # Phrasing that matches none of the deterministic keyword lists, so this genuinely exercises
    # the gap-fill path (unlike the common "Packs Requested" phrasing above).
    rows = [
        ["Product", "Boxes Wanted", "Contents Per Box"],
        ["Item one", 15, 100],
    ]

    result = parse_table_rows(rows)
    item = result.items[0]

    # No LLM key -> gap-fill silently unavailable -> falls through to the existing "no quantity
    # column found" behavior (status missing), same as before this feature existed.
    assert item.quantity is None
    assert item.status == "missing"


def test_parse_table_rows_does_not_attempt_gap_fill_when_quantity_already_found(monkeypatch) -> None:
    # A quantity role was already found heuristically - the gap-filler must not even be invoked,
    # so this must pass regardless of LLM key configuration. Force-unavailable anyway to prove
    # the call path doesn't depend on it.
    force_llm_unavailable(monkeypatch)

    rows = [
        ["Item", "Quantity", "Unit"],
        ["Amoxicillin 500mg Capsules", 2000, "caps"],
    ]

    result = parse_table_rows(rows)

    assert result.items[0].quantity == 2000
