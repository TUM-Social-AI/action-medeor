"""Request imports use the first worksheet by default, including when it is empty; any other
worksheet can be chosen explicitly."""

import io
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.parsing import llm_table_classifier
from app.parsing.excel_parser import _read_xls
from app.parsing.llm_client import LlmUnavailable
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
        content=workbook_bytes(
            first_rows,
            [
                ["Product", "Quantity", "Unit"],
                ["Other-sheet device", 20, "pcs"],
            ],
        ),
    )
    assert document.items == []
    assert document.rows_detected == 0
    assert call.call_count == 0
    assert any("No requested line items could be extracted" in note for note in document.warnings)
    assert any(
        "other worksheets" in note and "when uploading" in note for note in document.warnings
    )
    assert document.sheets == [
        {"name": "First sheet", "rows": 0}, {"name": "Other request", "rows": 2},
    ]
    assert document.selected_sheet == "First sheet"
    assert document.partner == {"partner": "", "region": "", "contact": ""}


def test_populated_first_sheet_ignores_other_sheet_items_and_metadata(monkeypatch):
    call = Mock(side_effect=AssertionError("A clear first sheet needs no mapping"))
    monkeypatch.setattr(llm_table_classifier, "call_llm", call)
    document = parse_upload(
        filename="request.xlsx",
        content=workbook_bytes(
            [["Product", "Quantity", "Unit"], ["First-sheet device", 2, "pcs"]],
            [
                ["Requester", "Other organization"],
                ["Product", "Quantity", "Unit"],
                ["Other-sheet device", 900, "boxes"],
            ],
        ),
    )
    assert [(item.name, item.quantity, item.unit) for item in document.items] == [
        ("First-sheet device", 2, "pcs"),
    ]
    assert document.partner["partner"] == ""
    assert call.call_count == 0
    assert not any("other worksheets" in note for note in document.warnings)


def test_xls_reader_uses_empty_first_sheet_even_with_additional_sheets(monkeypatch):
    import xlrd

    first = Mock(nrows=0)
    first.name = "First"
    later = Mock(nrows=1, row_values=Mock(return_value=["Product", 5]))
    later.name = "Later"
    workbook = Mock()
    workbook.sheet_names.return_value = ["First", "Later"]
    workbook.sheet_by_index.return_value = first
    workbook.sheet_by_name.side_effect = {"First": first, "Later": later}.__getitem__
    monkeypatch.setattr(xlrd, "open_workbook", Mock(return_value=workbook))
    rows, sheets, selected = _read_xls(b"local test workbook", None)
    assert (rows, selected) == ([], "First")  # never silently swapped for the populated sheet
    assert sheets == [{"name": "First", "rows": 0}, {"name": "Later", "rows": 1}]
    workbook.sheet_by_index.assert_called_once_with(0)


def test_another_worksheet_can_be_chosen_by_name(monkeypatch):
    monkeypatch.setattr(llm_table_classifier, "call_llm", Mock(side_effect=LlmUnavailable("off")))
    content = workbook_bytes(
        [["Product", "Quantity", "Unit"], ["First-sheet device", 2, "pcs"]],
        [["Product", "Quantity", "Unit"], ["Other-sheet device", 900, "boxes"]],
    )
    document = parse_upload(filename="request.xlsx", content=content, sheet="Other request")
    assert [(item.name, item.quantity) for item in document.items] == [("Other-sheet device", 900)]
    assert document.selected_sheet == "Other request"


def test_unknown_worksheet_is_a_clear_parsing_error():
    from app.parsing.service import ParsingError

    content = workbook_bytes([["Product"], ["Device"]], [])
    with pytest.raises(ParsingError, match="not found"):
        parse_upload(filename="request.xlsx", content=content, sheet="Nope")


def test_multiple_sheets_keep_source_coordinates_and_custom_columns(monkeypatch):
    from app.parsing.types import CustomColumnSpec

    monkeypatch.setattr(llm_table_classifier, "call_llm", Mock(side_effect=LlmUnavailable("off")))
    content = workbook_bytes(
        [["Product", "Quantity", "Unit", "Supplier"], ["First device", 2, "pcs", "Alpha"]],
        [["Product", "Quantity", "Unit", "Supplier"], ["Other device", 9, "pcs", "Beta"]],
    )
    document = parse_upload(
        filename="request.xlsx", content=content, selected_sheets=["Other request", "First sheet"]
    )
    assert [item.name for item in document.items] == ["First device", "Other device"]
    assert [(item.page, item.row) for item in document.items] == [(1, 2), (2, 2)]
    assert document.selected_sheets == ["First sheet", "Other request"]
    reparsed = parse_upload(
        filename="request.xlsx",
        content=content,
        selected_sheets=document.selected_sheets,
        table_mappings=document.table_mappings,
        custom_columns=[CustomColumnSpec(display_name="Supplier", hint="Supplier")],
    )
    assert [item.attributes["Supplier"] for item in reparsed.items] == ["Alpha", "Beta"]
    assert [(item.page, item.row) for item in reparsed.items] == [(1, 2), (2, 2)]


@pytest.mark.parametrize("selection", [[], ["Missing"], ["First sheet", "First sheet"]])
def test_invalid_multiple_sheet_selection(selection):
    from app.parsing.service import ParsingError

    with pytest.raises(ParsingError):
        parse_upload(
            filename="request.xlsx", content=workbook_bytes([], []), selected_sheets=selection
        )


@pytest.mark.asyncio
async def test_inspection_does_not_extract(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.api import routes
    from app.main import app

    extract = Mock(side_effect=AssertionError("Inspection must not extract"))
    monkeypatch.setattr(routes, "parse_upload", extract)
    content = workbook_bytes([], [["Product", "Quantity"], ["Device", 2]])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/imports/inspect", files={"file": ("request.xlsx", content)}
        )
        assert response.status_code == 200
        assert response.json() == {
            "sheets": [
                {"name": "First sheet", "rows": 0},
                {"name": "Other request", "rows": 2},
            ]
        }
        corrupt = await client.post("/api/imports/inspect", files={"file": ("bad.xlsx", b"bad")})
        assert corrupt.status_code == 422
    extract.assert_not_called()
