"""Header-detection + column-mapping logic shared by the Excel parser and the PDF table path.

Both sources ultimately hand this module the same shape of data: a list of rows, each a list of
raw cell values (str | int | float | None). It figures out which row is the header, maps columns
to roles (name/quantity/unit/notes/priority) using the multilingual keyword dictionary, and turns
the remaining rows into ParsedLineItem records.
"""

from dataclasses import dataclass, field

from app.parsing.keywords import SPECIAL_INFO_KEYWORDS, classify_columns, match_column_role
from app.parsing.text_heuristics import (
    build_item,
    detect_priority,
    detect_priority_from_column_value,
    extract_quantity_and_unit,
    parse_number,
)
from app.parsing.types import ParsedDocument, Priority

# How many leading rows we're willing to scan looking for a header.
_HEADER_SEARCH_WINDOW = 10
# A header row must resolve at least a name column plus one of quantity/unit to be trusted.
_REQUIRED_ROLES = {"name"}


@dataclass
class HeaderLayout:
    """How one detected header row maps onto the core fields and the extra columns."""

    row_index: int
    roles: dict[int, str] = field(default_factory=dict)
    # Request-side columns with no core role, as {col_index: original header label}. These
    # become per-item attributes, which is how a file's own vocabulary survives extraction.
    extras: dict[int, str] = field(default_factory=dict)
    labels: dict[int, str] = field(default_factory=dict)


def cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_header_row(rows: list[list[object]]) -> HeaderLayout | None:
    for row_index, row in enumerate(rows[:_HEADER_SEARCH_WINDOW]):
        cells = [cell_text(cell) for cell in row]
        keep_column = classify_columns(cells)
        layout = HeaderLayout(row_index=row_index)

        for col_index, text in enumerate(cells):
            if not text or not keep_column[col_index]:
                continue
            layout.labels[col_index] = text
            role = match_column_role(text)
            if role and role not in layout.roles.values():
                layout.roles[col_index] = role
            else:
                layout.extras[col_index] = text

        if _REQUIRED_ROLES <= set(layout.roles.values()):
            return layout
    return None


