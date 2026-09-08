import io

from app.parsing.excel_parser import parse_excel
from app.parsing.keywords import match_column_role
from app.parsing.pdf_parser import parse_pdf
from app.parsing.table_parser import is_table_well_structured, parse_table_rows
from app.parsing.text_heuristics import classify_item, extract_quantity_and_unit, parse_number


def build_xlsx(rows: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_minimal_pdf(lines: list[str]) -> bytes:
    """Hand-rolled single-page PDF with a Helvetica text stream - no PDF-writing dependency
    is installed, and this is enough to exercise pdfplumber's real text extraction."""

    def escape(text: str) -> str:
        return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    text_ops = "BT /F1 12 Tf 14 TL 50 750 Td\n"
    for line in lines:
        text_ops += f"({escape(line)}) Tj T*\n"
    text_ops += "ET"
    stream = text_ops.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return bytes(out)


def test_match_column_role_recognizes_multiple_languages() -> None:
    assert match_column_role("Item Description") == "name"
    assert match_column_role("Bezeichnung") == "name"
    assert match_column_role("Désignation") == "name"
    assert match_column_role("الصنف") == "name"
    assert match_column_role("Qty") == "quantity"
    assert match_column_role("Menge") == "quantity"
    assert match_column_role("Unit") == "unit"
    assert match_column_role("Some Random Header") is None


def test_parse_number_handles_various_shapes() -> None:
    assert parse_number(2000) == 2000
    assert parse_number(2000.0) == 2000
    assert parse_number("2,000") == 2000
    assert parse_number("2000 pcs") == 2000
    assert parse_number(None) is None
    assert parse_number("") is None


def test_extract_quantity_and_unit_from_free_text() -> None:
    quantity, unit = extract_quantity_and_unit("Amoxicillin 500mg caps [2000 pcs]")
    assert quantity == 2000
    assert unit == "pcs"


def test_classify_item_statuses() -> None:
    assert classify_item("", None, "")[0] == "missing"
    assert classify_item("Item", None, "")[0] == "missing"
    assert classify_item("Item", 10, "")[0] == "needs_review"
    assert classify_item("Item", 10, "caps")[0] == "verified"


def test_parse_table_rows_detects_header_and_maps_columns() -> None:
    rows = [
        ["Item", "Quantity", "Unit", "Notes"],
        ["Amoxicillin 500mg Capsules", 2000, "caps", "Blister pack preferred"],
        ["ORS Sachets", None, "sachets", "Illegible"],
    ]

    result = parse_table_rows(rows)

    assert result.rows_detected == 2
    assert result.items[0].name == "Amoxicillin 500mg Capsules"
    assert result.items[0].quantity == 2000
    assert result.items[0].status == "verified"
    assert result.items[1].quantity is None
    assert result.items[1].status == "missing"


def test_parse_table_rows_does_not_confuse_item_number_with_name() -> None:
    # Real RFQ-tracker workbooks have an "Item number" (SKU) column before the actual
    # description column ("Product") - "Item number" must not steal the name role via a bare
    # "item" keyword match, and its value should land in the dedicated item_number field.
    rows = [
        ["Item number", "Product", "Quantity enquiry", "Packaging enquiry"],
        [424109001, "Cholera Tests, stool, rapid", 300, None],
        [None, "Dengue Test", 200, None],
    ]

    result = parse_table_rows(rows)

    assert result.rows_detected == 2
    assert result.items[0].name == "Cholera Tests, stool, rapid"
    assert result.items[0].item_number == "424109001"
    assert result.items[1].name == "Dengue Test"
    assert result.items[1].item_number == ""


def test_parse_table_rows_captures_translation_and_shelf_life() -> None:
    rows = [
        ["Product", "Translation", "desired shelf life", "Quantity enquiry"],
        ["water-based lubricant, sterile", "Wasserbasierendes Gleitmittel, steril", "16 months", 272],
    ]

    result = parse_table_rows(rows)

    assert result.rows_detected == 1
    item = result.items[0]
    assert item.shelf_life == "16 months"
    assert "Wasserbasierendes Gleitmittel" in item.notes


def test_extract_request_priority_hint_reads_special_info_field() -> None:
    from app.parsing.table_parser import extract_request_priority_hint

    rows = [
        [None, "Besondere Informationen:", "DRINGEND - komplette Lieferung notwendig"],
        ["Product", "Quantity enquiry"],
    ]

    assert extract_request_priority_hint(rows) == "critical"


def test_extract_request_priority_hint_returns_none_when_empty() -> None:
    from app.parsing.table_parser import extract_request_priority_hint

    rows = [
        [None, "Besondere Informationen:", None],
        ["Product", "Quantity enquiry"],
    ]

    assert extract_request_priority_hint(rows) is None


def test_parse_table_rows_ignores_supplier_quote_block() -> None:
    # Everything from "Supplier I" onward is action medeor's own quote tracking, not part of
    # what the partner requested - must not bleed into quantity/unit/notes or the excerpt.
    rows = [
        ["Product", "Quantity enquiry", "Packaging enquiry", "Supplier I", "Item offered", "Quantity on offer", "Packaging"],
        ["Cholera Tests, stool, rapid", 300, None, "Centramed", "Rapid Test Kit, 20/box", 15, 20],
    ]

    result = parse_table_rows(rows)

    assert result.rows_detected == 1
    item = result.items[0]
    assert item.quantity == 300
    assert item.unit == ""
    assert "Centramed" not in item.excerpt
    assert "Rapid Test Kit" not in item.excerpt
    assert any("supplier" in warning.lower() for warning in result.warnings)


def test_parse_table_rows_skips_blank_names() -> None:
    rows = [
        ["Item", "Quantity", "Unit"],
        ["", 100, "caps"],
        ["Paracetamol 500mg Tablets", 5000, "tabs"],
    ]

    result = parse_table_rows(rows)

    assert len(result.items) == 1
    assert result.items[0].name == "Paracetamol 500mg Tablets"


def test_is_table_well_structured_true_for_consistent_table() -> None:
    rows = [
        ["Item", "Quantity", "Unit"],
        ["Amoxicillin 500mg Capsules", 2000, "caps"],
        ["Paracetamol 500mg Tablets", 5000, "tabs"],
        ["ORS Sachets", 500, "sachets"],
    ]
    assert is_table_well_structured(rows) is True


def test_is_table_well_structured_false_without_header() -> None:
    rows = [
        ["Please find our request below."],
        ["We urgently need medical supplies for the region."],
    ]
    assert is_table_well_structured(rows) is False


def test_parse_excel_end_to_end() -> None:
    content = build_xlsx(
        [
            ["Item", "Quantity", "Unit", "Notes"],
            ["Wound Dressing 10x10cm", 1000, "pcs", "Sterile"],
            ["Morphine HCl 10mg/ml Injection", 50, "vials", "Controlled substance"],
        ]
    )

    document = parse_excel(content, "request.xlsx")

    assert document.rows_detected == 2
    assert {item.name for item in document.items} == {
        "Wound Dressing 10x10cm",
        "Morphine HCl 10mg/ml Injection",
    }


def test_parse_excel_falls_back_to_free_text_quantity_unit() -> None:
    # Some files put the whole "name + qty + unit" into a single description column.
    content = build_xlsx(
        [
            ["Description"],
            ["Amoxicillin 500mg caps 2000 pcs"],
        ]
    )

    document = parse_excel(content, "request.xlsx")

    assert document.rows_detected == 1
    assert document.items[0].quantity == 2000
    assert document.items[0].unit == "pcs"


def test_parse_pdf_free_text_falls_back_to_naive_parsing_without_llm_key(monkeypatch) -> None:
    # No ANTHROPIC_API_KEY configured in the test environment, so the free-text page (no
    # detectable table) should degrade to the naive per-line regex parser, not raise.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    content = build_minimal_pdf(
        [
            "Amoxicillin 500mg caps 2000 pcs - blister pack preferred",
            "Paracetamol 500mg tablets 5000 tabs - generic acceptable",
        ]
    )

    document = parse_pdf(content)

    assert document.used_llm_fallback is False
    assert any("LLM fallback unavailable" in warning for warning in document.warnings)
    assert document.rows_detected == 2
    assert document.items[0].quantity == 2000
    assert document.items[0].unit == "pcs"
    assert document.items[0].confidence == 40
