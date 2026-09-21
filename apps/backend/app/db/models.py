"""SQLAlchemy models for persisted partner import requests and their extracted line items."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, ForeignKey, LargeBinary, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ImportRequestRow(Base):
    """One uploaded partner request file and the partner metadata collected for it."""

    __tablename__ = "import_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(unique=True, index=True)

    source_file_name: Mapped[str]
    rows_detected: Mapped[int] = mapped_column(default=0)

    partner: Mapped[str] = mapped_column(default="")
    region: Mapped[str] = mapped_column(default="")
    contact: Mapped[str] = mapped_column(default="")
    confirmed: Mapped[bool] = mapped_column(default=False)
    request_date: Mapped[str | None] = mapped_column(default=None)

    used_llm_fallback: Mapped[bool] = mapped_column(default=False)
    parser_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Ordered labels of the extra, file-specific columns this import contributed, so the review
    # table can render the same columns it extracted rather than a fixed set.
    attribute_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    # User-renamed column headers for this request: {column key: custom label}. Core fields use
    # a fixed key ("name", "quantity", ...); attribute columns use their own label as the key.
    column_labels: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # Header labels detected in the source file but not extracted into attribute_columns - offered
    # back to the user on the review screen as "other columns you can add" (see
    # repository.add_custom_column). Shrinks as columns get added; empty for free-text documents.
    available_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Custom columns the user has added after the fact from the review screen, as
    # [{"display_name": ..., "hint": ...}, ...] - kept so a later addition can be re-applied on
    # top of every prior one when the file is re-parsed (see repository.add_custom_column).
    custom_columns: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # The originally uploaded file, kept so a custom column requested after the fact can be
    # extracted by re-parsing the same source rather than asking the user to re-upload. Absent
    # (None) for rows that predate this column or the fixture demo request.
    raw_file: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)

    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    items: Mapped[list["RequestItemRow"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RequestItemRow.position",
    )
    source_references: Mapped[list["RequestSourceReferenceRow"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
    )


class RequestItemRow(Base):
    """One extracted line item. Its id is the global "item id" used in existing item routes."""

    __tablename__ = "request_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("import_requests.request_id"), index=True)
    position: Mapped[int] = mapped_column(default=0)

    name: Mapped[str]
    quantity: Mapped[int | None] = mapped_column(default=None)
    unit: Mapped[str] = mapped_column(default="")
    notes: Mapped[str] = mapped_column(default="")
    item_number: Mapped[str] = mapped_column(default="")
    shelf_life: Mapped[str] = mapped_column(default="")
    # {source column label: value} for columns outside the core fields - see
    # ImportRequestRow.attribute_columns for the ordering used when displaying them.
    attributes: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    priority: Mapped[str] = mapped_column(default="medium")
    confidence: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="needs_review")

    request: Mapped[ImportRequestRow] = relationship(back_populates="items")
    source_reference: Mapped["RequestSourceReferenceRow | None"] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        uselist=False,
    )


class RequestSourceReferenceRow(Base):
    """The source excerpt (page/row + raw text) an item was extracted from."""

    __tablename__ = "request_source_references"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("import_requests.request_id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("request_items.id"), unique=True)

    page: Mapped[int] = mapped_column(default=0)
    row: Mapped[int] = mapped_column(default=0)
    excerpt: Mapped[str] = mapped_column(default="")

    request: Mapped[ImportRequestRow] = relationship(back_populates="source_references")
    item: Mapped[RequestItemRow] = relationship(back_populates="source_reference")
