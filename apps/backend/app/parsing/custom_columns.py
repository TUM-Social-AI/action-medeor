"""User-requested custom columns: fields a user explicitly asked to be extracted after the fact,
from the review screen's "Add column" control (see ReviewItemsScreen and
repository.add_custom_column), by display name and an optional hint (a source column name or
short description). Unlike every other extraction path in this package, an explicit request
deliberately overrides the default supplier/admin-column exclusion - if the user names it, we
look for it everywhere in the document, not just the columns already scoped as "the partner's
own request".

Two mechanisms, in order:
1. Deterministic hint match: if a hint is given and it substring-matches a real header (accent-
   folded), use that column directly - free, no LLM call.
2. LLM match: any requests left unresolved (no hint, or the hint didn't match anything) go into
   one batched call that sees every column header + sample data and picks the best match per
   request, or "not found". Only engages when there's an actual gap, same pattern as the
   quantity gap-fill in llm_table_classifier.py.
"""

from typing import Literal

from pydantic import BaseModel

from app.parsing.keywords import normalize
from app.parsing.llm_client import LlmUnavailable, call_llm
from app.parsing.table_parser import cell_text
from app.parsing.types import CustomColumnSpec, ParsedDocument

_MAX_SAMPLE_VALUES = 6
_MAX_VALUE_CHARS = 40


def apply_custom_columns(
    rows: list[list[object]],
    header_row_index: int,
    specs: list[CustomColumnSpec],
    document: ParsedDocument,
) -> None:
    """Mutates document.items in place, adding a resolved column's value into each item's
    attributes; mutates document.warnings for any request that couldn't be resolved at all."""
    specs = [spec for spec in specs if spec.display_name]
    if not specs or header_row_index < 0 or header_row_index >= len(rows):
        return

    header_cells = [cell_text(cell) for cell in rows[header_row_index]]
    resolved: dict[str, int] = {}
    unresolved: list[CustomColumnSpec] = []

    for spec in specs:
        column = _match_by_hint(spec.hint, header_cells) if spec.hint else None
        if column is not None:
            resolved[spec.display_name] = column
        else:
            unresolved.append(spec)

    if unresolved:
        try:
            resolved.update(_match_with_llm(rows, header_row_index, header_cells, unresolved))
        except LlmUnavailable as exc:
            document.warnings.append(f"Custom column matching unavailable ({exc})")

    still_missing = [spec.display_name for spec in specs if spec.display_name not in resolved]
    if still_missing:
        document.warnings.append(f"Could not find a column for: {', '.join(still_missing)}")

    for item in document.items:
        if item.row < 1 or item.row > len(rows):
            continue
        raw_row = rows[item.row - 1]
        for display_name, column in resolved.items():
            if column < len(raw_row):
                value = cell_text(raw_row[column])
                if value:
                    item.attributes[display_name] = value

    # User-requested columns survive even if every matched value happened to be blank on this
    # particular file - unlike the general "drop empty attribute columns" rule, an explicit
    # request should never just silently vanish from the table.
    document.attribute_columns = list(
        dict.fromkeys([*document.attribute_columns, *resolved.keys()])
    )


def _match_by_hint(hint: str, header_cells: list[str]) -> int | None:
    normalized_hint = normalize(hint)
    if not normalized_hint:
        return None
    for index, label in enumerate(header_cells):
        if normalized_hint in normalize(label):
            return index
    return None


class _CustomColumnMatch(BaseModel):
    display_name: str
    column_index: int | Literal["not_found"]


class _CustomColumnMatchResult(BaseModel):
    matches: list[_CustomColumnMatch]


_PROMPT = """\
You are matching user-requested fields to columns in a document table, so their values can be
extracted. Look at every column's header AND its sample data values - a header alone can be
vague or absent, but the actual data usually makes the right column obvious.

All columns (index -> header label), sample values from real rows:
{columns_text}

Requested fields (the user wants these extracted, using their own chosen names):
{requests_text}

For each requested field, return the column_index of the single best-matching column, or
"not_found" if nothing in this table actually reports that field. Do not guess if there is
genuinely no reasonable match - "not_found" is a correct answer, not a failure.
"""


def _match_with_llm(
    rows: list[list[object]],
    header_row_index: int,
    header_cells: list[str],
    specs: list[CustomColumnSpec],
) -> dict[str, int]:
    columns_text = _format_columns(rows, header_row_index, header_cells)
    requests_text = "\n".join(
        f"- {spec.display_name!r}" + (f" (hint: {spec.hint!r})" if spec.hint else "")
        for spec in specs
    )
    prompt = _PROMPT.format(columns_text=columns_text, requests_text=requests_text)
    result = call_llm(prompt, _CustomColumnMatchResult)

    requested_names = {spec.display_name for spec in specs}
    resolved: dict[str, int] = {}
    for match in result.matches:
        if match.display_name not in requested_names or match.display_name in resolved:
            continue
        if isinstance(match.column_index, int) and 0 <= match.column_index < len(header_cells):
            resolved[match.display_name] = match.column_index
    return resolved


def _format_columns(rows: list[list[object]], header_row_index: int, header_cells: list[str]) -> str:
    data_rows = rows[header_row_index + 1 :]
    lines = []
    for index, label in enumerate(header_cells):
        values: list[str] = []
        for row in data_rows:
            if index < len(row):
                text = cell_text(row[index])
                if text:
                    values.append(text if len(text) <= _MAX_VALUE_CHARS else text[:_MAX_VALUE_CHARS] + "…")
            if len(values) >= _MAX_SAMPLE_VALUES:
                break
        lines.append(f"{index}: {label!r} - sample values: {values}")
    return "\n".join(lines)
