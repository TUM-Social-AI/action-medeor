"""PDF parsing: try structured tables first, fall back to an LLM pass over the raw text.

Strategy (see apps/backend README / PR description for the rationale):
1. Extract text + tables per page with pdfplumber (free, deterministic).
2. If a page's table is well-structured (recognizable header, consistent column count), parse it
   with the same heuristics as Excel - no LLM call. table_parser.parse_table_rows transparently
   tries an LLM quantity gap-fill only when the heuristic scoped columns but found no quantity
   signal among them at all (see llm_table_classifier.py) - it can enrich a result, never
   override an already-correct one.
3. Otherwise, hand the raw text to the shared free-text fallback (LLM, then naive regex parse -
   see free_text_parser.py).
"""

from app.parsing.free_text_parser import extract_from_free_text
from app.parsing.table_parser import is_table_well_structured, parse_table_rows
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
        document.items.extend(extract_from_free_text(remaining_text, document))

    document.rows_detected = len(document.items)
    if not document.items:
        document.warnings.append("No line items could be extracted from this PDF")
    return document


def _best_table(tables: list[list[list[object]]] | None) -> list[list[object]] | None:
    if not tables:
        return None
    return max(tables, key=len)
