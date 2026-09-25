"""Shared data types produced by the file parsers, independent of persistence/API shape."""

from dataclasses import dataclass, field
from typing import Literal

Priority = Literal["critical", "high", "medium", "low"]
ItemStatus = Literal["verified", "needs_review", "low_confidence", "missing"]

_MAX_CUSTOM_COLUMN_NAME = 60


@dataclass
class CustomColumnSpec:
    """A column the user explicitly asked to be extracted, requested after the initial extraction
    from the review screen (see ReviewItemsScreen's "Add column" control) - display_name is what
    they want it called; hint, if given, is a source column name or short description of where to
    find it (the "Add column" control passes the picked/typed text as both). Applies across all
    parsers (table and free-text); an explicit request overrides the default supplier/admin-column
    exclusion."""

    display_name: str
    hint: str = ""

    def __post_init__(self) -> None:
        self.display_name = self.display_name.strip()[:_MAX_CUSTOM_COLUMN_NAME]
        self.hint = self.hint.strip()[:_MAX_CUSTOM_COLUMN_NAME]


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
    domain: Literal["medicine", "equipment"] | None = None
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
    # Header labels this document's table has but that weren't extracted (supplier/admin columns
    # scoped out by classify_columns) - offered back to the user after the fact as "other columns
    # you can add" (see custom_columns.py / the /custom-columns endpoint). Empty for headerless
    # tables and free-text documents, where there's no detected header row to offer choices from.
    available_columns: list[str] = field(default_factory=list)
