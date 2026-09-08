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
