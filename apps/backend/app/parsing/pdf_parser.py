"""Extract usable grids locally, resolve uncertain column meanings, then copy source cells."""

from app.parsing.free_text_parser import extract_from_free_text
from app.parsing.partner_extraction import capture_context
from app.parsing.table_mapping import MappingSession
from app.parsing.table_parser import is_table_well_structured, parse_table_rows
from app.parsing.types import CustomColumnSpec, ParsedDocument


def parse_pdf(
    content: bytes,
    custom_columns: list[CustomColumnSpec] | None = None,
    mapping_session: MappingSession | None = None,
) -> ParsedDocument:
    import io

    import pdfplumber

    mapping_session = mapping_session or MappingSession()
    document = ParsedDocument()
    structured_pages: list[tuple[int, list[list[object]], str]] = []
    free_text_pages: list[tuple[int, str]] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            capture_context(document, page_text)
            candidates = page.find_tables()
            selected = (
                max(candidates, key=lambda candidate: len(candidate.rows)) if candidates else None
            )
            table = selected.extract() if selected else None
            if table and is_table_well_structured(table):
                # Preserve headings above the chosen table without sending line-item text twice.
                top = selected.bbox[1]
                context = page.crop((0, 0, page.width, top)).extract_text() if top > 0 else ""
                structured_pages.append((page_index, table, context or ""))
            else:
                free_text_pages.append((page_index, page_text))

    available_columns: list[str] = []
    if structured_pages:
        for page_number, table, context in structured_pages:
            page_result = parse_table_rows(
                table,
                page=page_number,
                custom_columns=custom_columns,
                mapping_session=mapping_session,
                context=context,
            )
            document.items.extend(page_result.items)
            document.warnings.extend(page_result.warnings)
            if page_result.used_llm_fallback:
                document.used_llm_fallback = True
            for label in page_result.available_columns:
                if label not in available_columns:
                    available_columns.append(label)

    remaining_text = "\n".join(text for _, text in free_text_pages if text.strip())
    if remaining_text:
        document.items.extend(
            extract_from_free_text(remaining_text, document, custom_columns=custom_columns)
        )

    document.table_mappings = mapping_session.export()
    document.warnings = list(dict.fromkeys(document.warnings))
    document.rows_detected = len(document.items)
    document.attribute_columns = _merge_attribute_columns(document)
    document.available_columns = available_columns
    if not document.items:
        document.warnings.append("No line items could be extracted from this PDF")
    return document


def _best_table(tables: list[list[list[object]]] | None) -> list[list[object]] | None:
    if not tables:
        return None
    return max(tables, key=len)


def _merge_attribute_columns(document: ParsedDocument) -> list[str]:
    """First-seen order across every page's items - a per-page parse_table_rows() call already
    computes its own attribute_columns, but that's discarded once items are merged into one
    document here, so it has to be recomputed at this level too."""
    ordered: list[str] = []
    for item in document.items:
        for label in item.attributes:
            if label not in ordered:
                ordered.append(label)
    return ordered
