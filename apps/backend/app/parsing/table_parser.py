"""Header-detection + column-mapping logic shared by the Excel parser and the PDF table path.

Both sources ultimately hand this module the same shape of data: a list of rows, each a list of
raw cell values (str | int | float | None). It figures out which row is the header, maps columns
to roles (name/quantity/unit/notes/priority) using the multilingual keyword dictionary, and turns
the remaining rows into ParsedLineItem records.
"""

from app.parsing.keywords import SPECIAL_INFO_KEYWORDS, is_supplier_block_start, match_column_role
from app.parsing.text_heuristics import (
    build_item,
    detect_priority,
    extract_quantity_and_unit,
    parse_number,
)
from app.parsing.types import ParsedDocument, Priority

# How many leading rows we're willing to scan looking for a header.
_HEADER_SEARCH_WINDOW = 10
# A header row must resolve at least a name column plus one of quantity/unit to be trusted.
_REQUIRED_ROLES = {"name"}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_header_row(
    rows: list[list[object]],
) -> tuple[int, dict[int, str], int | None] | None:
    """Returns (header_row_index, {col_index: role}, boundary) where boundary is the first
    column index that starts a supplier/quote block (RFQ trackers), or None if there isn't one -
    everything from boundary onward is out of scope for both role-mapping and excerpts."""
    for row_index, row in enumerate(rows[:_HEADER_SEARCH_WINDOW]):
        column_roles: dict[int, str] = {}
        boundary: int | None = None
        for col_index, cell in enumerate(row):
            text = _cell_text(cell)
            if is_supplier_block_start(text):
                boundary = col_index
                break
            role = match_column_role(text)
            if role and role not in column_roles.values():
                column_roles[col_index] = role
        found_roles = set(column_roles.values())
        if _REQUIRED_ROLES <= found_roles:
            return row_index, column_roles, boundary
    return None


def is_table_well_structured(rows: list[list[object]]) -> bool:
    """Cheap check used by the PDF parser to decide between table heuristics and the LLM fallback."""
    if _find_header_row(rows) is None:
        return False

    non_empty_lengths = [len([c for c in row if _cell_text(c)]) for row in rows if any(row)]
    if len(non_empty_lengths) < 2:
        return False

    # Require most rows to have a similar column count to the header - a real table, not
    # paragraphs that pdfplumber happened to slice into a grid.
    from statistics import median

    typical = median(non_empty_lengths)
    consistent = sum(1 for length in non_empty_lengths if abs(length - typical) <= 1)
    return consistent / len(non_empty_lengths) >= 0.7


def extract_request_priority_hint(rows: list[list[object]]) -> Priority | None:
    """Scan the leading rows for a "Besondere Informationen:" / "Special information:" label and
    derive a priority from whatever free text follows it on that row. Most files leave it empty
    today (no current sample has priority-signalling text there), so this usually returns None
    and the medium default in build_item() applies - it's a hook for when a file does carry one."""
    for row in rows[:_HEADER_SEARCH_WINDOW]:
        cells = [_cell_text(cell) for cell in row]
        for index, cell in enumerate(cells):
            lowered = cell.lower()
            if any(keyword in lowered for keyword in SPECIAL_INFO_KEYWORDS):
                remainder = " ".join(text for text in cells[index + 1 :] if text)
                if remainder:
                    return detect_priority(remainder)
    return None


def parse_table_rows(
    rows: list[list[object]],
    *,
    page: int = 0,
    default_priority: Priority | None = None,
) -> ParsedDocument:
    document = ParsedDocument()
    header = _find_header_row(rows)

    if header is None:
        document.warnings.append("No recognizable header row found; treated as headerless table")
        column_roles = {0: "name", 1: "quantity", 2: "unit", 3: "notes"}
        data_rows = rows
        start_index = 0
        boundary = None
    else:
        header_index, column_roles, boundary = header
        data_rows = rows[header_index + 1 :]
        start_index = header_index + 1
        if boundary is not None:
            document.warnings.append(
                f"Ignored columns from index {boundary} onward (supplier/quote block)"
            )

    for offset, row in enumerate(data_rows):
        in_scope_row = row[:boundary] if boundary is not None else row
        row_number = start_index + offset + 1
        values = {
            role: _cell_text(in_scope_row[col])
            for col, role in column_roles.items()
            if col < len(in_scope_row)
        }
        name = values.get("name", "")
        if not name:
            continue

        raw_quantity = values.get("quantity", "")
        quantity = parse_number(raw_quantity) if raw_quantity else None
        unit = values.get("unit", "")
        if quantity is None and not unit:
            # Some files put "2000 pcs" straight into the name/description column.
            inferred_quantity, inferred_unit = extract_quantity_and_unit(name)
            quantity = quantity or inferred_quantity
            unit = unit or (inferred_unit or "")

        notes = values.get("notes", "")
        translation = values.get("translation", "")
        if translation:
            notes = f"Translation: {translation}" + (f" · {notes}" if notes else "")

        excerpt = " | ".join(cell for cell in (_cell_text(v) for v in in_scope_row) if cell)
        document.items.append(
            build_item(
                name=name,
                quantity=quantity,
                unit=unit,
                notes=notes,
                item_number=values.get("item_number", ""),
                shelf_life=values.get("shelf_life", ""),
                priority=detect_priority(values["priority"]) if values.get("priority") else None,
                default_priority=default_priority,
                page=page,
                row=row_number,
                excerpt=excerpt,
            )
        )

    document.rows_detected = len(document.items)
    return document
