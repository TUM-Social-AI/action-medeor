"""Shared data types produced by the file parsers, independent of persistence/API shape."""

from dataclasses import dataclass, field
from typing import Literal

Priority = Literal["critical", "high", "medium", "low"]
ItemStatus = Literal["verified", "needs_review", "low_confidence", "missing"]


@dataclass
class ParsedLineItem:
    """One request line extracted from a source file, before it is persisted."""

    name: str
    quantity: int | None
    unit: str
    notes: str = ""
    item_number: str = ""
    shelf_life: str = ""
    # Source columns that carry real request information but don't map to a core field, kept as
    # {original header label: value} so the review screen can surface them per file. Which
    # labels a document actually contributes is tracked on ParsedDocument.attribute_columns.
    attributes: dict[str, str] = field(default_factory=dict)
    priority: Priority = "medium"
    confidence: int | None = None
    status: ItemStatus = "needs_review"
    page: int = 0
    row: int = 0
    excerpt: str = ""


@dataclass
class ParsedDocument:
    """Everything extracted from one uploaded file."""

    items: list[ParsedLineItem] = field(default_factory=list)
    rows_detected: int = 0
    warnings: list[str] = field(default_factory=list)
    used_llm_fallback: bool = False
    # Ordered labels of the extra columns this document contributed, in source column order.
    # Columns that were empty for every row are dropped, so this reflects what's worth showing.
    attribute_columns: list[str] = field(default_factory=list)
