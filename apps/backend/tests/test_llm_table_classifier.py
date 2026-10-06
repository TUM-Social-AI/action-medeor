"""Behavior and cost regressions for semantic table mapping; no network calls."""

import io
from unittest.mock import Mock

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from app.parsing import llm_table_classifier
from app.parsing.llm_client import LlmUnavailable
from app.parsing.llm_table_classifier import ColumnMapping, TableMapping
from app.parsing.pdf_parser import parse_pdf
from app.parsing.service import parse_upload
from app.parsing.table_mapping import MappingSession, validated_layout
from app.parsing.table_parser import parse_table_rows
from app.parsing.types import CustomColumnSpec
from tests.test_parsing import build_xlsx

HEADERS = [
    "Line Item",
    "ITEM DESCRIPTION and REQUESTED TECHNICAL\nSPECIFICATIONS",
    "QUANTITY OF\nPACKS",
    "UNITS PER\nPACK",
    "TOTAL UNITS",
    "QUANTITY OF\nPACKS",
    "UNITS PER\nPACK",
    "TOTAL UNITS",
    "UNIT OF\nMEASURE\nOFFERED",
    "UNIT PRICE\n(EUR)",
    "PACK PRICE\n(EUR)",
    "TOTAL PRICE\n(EUR)",
    "DATE\nMANUFACTURE",
    "EXPIRY DATE",
    "ORIGIN",
    "DELIVERY\nDATE",
]
NAMES = [f"Clinical device model {i}, full specification" for i in range(1, 13)]
QUANTITIES = [2, 2, 4, 2, 1, 4, 2, 3, 4, 1, 1, 2]


def mapping(roles, width, header=0, suppliers=()):
    return TableMapping(
        header_row_index=header,
        columns=[
            ColumnMapping(
                column_index=i,
                role=roles.get(i, "none"),
                scope="supplier" if i in suppliers else "request",
            )
            for i in range(width)
        ],
    )


def rfq_rows():
    return (
        [HEADERS]
        + [
            [str(i), name, qty, 1, qty] + [""] * 11
            for i, (name, qty) in enumerate(zip(NAMES, QUANTITIES), 1)
        ]
        + [["TOTAL"] + [""] * 15]
    )


def rfq_mapping():
    return mapping(
        {0: "ordinal", 1: "name", 2: "quantity_packs", 3: "units_per_pack", 4: "quantity"},
        16,
        suppliers=range(5, 16),
    )


def stub(monkeypatch, result):
    call = Mock(return_value=result)
    monkeypatch.setattr(llm_table_classifier, "call_llm", call)
    return call


