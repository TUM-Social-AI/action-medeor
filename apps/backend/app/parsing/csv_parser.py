"""CSV parsing: read a CSV file into rows and hand them to the same table heuristics Excel uses
(header detection, column-role matching, supplier-block scoping, quantity gap-fill, etc.) -
a CSV is the same underlying shape, just text-delimited instead of binary.
"""

import csv
import io

from app.parsing.table_parser import extract_request_priority_hint, parse_table_rows
from app.parsing.types import ParsedDocument

_DECODE_ATTEMPTS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_SNIFF_SAMPLE_CHARS = 4096


def parse_csv(content: bytes) -> ParsedDocument:
    text = _decode(content)
    rows = _read_rows(text)

    if not rows:
        document = ParsedDocument()
        document.warnings.append("CSV file contained no rows")
        return document

    default_priority = extract_request_priority_hint(rows)
    return parse_table_rows(rows, default_priority=default_priority)


def _decode(content: bytes) -> str:
    for encoding in _DECODE_ATTEMPTS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 maps every byte 0-255, so the loop above never actually falls through to here in
    # practice - kept as an explicit last resort so a decode failure can't surface as a 500.
    return content.decode("latin-1", errors="replace")


def _read_rows(text: str) -> list[list[object]]:
    # Partner exports vary: comma is the CSV default, but semicolon is common in European
    # Excel exports (comma is the decimal separator there), and tab/pipe both show up too.
    sample = text[:_SNIFF_SAMPLE_CHARS]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # comma-delimited default when sniffing can't tell (e.g. one column)

    reader = csv.reader(io.StringIO(text), dialect)
    return [list(row) for row in reader]
