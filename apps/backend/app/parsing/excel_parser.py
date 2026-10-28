"""Excel worksheet inspection and extraction of the user-selected worksheets."""

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
    selected_sheets: list[str] | None = None,
    _page: int = 0,
) -> ParsedDocument:
    if selected_sheets is not None:
        if not selected_sheets or len(set(selected_sheets)) != len(selected_sheets):
            raise ValueError("Select at least one worksheet, without duplicates")
        available = inspect_excel(content, filename)
        names = [entry["name"] for entry in available]
        if any(name not in names for name in selected_sheets):
            raise UnknownWorksheet("Unknown worksheet")
        # Workbook order keeps source coordinates stable across every later re-parse.
        selected_sheets = [name for name in names if name in selected_sheets]
        combined = ParsedDocument(
            sheets=available, selected_sheet=selected_sheets[0], selected_sheets=selected_sheets
        )
        for name in selected_sheets:
            part = parse_excel(
                content,
                filename,
                custom_columns,
                mapping_session,
                sheet=name,
                _page=names.index(name) + 1 if len(selected_sheets) > 1 else 0,
            )
            for item in part.items:
                item.review_source["worksheet"] = name
            combined.items.extend(part.items)
            combined.rows_detected += part.rows_detected
            combined.warnings.extend(f"{name}: {warning}" for warning in part.warnings)
            combined.used_llm_fallback |= part.used_llm_fallback
            combined.table_mappings.update(part.table_mappings)
            for field in ("attribute_columns", "available_columns"):
                target = getattr(combined, field)
                target.extend(value for value in getattr(part, field) if value not in target)
            combined.partner_context += "\n" + part.partner_context
        return combined
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
            page=_page,
            default_priority=default_priority,
            custom_columns=custom_columns,
            mapping_session=mapping_session,
        )
    if not document.items and len(sheets) > 1:
        document.warnings.append(
            f"No requested line items were extracted from the {which}. This workbook has other "
            "worksheets - select them when uploading to extract their items."
        )
    document.sheets = sheets
    document.selected_sheet = selected
    document.selected_sheets = [selected]
    for item in document.items:
        item.review_source["worksheet"] = selected
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


def inspect_excel(content: bytes, filename: str) -> list[dict]:
    """Read worksheet names and row counts without running extraction or AI."""
    reader = _read_xls if filename.lower().endswith(".xls") else _read_xlsx
    return reader(content, None)[1]
