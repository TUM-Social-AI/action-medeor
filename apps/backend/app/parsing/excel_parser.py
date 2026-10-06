"""Excel (.xlsx / .xls) parsing: sheet -> raw rows -> ParsedDocument via the shared table parser."""

import io

from app.parsing.partner_extraction import capture_rows
from app.parsing.table_mapping import MappingSession
from app.parsing.table_parser import extract_request_priority_hint, parse_table_rows
from app.parsing.types import CustomColumnSpec, ParsedDocument


def parse_excel(
    content: bytes,
    filename: str,
    custom_columns: list[CustomColumnSpec] | None = None,
    mapping_session: MappingSession | None = None,
) -> ParsedDocument:
    if filename.lower().endswith(".xls"):
        rows, sheet_count = _read_xls(content)
    else:
        rows, sheet_count = _read_xlsx(content)

    if not any(any(value is not None and str(value).strip() for value in row) for row in rows):
        document = ParsedDocument()
        document.warnings.append("The first worksheet contained no data")
    else:
        default_priority = extract_request_priority_hint(rows)
        document = parse_table_rows(
            rows,
            default_priority=default_priority,
            custom_columns=custom_columns,
            mapping_session=mapping_session,
        )
    if not document.items and sheet_count > 1:
        document.warnings.append(
            "No requested line items were extracted from the first worksheet. "
            "This workbook has additional sheets, but only the first is imported. "
            "Multiple-sheet selection is a future feature; for now, delete the unnecessary "
            "sheets so the request sheet is first, then upload again."
        )
    capture_rows(document, rows)
    return document


def _read_xlsx(content: bytes) -> tuple[list[list[object]], int]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        return [list(row) for row in sheet.iter_rows(values_only=True)], len(workbook.worksheets)
    finally:
        workbook.close()


def _read_xls(content: bytes) -> tuple[list[list[object]], int]:
    import xlrd

    workbook = xlrd.open_workbook(file_contents=content)
    sheet = workbook.sheet_by_index(0)
    return [sheet.row_values(row_index) for row_index in range(sheet.nrows)], workbook.nsheets
