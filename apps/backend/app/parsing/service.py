"""Entry point for the parsing package: dispatch an uploaded file to the right parser."""

from app.parsing.excel_parser import parse_excel
from app.parsing.pdf_parser import parse_pdf
from app.parsing.types import ParsedDocument


class ParsingError(Exception):
    """Raised when a file can't be parsed at all (corrupt/unreadable), vs. yielding 0 items."""


def parse_upload(*, filename: str, content: bytes) -> ParsedDocument:
    extension = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""

    try:
        if extension in ("xlsx", "xls"):
            return parse_excel(content, filename)
        if extension == "pdf":
            return parse_pdf(content)
    except ParsingError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert any parser-library failure into ParsingError
        raise ParsingError(f"Could not read {filename}: {exc}") from exc

    raise ParsingError(f"Unsupported file extension: .{extension}")
