"""Tests for user-requested custom column extraction (see IngestionScreen).

Hint-based matching is pure/deterministic and tested directly. The "no LLM key" path is
exercised through parse_table_rows, mirroring force_llm_unavailable's use elsewhere in this
suite; genuine LLM semantic matching (no hint given) is not covered here since it requires a
live call - see the manual verification in the PR/commit history instead.
"""

from app.parsing.table_parser import parse_table_rows
from app.parsing.types import CustomColumnSpec
from tests.test_parsing import force_llm_unavailable


def test_custom_column_matches_by_hint_without_any_llm_call() -> None:
    rows = [
        ["Item", "Quantity", "Unit", "Manufacturer"],
        ["Amoxicillin 500mg Capsules", 2000, "caps", "Reyoung Pharmaceutical"],
    ]
    specs = [CustomColumnSpec(display_name="Maker", hint="Manufacturer")]

    result = parse_table_rows(rows, custom_columns=specs)

    assert "Maker" in result.attribute_columns
    assert result.items[0].attributes["Maker"] == "Reyoung Pharmaceutical"


def test_custom_column_hint_match_overrides_supplier_exclusion() -> None:
    # "Supplier code" opens a supplier block that table_parser normally excludes entirely - an
    # explicit custom-column request must still be able to reach into it.
    rows = [
        ["Item", "Quantity", "Unit", "Supplier code", "Unit Price"],
        ["Amoxicillin 500mg Capsules", 2000, "caps", "SUP-001", 1.33],
    ]
    specs = [CustomColumnSpec(display_name="Price", hint="Unit Price")]

    result = parse_table_rows(rows, custom_columns=specs)

    assert result.items[0].attributes["Price"] == "1.33"
    assert "Price" in result.attribute_columns


def test_custom_column_without_hint_falls_back_to_missing_without_llm_key(monkeypatch) -> None:
    force_llm_unavailable(monkeypatch)

    rows = [
        ["Item", "Quantity", "Unit", "Batch No."],
        ["Amoxicillin 500mg Capsules", 2000, "caps", "B12345"],
    ]
    specs = [CustomColumnSpec(display_name="Lot Code", hint="")]  # no hint -> needs the LLM

    result = parse_table_rows(rows, custom_columns=specs)

    assert "Lot Code" not in result.attribute_columns
    assert any("Could not find a column" in warning for warning in result.warnings)
    # The column that WAS findable via keyword matching stays visible regardless.
    assert "Batch No." in result.attribute_columns


def test_custom_column_survives_even_when_blank_on_every_row() -> None:
    # Unlike normal attribute columns (dropped if empty everywhere), an explicit user request
    # should never just silently vanish - the column shows up, even if this file has nothing in
    # it, so the user can see it was looked for.
    rows = [
        ["Item", "Quantity", "Unit", "Manufacturer"],
        ["Amoxicillin 500mg Capsules", 2000, "caps", None],
    ]
    specs = [CustomColumnSpec(display_name="Maker", hint="Manufacturer")]

    result = parse_table_rows(rows, custom_columns=specs)

    assert "Maker" in result.attribute_columns
    assert "Maker" not in result.items[0].attributes  # blank value just isn't set on the item
