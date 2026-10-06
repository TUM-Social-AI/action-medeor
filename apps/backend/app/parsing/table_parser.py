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
)
from app.parsing.types import CustomColumnSpec, ParsedDocument, Priority

# Include cover notes and requester metadata, while keeping discovery bounded.
HEADER_SEARCH_LIMIT = 200
# A name candidate locates a possible header; semantic validation happens separately.
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
    candidates = []
    width = max(map(len, rows), default=0)
    for row_index, row in enumerate(rows[:HEADER_SEARCH_LIMIT]):
        cells = [cell_text(cell) for cell in row]
        # A merged document title is not a column header in a multi-column table.
        if width > 1 and sum(bool(cell) for cell in cells) < 2:
            continue
        # Numeric amounts alongside product text indicate data, not header labels.
        if any(text.isdigit() for text in cells):
            continue
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
                layout.extras[col_index] = (
                    f"{text} ({col_index + 1})" if text in layout.extras.values() else text
                )

        if _REQUIRED_ROLES <= set(layout.roles.values()):
            roles = set(layout.roles.values())
            score = (
                10 * ("quantity" in roles or {"quantity_packs", "units_per_pack"} <= roles)
                + 4 * ("unit" in roles)
                + len(roles)
            )
            candidates.append((score, -row_index, layout))
    return max(candidates, key=lambda candidate: candidate[:2])[2] if candidates else None


def is_table_well_structured(rows: list[list[object]]) -> bool:
    """Cheap check used by the PDF parser to decide between table heuristics and the LLM fallback."""
    if len(rows) < 2 or max(map(len, rows), default=0) < 2:
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
    for row in rows[:HEADER_SEARCH_LIMIT]:
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
    custom_columns: list[CustomColumnSpec] | None = None,
    mapping_session=None,
    context: str = "",
) -> ParsedDocument:
    """layout, when given, skips heuristic header detection entirely - lets a caller hand in an
    already-computed layout instead of the keyword-derived one this module computes on its own."""
    document = ParsedDocument()
    from app.parsing.table_mapping import MappingSession, strict_quantity

    mapping_session = mapping_session or MappingSession()
    proposed = layout if layout is not None else _find_header_row(rows)
    layout, mapping_warnings, used_llm = mapping_session.resolve(rows, proposed, page, context)
    document.warnings.extend(mapping_warnings)
    document.used_llm_fallback = used_llm
    uncertain = bool(mapping_warnings)
    document.table_mappings = mapping_session.export()

    if layout is None:
        document.warnings.append("No recognizable header row found; treated as headerless table")
        layout = HeaderLayout(row_index=-1, roles={0: "name", 1: "quantity", 2: "unit", 3: "notes"})
        data_rows = rows
        in_scope_columns = None
    else:
        data_rows = rows[layout.row_index + 1 :]
        in_scope_columns = set(layout.labels)
        skipped = (
            _skipped_column_labels(rows[layout.row_index], in_scope_columns)
            if layout.row_index >= 0
            else []
        )
        if skipped:
            document.warnings.append(f"Ignored supplier/admin columns: {', '.join(skipped)}")
            document.available_columns = skipped

    start_index = layout.row_index + 1

    for offset, row in enumerate(data_rows):
        row_number = start_index + offset + 1
        values = {role: cell_text(row[col]) for col, role in layout.roles.items() if col < len(row)}
        name = values.get("name", "")
        if not name or name.strip().lower() in {"total", "grand total", "subtotal"}:
            continue
        row_issues = []
        if not any(c.isalpha() for c in name):
            row_issues.append("Product name appears to be an identifier")

        raw_quantity = values.get("quantity", "")
        quantity = strict_quantity(raw_quantity) if raw_quantity else None
        if raw_quantity and quantity is None:
            row_issues.append("Requested quantity is not a valid whole number")
        if quantity == 0:
            row_issues.append("Requested quantity must be positive")
        unit = values.get("unit", "")
        if quantity is not None and not unit:
            _, source_unit = extract_quantity_and_unit(raw_quantity)
            unit = source_unit or ""
        if unit and not any(c.isalpha() for c in unit):
            unit = ""
            row_issues.append("Numeric value cannot be used as a unit")

        attributes = {
            label: cell_text(row[col])
            for col, label in layout.extras.items()
            if col < len(row) and cell_text(row[col])
        }

        packs_raw = values.get("quantity_packs", "")
        per_pack_raw = values.get("units_per_pack", "")
        packs = strict_quantity(packs_raw) if packs_raw else None
        per_pack = strict_quantity(per_pack_raw) if per_pack_raw else None
        if packs_raw:
            attributes["Packs requested"] = packs_raw
        if per_pack_raw:
            attributes["Units per pack"] = per_pack_raw
        if (packs_raw and packs is None) or (per_pack_raw and per_pack is None):
            row_issues.append("Invalid pack quantity")
        if packs is not None and per_pack is not None:
            computed = packs * per_pack
            if quantity is not None and quantity != computed:
                row_issues.append("Requested total conflicts with packs × units per pack")
            elif quantity is None and not raw_quantity:
                quantity = computed

        if quantity is None and not unit and not raw_quantity:
            # Require an explicit quantity/unit expression, never the first dosage or model number.
            inferred_quantity, inferred_unit = extract_quantity_and_unit(name)
            if inferred_unit:
                quantity, unit = inferred_quantity, inferred_unit

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
        item = build_item(
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
            source_type=values.get("domain", ""),
        )
        if row_issues or uncertain:
            item.confidence = min(item.confidence or 40, 40 if uncertain else 60)
            if item.status != "missing":
                item.status = "low_confidence" if uncertain else "needs_review"
        if row_issues:
            document.warnings.append(f"Page {page}, row {row_number}: " + "; ".join(row_issues))
        item.review_reasons = row_issues
        item.review_source = {
            "headers": {str(c): label for c, label in layout.labels.items()},
            "roles": {str(c): role for c, role in layout.roles.items()},
            "context": context,
            "cells": {
                str(c): cell_text(cell)
                for c, cell in enumerate(row)
                if in_scope_columns is None or c in in_scope_columns
            },
            "mappingUncertain": uncertain or layout.row_index < 0,
        }
        document.items.append(item)

    document.rows_detected = len(document.items)
    document.attribute_columns = _surviving_attribute_columns(document)

    if custom_columns and layout.row_index >= 0:
        # Lazy import: custom_columns.py imports cell_text/HeaderLayout from this module.
        from app.parsing.custom_columns import apply_custom_columns

        apply_custom_columns(rows, layout.row_index, custom_columns, document)

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
