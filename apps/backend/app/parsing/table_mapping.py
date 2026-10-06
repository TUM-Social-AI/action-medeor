"""Semantic checks, validated layouts, and per-upload/persisted mapping reuse."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from app.parsing.keywords import (
    UNIT_TOKENS,
    classify_columns,
    is_ordinal_column,
    is_request_side,
    is_supplier_block_start,
    is_supplier_field,
    match_column_role,
    normalize,
)
from app.parsing.llm_table_classifier import (
    ColumnMapping,
    LlmUnavailable,
    TableMapping,
    map_table_with_llm,
)
from app.parsing.table_parser import HEADER_SEARCH_LIMIT, HeaderLayout, cell_text

logger = logging.getLogger(__name__)


class MappingRejected(ValueError):
    """A mapping validation failure whose message contains no source values."""


def layout_issues(rows, layout: HeaderLayout | None, *, check_headers: bool = True) -> list[str]:
    if layout is None:
        return ["No recognizable header"]
    issues = []
    if "name" not in layout.roles.values():
        issues.append("No product-name column")
    if check_headers and layout.row_index >= 0:
        cells = [cell_text(c) for c in rows[layout.row_index]]
        candidates = [
            match_column_role(c) for c, keep in zip(cells, classify_columns(cells)) if keep
        ]
        supplier_start = next(
            (i for i, c in enumerate(cells) if is_supplier_block_start(c)), len(cells)
        )
        if any(
            not cells[col]
            and any(col < len(row) and cell_text(row[col]) for row in rows[layout.row_index + 1 :])
            for col in range(supplier_start)
        ):
            issues.append("Blank or merged headers have populated columns")
        if any(is_supplier_field(c) and not is_request_side(c) for c in cells[:supplier_start]):
            issues.append("Request/supplier column boundary is unclear")
        if any(candidates.count(role) > 1 for role in set(candidates) - {None}):
            issues.append("Competing column roles or request/supplier groups")
        if not (
            "quantity" in candidates or {"quantity_packs", "units_per_pack"} <= set(candidates)
        ):
            # Missing amounts are not a mapping gap unless other columns could contain them.
            if any(
                re.fullmatch(r"[\d.,\s]+", cell_text(row[col]))
                for col in layout.extras
                for row in rows[layout.row_index + 1 :]
                if col < len(row) and cell_text(row[col])
            ):
                issues.append("Requested quantity column is unclear")
    for row in rows[layout.row_index + 1 :]:
        values = {role: cell_text(row[col]) for col, role in layout.roles.items() if col < len(row)}
        if values.get("name") and not any(c.isalpha() for c in values["name"]):
            issues.append("Product-name column contains numeric identifiers")
        if values.get("unit") and not any(c.isalpha() for c in values["unit"]):
            issues.append("Unit column contains numbers")
        for role in ("quantity", "quantity_packs", "units_per_pack"):
            if values.get(role) and strict_quantity(values[role]) is None:
                issues.append("Quantity column contains non-quantity values")
    return list(dict.fromkeys(issues))


def strict_quantity(value: object) -> int | None:
    """Nonnegative integers, with standard thousands separators; never doses/codes/fractions."""
    text = cell_text(value)
    amount_unit = re.fullmatch(r"([\d.,\s]+)\s*([^\d\s]+)", text)
    if amount_unit and amount_unit.group(2).lower() in UNIT_TOKENS:
        text = amount_unit.group(1).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if re.fullmatch(r"\d{1,3}(?:[,.\s]\d{3})+", text):
        return int(re.sub(r"[,.\s]", "", text))
    if re.fullmatch(r"\d+\.0+", text):
        return int(float(text))
    return None


def validated_layout(rows, mapping: TableMapping) -> HeaderLayout:
    width = max(map(len, rows), default=0)
    header = mapping.header_row_index
    if header < -1 or header >= min(HEADER_SEARCH_LIMIT, len(rows)):
        raise MappingRejected("Invalid header position")
    if header >= len(rows) - 1:
        raise MappingRejected("No data rows after header")
    indices = [c.column_index for c in mapping.columns]
    if len(indices) != width or set(indices) != set(range(width)):
        raise MappingRejected("Missing, duplicated or invalid column indices")
    cells = [cell_text(c) for c in rows[header]] if header >= 0 else [""] * width
    if header >= 0:
        numeric_columns = {
            col for col, cell in enumerate(cells) if cell and strict_quantity(cell) is not None
        }
        if numeric_columns and (
            not {"name", "quantity"} <= {match_column_role(cell) for cell in cells}
            or any(
                column.column_index in numeric_columns
                and column.role not in {"none", "ordinal"}
                for column in mapping.columns
            )
        ):
            raise MappingRejected("Data row selected as header")
    kept = classify_columns(cells)
    layout = HeaderLayout(row_index=header)
    for column in mapping.columns:
        col, role = column.column_index, column.role
        label = cells[col] if col < len(cells) else ""
        if column.scope != "request":
            if role not in {"none", "ordinal"}:
                raise MappingRejected("Non-request field assigned a request role")
            if column.scope == "unknown" and any(
                col < len(row) and cell_text(row[col]) for row in rows[header + 1 :]
            ):
                raise MappingRejected("Populated column scope remains unresolved")
            continue
        if col < len(kept) and label and not kept[col] and not is_ordinal_column(label):
            raise MappingRejected("Explicit supplier/admin exclusion overridden")
        if role in {"none", "ordinal"}:
            continue
        layout.labels[col] = label or f"Column {col + 1}"
        if role == "attribute":
            # Repeated labels cannot silently overwrite each other's data.
            extra_label = layout.labels[col]
            if extra_label in layout.extras.values():
                extra_label = f"{extra_label} ({col + 1})"
            layout.extras[col] = extra_label
        else:
            if role in layout.roles.values():
                raise MappingRejected("Duplicate core role")
            layout.roles[col] = role
    problems = layout_issues(rows, layout, check_headers=False)
    if problems:
        raise MappingRejected("; ".join(problems))
    # A mapping that hides an entire populated request amount is not a resolution.
    if not (
        "quantity" in layout.roles.values()
        or {"quantity_packs", "units_per_pack"} <= set(layout.roles.values())
    ):
        if "Requested quantity column is unclear" in layout_issues(rows, layout):
            raise MappingRejected("Requested quantity remains unresolved")
    return layout


@dataclass
class MappingSession:
    persisted: dict = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)

    def resolve(self, rows, proposed, page: int, context: str):
        # Data values are deliberately excluded: identical layouts reuse a decision, while
        # every subsequent table still undergoes semantic validation against its own values.
        header = proposed.row_index if proposed else -1
        identity = {
            "width": max(map(len, rows), default=0),
            "header": header,
            "labels": [normalize(cell_text(c)) for c in rows[header]] if header >= 0 else [],
            "groups": [[normalize(cell_text(c)) for c in row] for row in rows[: max(header, 0)]],
            "scope_headings": [
                normalize(line)
                for line in context.splitlines()
                if is_supplier_block_start(line) or is_request_side(line)
            ],
        }
        if proposed is None:
            first = [cell_text(c) for c in rows[0]] if rows else []
            if first and all(
                not c or (any(ch.isalpha() for ch in c) and strict_quantity(c) is None)
                for c in first
            ):
                identity["unknown_header_candidates"] = [normalize(c) for c in first]
            else:
                # With no labels, equal column counts do not establish equal meanings.
                identity["unlabelled_source_page"] = page
        signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        key = str(page)
        saved = (
            self.persisted.get("tables", {}).get(key)
            if self.persisted.get("version") == 1
            else None
        )
        record = (
            saved if saved and saved.get("signature") == signature else self.cache.get(signature)
        )
        if record:
            try:
                if record.get("mapping"):
                    layout = validated_layout(rows, TableMapping.model_validate(record["mapping"]))
                else:
                    layout = proposed
                issues = layout_issues(rows, layout, check_headers=not record["used_llm"])
                # Known ambiguity from a failed call must not trigger repeated paid attempts.
                warnings = list(dict.fromkeys([*record["warnings"], *issues]))
                self.records[key] = {**record, "warnings": warnings}
                return layout, warnings, record["used_llm"]
            except (ValueError, KeyError, TypeError):
                logger.info("Cached table mapping failed validation at page=%s", page)
                # Don't call the model again for the same layout in this upload.
                warnings = [
                    "Reused column mapping does not fit these rows; review basic extraction"
                ]
                self.records[key] = {
                    **record,
                    "warnings": warnings,
                    "used_llm": False,
                    "mapping": None,
                }
                return proposed, warnings, False
        issues = layout_issues(rows, proposed)
        layout, mapping, used_llm, warnings = proposed, None, False, []
        if issues:
            try:
                mapping = map_table_with_llm(rows, proposed, context)
                layout = validated_layout(rows, mapping)
                used_llm = True
            except (LlmUnavailable, ValueError) as exc:
                reason = str(exc) if isinstance(exc, MappingRejected) else type(exc).__name__
                logger.warning("Table mapping unavailable at page=%s: %s", page, reason)
                warnings = [
                    "Columns could not be confirmed; review basic extraction: " + "; ".join(issues)
                ]
                mapping = None
        if not issues and proposed is not None:
            mapping = TableMapping(
                header_row_index=proposed.row_index,
                columns=[
                    ColumnMapping(
                        column_index=col,
                        role=proposed.roles.get(
                            col, "attribute" if col in proposed.extras else "none"
                        ),
                        scope="request" if col in proposed.labels else "admin",
                    )
                    for col in range(max(map(len, rows), default=0))
                ],
            )
        record = {
            "signature": signature,
            "mapping": mapping.model_dump() if mapping else None,
            "used_llm": used_llm,
            "warnings": warnings,
        }
        self.cache[signature] = record
        self.records[key] = record
        return layout, warnings, used_llm

    def export(self):
        return {"version": 1, "tables": self.records}
