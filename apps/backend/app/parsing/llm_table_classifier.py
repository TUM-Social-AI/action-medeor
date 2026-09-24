"""LLM-assisted quantity-gap filling for tables where the keyword heuristic scoped the partner's
own columns correctly but found no quantity signal among them at all.

An earlier version of this module asked an LLM to classify every column in a table from scratch,
including deciding which columns belong to a supplier's quote versus the partner's own request.
Tested live against a reconstruction of a real ambiguous case (a form repeating a near-identical
"Unit Qty" label once for the partner's request and again for a supplier's computed total): the
LLM picked the wrong column and additionally mislabeled an unrelated column as "unit". The
deterministic heuristic (table_parser.classify_columns's supplier-block scoping, together with
match_column_role checking specific roles before the generic "name" catch-all) already resolves
that exact ambiguity correctly on its own - so that broader design was dropped rather than shipped
into a path that can override an already-correct result.

What's left here is narrower and can only help, never hurt: table_parser.classify_columns has
already excluded supplier/admin columns deterministically, so by the time this runs, every
candidate column is already known to be part of the partner's own request - genuinely supplier
data is never shown to the model. It is only invoked when none of those columns matched a
quantity-bearing role at all, which happens when a form splits the requested amount across a
"packs requested" column and a separate "units per pack" column that no keyword list can name in
advance. One call, only on that gap; if it finds nothing, the caller's original layout (and its
existing "quantity missing" handling) is unchanged.
"""

from typing import Literal

from pydantic import BaseModel

from app.parsing.llm_client import LlmUnavailable, call_llm
from app.parsing.table_parser import HeaderLayout, cell_text

__all__ = ["LlmUnavailable", "fill_quantity_gap_with_llm"]

_MAX_SAMPLE_VALUES = 6
_MAX_VALUE_CHARS = 40

_QuantityRoleLiteral = Literal["quantity_total", "quantity_packs", "units_per_pack", "none"]

_ROLE_MAP: dict[str, str] = {
    "quantity_total": "quantity",
    "quantity_packs": "quantity_packs",
    "units_per_pack": "units_per_pack",
}


class _QuantityColumnClassification(BaseModel):
    column_index: int
    role: _QuantityRoleLiteral


class _QuantityGapResult(BaseModel):
    columns: list[_QuantityColumnClassification]


_PROMPT = """\
You are looking at columns from a medical-supply request table that a keyword-based parser
could not confidently label. The item name and the columns' scope (these are already known to
belong to the partner's own request, not a supplier's quote) are settled; you only need to find
where the REQUESTED QUANTITY is reported here, if it's in this list at all.

Sometimes the quantity is a single column with the total number of individual units requested.
Other times a form splits it across two columns instead: one for how many packs/boxes/cartons
are requested, and a separate one for how many individual units make up one pack - the real
total the partner needs is those two multiplied together.

Candidate columns, with sample values taken from real rows of this table:
{columns_text}

Classify EVERY candidate column index into exactly one role:
- "quantity_total": already reports the total number of individual units requested - not a pack
  count.
- "quantity_packs": the number of packs/boxes/cartons requested - pairs with a units_per_pack
  column and must be multiplied by it to get the real total.
- "units_per_pack": how many individual units make up one pack - pairs with quantity_packs.
- "none": not a quantity signal at all (e.g. a price, a date, a code, free text).

At most one column may be "quantity_total". At most one may be "quantity_packs" and at most one
"units_per_pack" - never assign both a quantity_total AND a quantity_packs/units_per_pack pair.
If nothing in this list represents the requested quantity, classify every column "none".
"""


def fill_quantity_gap_with_llm(rows: list[list[object]], layout: HeaderLayout) -> HeaderLayout:
    """Raises LlmUnavailable (no key, or the call fails) - callers should catch it and keep using
    their original layout unchanged, the same as any other LLM fallback in this package."""
    candidate_columns = sorted(layout.extras)
    if not candidate_columns:
        raise LlmUnavailable("No candidate columns available for quantity gap-filling")

    columns_text = _format_candidate_columns(rows, layout.row_index, candidate_columns, layout.labels)
    result = call_llm(_PROMPT.format(columns_text=columns_text), _QuantityGapResult)
    return _apply_gap_fill(layout, candidate_columns, result)


def _format_candidate_columns(
    rows: list[list[object]],
    header_row_index: int,
    candidate_columns: list[int],
    labels: dict[int, str],
) -> str:
    data_rows = rows[header_row_index + 1 :]
    lines = []
    for col in candidate_columns:
        values: list[str] = []
        for row in data_rows:
            if col < len(row):
                text = cell_text(row[col])
                if text:
                    values.append(text if len(text) <= _MAX_VALUE_CHARS else text[:_MAX_VALUE_CHARS] + "…")
            if len(values) >= _MAX_SAMPLE_VALUES:
                break
        lines.append(f"{col}: {labels.get(col, '')!r} - sample values: {values}")
    return "\n".join(lines)


def _apply_gap_fill(
    layout: HeaderLayout,
    candidate_columns: list[int],
    result: _QuantityGapResult,
) -> HeaderLayout:
    updated = HeaderLayout(
        row_index=layout.row_index,
        roles=dict(layout.roles),
        extras=dict(layout.extras),
        labels=dict(layout.labels),
    )
    assigned_roles = set(updated.roles.values())

    for entry in sorted(result.columns, key=lambda c: c.column_index):
        if entry.role == "none" or entry.column_index not in candidate_columns:
            continue
        role_key = _ROLE_MAP[entry.role]
        if role_key in assigned_roles:
            continue  # model repeated a role it already used - keep the first, ignore the rest
        assigned_roles.add(role_key)
        updated.roles[entry.column_index] = role_key
        updated.extras.pop(entry.column_index, None)

    return updated