def is_table_well_structured(rows: list[list[object]]) -> bool:
    """Cheap check used by the PDF parser to decide between table heuristics and the LLM fallback."""
    if _find_header_row(rows) is None:
        return False

    non_empty_lengths = [len([c for c in row if cell_text(c)]) for row in rows if any(row)]
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
        cells = [cell_text(cell) for cell in row]
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
    layout: HeaderLayout | None = None,
) -> ParsedDocument:
    """layout, when given, skips heuristic header detection entirely - lets a caller hand in an
    already-computed layout instead of the keyword-derived one this module computes on its own."""
    document = ParsedDocument()
    if layout is None:
        layout = _find_header_row(rows)
        # The heuristic scoped these columns as part of the partner's request but couldn't name
        # a quantity role among them at all - e.g. quantity split across "packs requested" +
        # "units per pack" columns, which no keyword list can name in advance. Only engages on a
        # genuine gap, so it can enrich a layout but never override an already-successful match.
        if layout is not None and layout.extras and not _has_quantity_role(layout):
            layout = _try_fill_quantity_gap(rows, layout)
            if _has_quantity_role(layout):
                document.used_llm_fallback = True

    if layout is None:
        document.warnings.append("No recognizable header row found; treated as headerless table")
        layout = HeaderLayout(row_index=-1, roles={0: "name", 1: "quantity", 2: "unit", 3: "notes"})
        data_rows = rows
        in_scope_columns = None
    else:
        data_rows = rows[layout.row_index + 1 :]
        in_scope_columns = set(layout.labels)
        skipped = _skipped_column_labels(rows[layout.row_index], in_scope_columns)
        if skipped:
            document.warnings.append(f"Ignored supplier/admin columns: {', '.join(skipped)}")

    start_index = layout.row_index + 1

    for offset, row in enumerate(data_rows):
        row_number = start_index + offset + 1
        values = {
            role: cell_text(row[col]) for col, role in layout.roles.items() if col < len(row)
        }
        name = values.get("name", "")
        if not name:
            continue

        raw_quantity = values.get("quantity", "")
        quantity = parse_number(raw_quantity) if raw_quantity else None
        unit = values.get("unit", "")

        attributes = {
            label: cell_text(row[col])
            for col, label in layout.extras.items()
            if col < len(row) and cell_text(row[col])
        }

        # Some forms don't give a single total, only "quantity in packs" + "units per pack"
        # (e.g. requesting 15 boxes of 100 - the total requested is what downstream matching
        # needs, not the box count). Compute it, but keep the breakdown visible as attributes
        # rather than silently collapsing it - a reviewer should be able to check the math.
        if quantity is None:
            packs_raw = values.get("quantity_packs", "")
            per_pack_raw = values.get("units_per_pack", "")
            packs = parse_number(packs_raw) if packs_raw else None
            per_pack = parse_number(per_pack_raw) if per_pack_raw else None
            if packs is not None and per_pack is not None:
                quantity = packs * per_pack
                attributes["Packs requested"] = packs_raw
                attributes["Units per pack"] = per_pack_raw

        if quantity is None and not unit:
            # Some files put "2000 pcs" straight into the name/description column.
            inferred_quantity, inferred_unit = extract_quantity_and_unit(name)
            quantity = quantity or inferred_quantity
            unit = unit or (inferred_unit or "")

        notes = values.get("notes", "")
        translation = values.get("translation", "")
        if translation:
            notes = f"Translation: {translation}" + (f" · {notes}" if notes else "")

        # Partner procurement forms use their own priority-tier wording ("Prioritaire-Priority",
        # "Standard", "Optionnel-Optional") - mapped onto our scale; anything genuinely
        # unrecognized still survives as an attribute rather than being silently dropped.
        raw_priority = values.get("priority", "")
        mapped_priority = detect_priority_from_column_value(raw_priority) if raw_priority else None
        if raw_priority and mapped_priority is None:
            attributes[_priority_label(layout)] = raw_priority

        excerpt = " | ".join(
            text
            for col, text in ((col, cell_text(cell)) for col, cell in enumerate(row))
            if text and (in_scope_columns is None or col in in_scope_columns)
        )
        document.items.append(
            build_item(
                name=name,
                quantity=quantity,
                unit=unit,
                notes=notes,
                item_number=values.get("item_number", ""),
                shelf_life=values.get("shelf_life", ""),
                attributes=attributes,
                priority=mapped_priority,
                default_priority=default_priority,
                page=page,
                row=row_number,
                excerpt=excerpt,
            )
        )

    document.rows_detected = len(document.items)
    document.attribute_columns = _surviving_attribute_columns(document)
    return document


def _priority_label(layout: HeaderLayout) -> str:
    for col, role in layout.roles.items():
        if role == "priority":
            return layout.labels.get(col, "Priority")
    return "Priority"


def _skipped_column_labels(header_row: list[object], kept: set[int]) -> list[str]:
    return [
        cell_text(cell)
        for col, cell in enumerate(header_row)
        if col not in kept and cell_text(cell)
    ]


def _surviving_attribute_columns(document: ParsedDocument) -> list[str]:
    """Extra columns in first-seen order, dropping any that were empty on every row - that's
    what makes the review table adapt to the file instead of showing a wall of blank columns."""
    ordered: list[str] = []
    for item in document.items:
        for label in item.attributes:
            if label not in ordered:
                ordered.append(label)
    return ordered


def _has_quantity_role(layout: HeaderLayout) -> bool:
    values = layout.roles.values()
    return "quantity" in values or ("quantity_packs" in values and "units_per_pack" in values)


def _try_fill_quantity_gap(rows: list[list[object]], layout: HeaderLayout) -> HeaderLayout:
    # Imported lazily: llm_table_classifier imports HeaderLayout/cell_text from this module, so
    # a module-level import here would be circular.
    from app.parsing.llm_table_classifier import LlmUnavailable, fill_quantity_gap_with_llm

    try:
        return fill_quantity_gap_with_llm(rows, layout)
    except LlmUnavailable:
        return layout
