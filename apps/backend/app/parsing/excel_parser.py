"""Excel (.xlsx / .xls) parsing: sheet -> raw rows -> ParsedDocument via the shared table parser.

One worksheet is imported per request: the first by default, or the one the user picked on the
review screen. Extra sheets in real requests are typically scratch copies of request lines or
helper formulas, so combining them would duplicate items; every sheet is listed (name + row count)
so the user can switch instead.
"""

import io

from app.parsing.partner_extraction import capture_rows
from app.parsing.table_mapping import MappingSession
from app.parsing.table_parser import extract_request_priority_hint, parse_table_rows
from app.parsing.types import CustomColumnSpec, ParsedDocument


class UnknownWorksheet(ValueError):
    """The requested worksheet name doesn't exist in this workbook."""


def parse_excel(
    content: bytes,
    filename: str,
    custom_columns: list[CustomColumnSpec] | None = None,
    mapping_session: MappingSession | None = None,
    sheet: str | None = None,
) -> ParsedDocument:
    reader = _read_xls if filename.lower().endswith(".xls") else _read_xlsx
    rows, sheets, selected = reader(content, sheet)
    which = f'worksheet "{selected}"' if sheet is not None else "first worksheet"

    if not any(_non_empty(row) for row in rows):
        document = ParsedDocument()
        document.warnings.append(f"The {which} contained no data")
    else:
        default_priority = extract_request_priority_hint(rows)
        document = parse_table_rows(
            rows,
            default_priority=default_priority,
            custom_columns=custom_columns,
            mapping_session=mapping_session,
        )
    if not document.items and len(sheets) > 1:
        document.warnings.append(
            f"No requested line items were extracted from the {which}. This workbook has other "
            "worksheets - choose one in the Worksheet selector to extract it instead."
        )
    document.sheets = sheets
    document.selected_sheet = selected
    capture_rows(document, rows)
    return document


def _non_empty(row) -> bool:
    return any(value is not None and str(value).strip() for value in row)


def _read_xlsx(content: bytes, sheet: str | None) -> tuple[list[list[object]], list[dict], str]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        if sheet is not None and sheet not in workbook.sheetnames:
            raise UnknownWorksheet(f'Worksheet "{sheet}" not found')
        worksheet = workbook[sheet] if sheet is not None else workbook.worksheets[0]
        sheets = [
            {"name": ws.title, "rows": sum(map(_non_empty, ws.iter_rows(values_only=True)))}
            for ws in workbook.worksheets
        ]
        return [list(row) for row in worksheet.iter_rows(values_only=True)], sheets, worksheet.title
    finally:
        workbook.close()


def _read_xls(content: bytes, sheet: str | None) -> tuple[list[list[object]], list[dict], str]:
    import xlrd

    workbook = xlrd.open_workbook(file_contents=content)
    names = workbook.sheet_names()
    if sheet is not None and sheet not in names:
        raise UnknownWorksheet(f'Worksheet "{sheet}" not found')
    worksheet = workbook.sheet_by_name(sheet) if sheet is not None else workbook.sheet_by_index(0)
    sheets = [
        {
            "name": name,
            "rows": sum(
                _non_empty(workbook.sheet_by_name(name).row_values(i))
                for i in range(workbook.sheet_by_name(name).nrows)
            ),
        }
        for name in names
    ]
    rows = [worksheet.row_values(row_index) for row_index in range(worksheet.nrows)]
    return rows, sheets, worksheet.name