def build_rfq_pdf(pages=1):
    # Synthetic, wide PDF with the original layout but no partner/product data.
    from reportlab.platypus import PageBreak

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape((1200, 1600)),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=20,
    )
    style = getSampleStyleSheet()["Normal"]
    style.fontSize = 7
    story = []
    for page in range(pages):
        if page:
            story.append(PageBreak())
        story.append(Paragraph("Request for clinical devices: supplier quotation section", style))
        table = Table(
            [[Paragraph(str(c).replace("\n", "<br/>"), style) for c in row] for row in rfq_rows()],
            colWidths=[45, 370] + [80] * 14,
        )
        table.setStyle(
            TableStyle(
                [("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]
            )
        )
        story.append(table)
    doc.build(story)
    return buffer.getvalue()


def test_pdf_rfq_extracts_twelve_names_and_requested_totals(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    document = parse_pdf(build_rfq_pdf())
    assert [item.name for item in document.items] == NAMES
    assert [item.quantity for item in document.items] == QUANTITIES
    assert all(item.unit == "" and item.status != "verified" for item in document.items)
    assert all(item.notes == "" for item in document.items)
    assert document.used_llm_fallback is True
    assert call.call_count == 1
    assert all(item.attributes["Units per pack"] == "1" for item in document.items)


def test_repeated_pdf_pages_reuse_mapping(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    document = parse_pdf(build_rfq_pdf(pages=2))
    assert len(document.items) == 24
    assert {item.page for item in document.items} == {1, 2}
    assert call.call_count == 1


def test_clear_reordered_multiline_table_needs_no_call(monkeypatch):
    call = stub(monkeypatch, None)
    document = parse_table_rows(
        [
            ["Unit", "TOTAL\nUNITS", "ITEM DESCRIPTION and TECHNICAL SPECIFICATIONS", "Line Item"],
            ["pcs", 12, "Clinical device", 1],
            ["", 5, "Other device", 2],
        ]
    )
    assert call.call_count == 0
    assert document.items[0].name == "Clinical device"
    assert document.items[0].quantity == 12
    assert document.items[1].unit == ""
    assert document.table_mappings["version"] == 1


def test_supplier_values_never_become_request_quantity(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    rows = rfq_rows()
    rows[1][5:10] = [900, 500, 450000, "boxes", 123]
    result = parse_table_rows(rows)
    assert result.items[0].quantity == 2
    assert "450000" not in result.items[0].excerpt
    assert result.items[0].unit == ""
    assert call.call_count == 1


def test_unknown_headers_and_quantity_gap_are_resolved(monkeypatch):
    call = stub(monkeypatch, mapping({0: "name", 1: "quantity_packs", 2: "units_per_pack"}, 3))
    result = parse_table_rows(
        [["Product", "Boxes Wanted", "Contents Per Box"], ["Device", 15, 100]]
    )
    assert result.items[0].quantity == 1500
    assert call.call_count == 1


def test_headerless_table_uses_mapping_without_dropping_first_item(monkeypatch):
    call = stub(monkeypatch, mapping({0: "quantity", 1: "name", 2: "unit"}, 3, header=-1))
    result = parse_table_rows([[20, "Sterile gauze", "pcs"], [30, "Sterile catheter", "pcs"]])
    assert [item.quantity for item in result.items] == [20, 30]
    assert result.items[0].row == 1
    assert call.call_count == 1


def test_group_headers_are_supplied_and_last_header_is_used(monkeypatch):
    result_mapping = mapping({0: "name", 1: "quantity"}, 3, header=1, suppliers=[2])
    call = stub(monkeypatch, result_mapping)
    result = parse_table_rows(
        [
            ["Requested products", None, "Supplier offer"],
            ["Product", "Quantity", "Quantity"],
            ["Catheter", 12, 900],
        ]
    )
    assert result.items[0].quantity == 12
    assert result.items[0].row == 3
    assert "Supplier offer" in call.call_args.args[0]


@pytest.mark.parametrize("failure", [LlmUnavailable("SECRET provider response"), ValueError("bad")])
def test_failed_mapping_has_visible_safe_warning_and_low_confidence(monkeypatch, failure):
    call = stub(monkeypatch, None)
    call.side_effect = failure
    session = MappingSession()
    first = parse_table_rows(rfq_rows(), page=1, mapping_session=session)
    second = parse_table_rows(rfq_rows(), page=2, mapping_session=session)
    assert first.items[0].name == NAMES[0]  # improved basic parser still works
    assert all(item.status != "verified" for item in first.items)
    assert first.warnings and "SECRET" not in " ".join(first.warnings)
    assert second.warnings
    assert call.call_count == 1


@pytest.mark.parametrize(
    "change",
    ["duplicate_role", "duplicate_index", "out_of_range", "supplier", "numeric_unit", "header"],
)
def test_invalid_model_assignments_are_rejected(change):
    rows = [
        ["Product", "Quantity", "Unit", "Supplier I", "Quantity on offer"],
        ["Catheter", 12, "pcs", "Vendor", 900],
    ]
    candidate = mapping({0: "name", 1: "quantity", 2: "unit"}, 5, suppliers=[3, 4])
    if change == "duplicate_role":
        candidate.columns[2].role = "quantity"
    elif change == "duplicate_index":
        candidate.columns[2].column_index = 1
    elif change == "out_of_range":
        candidate.columns[2].column_index = 100
    elif change == "supplier":
        candidate.columns[1].role = "none"
        candidate.columns[4].scope = "request"
        candidate.columns[4].role = "quantity"
    elif change == "numeric_unit":
        candidate.columns[1].role = "unit"
        candidate.columns[2].role = "none"
    else:
        candidate.header_row_index = 1
    with pytest.raises(ValueError):
        validated_layout(rows, candidate)


def test_explicit_total_wins_and_conflicting_pack_math_needs_review(monkeypatch):
    call = stub(monkeypatch, None)
    result = parse_table_rows(
        [
            ["Product", "Total units", "Packs requested", "Units per pack", "Unit"],
            ["Catheter", 120, 2, 100, "pcs"],
        ]
    )
    assert result.items[0].quantity == 120
    assert result.items[0].attributes["Packs requested"] == "2"
    assert result.items[0].status == "needs_review"
    assert "conflicts" in " ".join(result.warnings)
    assert call.call_count == 0


def test_no_quantity_is_inferred_from_dosage_or_model_number(monkeypatch):
    stub(monkeypatch, None)
    result = parse_table_rows([["Description"], ["Amoxicillin 500mg"], ["Scale model 354"]])
    assert all(item.quantity is None for item in result.items)


def test_persisted_mapping_is_reused_for_custom_columns(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    content = build_xlsx(rfq_rows())
    first = parse_upload(filename="sample.xlsx", content=content)
    second = parse_upload(
        filename="sample.xlsx",
        content=content,
        table_mappings=first.table_mappings,
        custom_columns=[CustomColumnSpec("Pack size", "UNITS PER PACK")],
    )
    assert call.call_count == 1
    assert second.items[0].attributes["Pack size"] == "1"
    assert [item.row for item in second.items] == [item.row for item in first.items]


def test_reused_layout_checks_new_page_data_without_another_call(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    session = MappingSession()
    parse_table_rows(rfq_rows(), page=1, mapping_session=session)
    rows = rfq_rows()
    rows[1][4] = "unreadable"
    result = parse_table_rows(rows, page=2, mapping_session=session)
    assert call.call_count == 1
    assert result.items[0].quantity is None
    assert result.items[0].status != "verified"
    assert result.warnings


def test_same_headers_with_different_scope_headings_are_distinct_layouts(monkeypatch):
    call = stub(monkeypatch, rfq_mapping())
    session = MappingSession()
    parse_table_rows(
        rfq_rows(),
        page=1,
        mapping_session=session,
        context="Requested amounts then supplier quotation",
    )
    parse_table_rows(
        rfq_rows(),
        page=2,
        mapping_session=session,
        context="Supplier quotation then requested amounts",
    )
    assert call.call_count == 2


def test_unlabelled_pages_do_not_share_a_mapping_by_column_count(monkeypatch):
    call = stub(monkeypatch, mapping({0: "quantity", 1: "name", 2: "unit"}, 3, header=-1))
    session = MappingSession()
    parse_table_rows([[20, "Catheter", "pcs"]], page=1, mapping_session=session)
    parse_table_rows([[30, "Gauze", "pcs"]], page=2, mapping_session=session)
    assert call.call_count == 2


def test_unknown_scope_on_populated_columns_is_not_treated_as_verified():
    candidate = rfq_mapping()
    candidate.columns[4].scope = "unknown"
    candidate.columns[4].role = "none"
    with pytest.raises(ValueError, match="unresolved"):
        validated_layout(rfq_rows(), candidate)


def test_bad_data_outside_mapping_sample_is_flagged(monkeypatch):
    call = stub(monkeypatch, None)
    rows = [["Product", "Quantity", "Unit"]] + [[f"Device {i}", 10, "pcs"] for i in range(20)]
    rows[17][1] = "unreadable"
    call.side_effect = LlmUnavailable("offline")
    result = parse_table_rows(rows)
    assert result.items[16].quantity is None
    assert result.items[16].status != "verified"
    assert any("row 18" in warning for warning in result.warnings)


@pytest.mark.parametrize("value", ["2,000 pcs", "2000pcs"])
def test_explicit_quantity_and_unit_in_amount_cell_need_no_llm(monkeypatch, value):
    call = stub(monkeypatch, None)
    result = parse_table_rows([["Product", "Quantity"], ["Gauze", value]])
    assert result.items[0].quantity == 2000
    assert result.items[0].unit == "pcs"
    assert call.call_count == 0


def test_zero_requested_amount_is_not_verified(monkeypatch):
    call = stub(monkeypatch, None)
    result = parse_table_rows([["Product", "Quantity", "Unit"], ["Gauze", 0, "pcs"]])
    assert result.items[0].status == "needs_review"
    assert result.warnings
    assert call.call_count == 0
