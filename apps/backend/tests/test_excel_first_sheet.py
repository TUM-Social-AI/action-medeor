"""Request imports use the first worksheet, including when it is empty."""

import io
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.parsing import llm_table_classifier
from app.parsing.excel_parser import _read_xls
from app.parsing.service import parse_upload


def workbook_bytes(first_rows, later_rows):
    workbook = Workbook()
    first = workbook.active
    first.title = "First sheet"
    for row in first_rows:
        first.append(row)
    later = workbook.create_sheet("Other request")
    for row in later_rows:
        later.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


@pytest.mark.parametrize("first_rows", [[], [[None]], [["   "]]])
def test_empty_first_sheet_is_not_replaced_by_populated_later_sheet(monkeypatch, first_rows):
    call = Mock(side_effect=AssertionError("An empty sheet needs no column mapping"))
    monkeypatch.setattr(llm_table_classifier, "call_llm", call)
    document = parse_upload(
        filename="request.xlsx",
        content=workbook_bytes(first_rows, [
            ["Product", "Quantity", "Unit"], ["Other-sheet device", 20, "pcs"],
        ]),
    )
    assert document.items == []
    assert document.rows_detected == 0
    assert call.call_count == 0
    assert any("No requested line items could be extracted" in note for note in document.warnings)
    assert any(
        "only the first is imported" in note
        and "future feature" in note
        and "delete the unnecessary sheets" in note
        for note in document.warnings
    )
    assert document.partner == {"partner": "", "region": "", "contact": ""}


def test_populated_first_sheet_ignores_other_sheet_items_and_metadata(monkeypatch):
    call = Mock(side_effect=AssertionError("A clear first sheet needs no mapping"))
    monkeypatch.setattr(llm_table_classifier, "call_llm", call)
    document = parse_upload(
        filename="request.xlsx",
        content=workbook_bytes(
            [["Product", "Quantity", "Unit"], ["First-sheet device", 2, "pcs"]],
            [["Requester", "Other organization"], ["Product", "Quantity", "Unit"],
             ["Other-sheet device", 900, "boxes"]],
        ),
    )
    assert [(item.name, item.quantity, item.unit) for item in document.items] == [
        ("First-sheet device", 2, "pcs"),
    ]
    assert document.partner["partner"] == ""
    assert call.call_count == 0
    assert not any("future feature" in note for note in document.warnings)


def test_xls_reader_uses_empty_first_sheet_even_with_additional_sheets(monkeypatch):
    import xlrd

    first = Mock(nrows=0)
    workbook = Mock(nsheets=2)
    workbook.sheet_by_index.return_value = first
    monkeypatch.setattr(xlrd, "open_workbook", Mock(return_value=workbook))
    assert _read_xls(b"local test workbook") == ([], 2)
    workbook.sheet_by_index.assert_called_once_with(0)
    workbook.sheets.assert_not_called()
