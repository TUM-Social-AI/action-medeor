"""Entry point for the parsing package: dispatch an uploaded file to the right parser."""

from app.parsing.csv_parser import parse_csv
from app.parsing.docx_parser import parse_docx
from app.parsing.excel_parser import parse_excel
from app.parsing.partner_extraction import basic_partner
from app.parsing.pdf_parser import parse_pdf
from app.parsing.table_mapping import MappingSession
from app.parsing.types import CustomColumnSpec, ParsedDocument

MAX_CUSTOM_COLUMNS = 10


class ParsingError(Exception):
    """Raised when a file can't be parsed at all (corrupt/unreadable), vs. yielding 0 items."""


def parse_upload(
    *,
    filename: str,
    content: bytes,
    custom_columns: list[CustomColumnSpec] | None = None,
    table_mappings: dict | None = None,
) -> ParsedDocument:
    extension = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
    custom_columns = (custom_columns or [])[:MAX_CUSTOM_COLUMNS]

    mapping_session = MappingSession(persisted=table_mappings or {})
    try:
        if extension in ("xlsx", "xls"):
            document = parse_excel(
                content, filename, custom_columns=custom_columns, mapping_session=mapping_session
            )
        elif extension == "pdf":
            document = parse_pdf(
                content, custom_columns=custom_columns, mapping_session=mapping_session
            )
        elif extension == "docx":
            document = parse_docx(content, custom_columns=custom_columns)
        elif extension == "csv":
            document = parse_csv(
                content, custom_columns=custom_columns, mapping_session=mapping_session
            )
        else:
            raise ParsingError(f"Unsupported file extension: .{extension}")
        if not document.items:
            document.warnings.append(
                "No requested line items could be extracted; check the source table or add items manually"
            )
        basic_partner(document, filename)
        return document
    except ParsingError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert any parser-library failure into ParsingError
        raise ParsingError(f"Could not read {filename}: {exc}") from exc
