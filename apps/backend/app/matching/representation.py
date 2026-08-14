"""Deterministic text representations shared by retrieval implementations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from app.matching.contracts import AttributeValue, InquiryLineV1, InventoryItemV1
from app.matching.domain import SearchRepresentation

TOKEN_PATTERN = re.compile(r"[\wµ%./+-]+", flags=re.UNICODE)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(TOKEN_PATTERN.findall(normalized))


def tokenize(value: str) -> frozenset[str]:
    return frozenset(token for token in normalize_text(value).split() if token)


def _attribute_text(attributes: dict[str, AttributeValue]) -> list[str]:
    rendered: list[str] = []
    for name, attribute in sorted(attributes.items()):
        value, unit = attribute.comparable()
        rendered.append(f"{normalize_text(name)}={value}{f' {unit}' if unit else ''}")
    return rendered


def _build(core_parts: list[str], attributes: dict[str, AttributeValue]) -> SearchRepresentation:
    semantic_core = normalize_text(" ".join(part for part in core_parts if part))
    canonical_parts = [semantic_core, *_attribute_text(attributes)]
    canonical_text = "; ".join(part for part in canonical_parts if part)
    content_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return SearchRepresentation(
        semantic_core=semantic_core,
        canonical_text=canonical_text,
        tokens=tokenize(canonical_text),
        content_hash=content_hash,
    )


def represent_inquiry(line: InquiryLineV1) -> SearchRepresentation:
    return _build(
        [line.raw_description, line.translated_description or ""],
        line.attributes,
    )


def represent_inventory_item(item: InventoryItemV1) -> SearchRepresentation:
    return _build(
        [*item.descriptions, item.manufacturer or "", item.brand or ""],
        item.attributes,
    )


def stable_json_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
