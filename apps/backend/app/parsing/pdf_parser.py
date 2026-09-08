"""PDF parsing: try structured tables first, fall back to an LLM pass over the raw text.

Strategy (see apps/backend README / PR description for the rationale):
1. Extract text + tables per page with pdfplumber (free, deterministic).
2. If a page's table is well-structured (recognizable header, consistent column count), parse it
   with the same heuristics as Excel - no LLM call.
3. Otherwise, collect the raw text and hand it to the LLM fallback (one call per document). If no
   API key is configured or the call fails, fall back further to a naive per-line regex parse so
   the endpoint still returns *something* rather than failing the upload outright.
"""

from app.parsing.llm_extractor import LlmUnavailable, extract_items_with_llm
from app.parsing.table_parser import is_table_well_structured, parse_table_rows
from app.parsing.text_heuristics import build_item, extract_quantity_and_unit
from app.parsing.types import ParsedDocument


def parse_pdf(content: bytes) -> ParsedDocument:
    import io

    import pdfplumber

    document = ParsedDocument()
    structured_pages: list[tuple[int, list[list[object]]]] = []
    free_text_pages: list[tuple[int, str]] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            table = _best_table(tables)
            if table and is_table_well_structured(table):
                structured_pages.append((page_index, table))
            else:
                free_text_pages.append((page_index, page.extract_text() or ""))

    if structured_pages:
        for page_number, table in structured_pages:
            page_result = parse_table_rows(table, page=page_number)
            document.items.extend(page_result.items)
            document.warnings.extend(page_result.warnings)

    remaining_text = "\n".join(text for _, text in free_text_pages if text.strip())
    if remaining_text:
        document.items.extend(_extract_from_free_text(remaining_text, document))

    document.rows_detected = len(document.items)
    if not document.items:
        document.warnings.append("No line items could be extracted from this PDF")
    return document


def _best_table(tables: list[list[list[object]]] | None) -> list[list[object]] | None:
    if not tables:
        return None
    return max(tables, key=len)


def _extract_from_free_text(text: str, document: ParsedDocument) -> list:
    try:
        llm_result = extract_items_with_llm(text)
        document.warnings.extend(llm_result.warnings)
        document.used_llm_fallback = True
        return llm_result.items
    except LlmUnavailable as exc:
        document.warnings.append(f"LLM fallback unavailable ({exc}); used naive text parsing")
        return _naive_line_parse(text)


def _naive_line_parse(text: str) -> list:
    """Best-effort, no-LLM fallback: one candidate item per non-empty line with a number in it."""
    items = []
    for row_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or not any(char.isdigit() for char in stripped):
            continue

        quantity, unit = extract_quantity_and_unit(stripped)
        if quantity is None:
            continue

        items.append(
            build_item(
                name=stripped,
                quantity=quantity,
                unit=unit or "",
                row=row_number,
                excerpt=stripped,
                confidence=40,  # naive regex parse, no header/table context, no LLM - low trust
            )
        )
    return items
