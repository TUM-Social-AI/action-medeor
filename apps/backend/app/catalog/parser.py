"""Strict parsers for the two Business Central CSV exports."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.catalog.contracts import CatalogImportErrorV1, CatalogImportValidationError
from app.matching.representation import normalize_text, stable_json_hash

ARTICLE_HEADERS = {
    "Nr.",
    "Nummer 2",
    "Beschreibung",
    "Beschreibung 2",
    "Basiseinheit",
    "Artikelkategoriencode",
    "Zollware (T1)",
    "Lagerbestand",
    "Menge in Bestellung",
    "Menge in Auftrag",
    "Wiederbeschaffungsverfahren",
}
TRANSLATION_HEADERS = {"Artikelnr.", "Sprachcode", "Beschreibung", "Beschreibung 2"}
LANGUAGE_MAP = {"ENU": "en", "ENG": "en", "FRA": "fr", "FRS": "fr"}


@dataclass(frozen=True)
class ParsedTranslation:
    raw_language_code: str
    locale: str
    description: str
    description_2: str
    content_hash: str


@dataclass(frozen=True)
class ParsedCatalogItem:
    item_number: str
    domain: str
    family_id: str | None
    descriptions: tuple[str, ...]
    translations: tuple[ParsedTranslation, ...]
    base_unit: str
    category_code: str
    t1: bool
    replenishment_method: str
    on_hand: Decimal
    incoming_purchase_order: Decimal
    committed_order: Decimal
    master_item: bool
    matching_eligible: bool
    canonical_text: str
    content_hash: str
    record_hash: str


@dataclass(frozen=True)
class ParsedCatalogImport:
    items: tuple[ParsedCatalogItem, ...]
    article_checksum: str
    translation_checksum: str
    warnings: tuple[str, ...]


def _decode_csv(data: bytes, document: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogImportValidationError(
            [
                CatalogImportErrorV1(
                    code="invalid_encoding",
                    message=f"{document} must be UTF-8 encoded: {exc}",
                )
            ]
        ) from exc


def _rows(data: bytes, document: str, required: set[str]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(_decode_csv(data, document), newline=""), delimiter=";")
    headers = {header.strip() for header in (reader.fieldnames or []) if header}
    missing = sorted(required - headers)
    if missing:
        raise CatalogImportValidationError(
            [
                CatalogImportErrorV1(
                    code="missing_headers",
                    message=f"{document} is missing required columns: {', '.join(missing)}",
                )
            ]
        )
    return [
        {str(key).strip(): (value or "").strip() for key, value in row.items() if key is not None}
        for row in reader
        if any((value or "").strip() for value in row.values())
    ]


def _quantity(value: str, *, row: int, field: str) -> Decimal:
    # Business Central exports German-formatted integral quantities, e.g. 21.821.
    normalized = value.replace(".", "").replace(",", ".")
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise CatalogImportValidationError(
            [
                CatalogImportErrorV1(
                    row=row,
                    field=field,
                    code="invalid_quantity",
                    message=f"{field} is not a valid number: {value!r}",
                )
            ]
        ) from exc
    if number < 0:
        raise CatalogImportValidationError(
            [
                CatalogImportErrorV1(
                    row=row,
                    field=field,
                    code="negative_source_quantity",
                    message=f"{field} cannot be negative in the ERP source report.",
                )
            ]
        )
    return number


def _domain(item_number: str, category_code: str) -> str:
    if category_code.startswith("2") or item_number.startswith("82"):
        return "medicine"
    if category_code.startswith("4") or item_number.startswith("84"):
        return "equipment"
    return "unknown"


def _unique_texts(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        key = normalize_text(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _canonical_text(
    descriptions: tuple[str, ...], *, category_code: str, base_unit: str
) -> str:
    text = " ; ".join(normalize_text(value) for value in descriptions if value)
    attributes = "; ".join(
        value
        for value in (
            f"category={normalize_text(category_code)}" if category_code else "",
            f"base_unit={normalize_text(base_unit)}" if base_unit else "",
        )
        if value
    )
    return "; ".join(value for value in (text, attributes) if value)


def parse_catalog_files(article_data: bytes, translation_data: bytes) -> ParsedCatalogImport:
    article_rows = _rows(article_data, "Artikeldaten.csv", ARTICLE_HEADERS)
    translation_rows = _rows(
        translation_data, "Artikeluebersetzungen.csv", TRANSLATION_HEADERS
    )
    errors: list[CatalogImportErrorV1] = []
    warnings: list[str] = []

    translations: dict[str, list[ParsedTranslation]] = {}
    translation_keys: set[tuple[str, str]] = set()
    for row_number, row in enumerate(translation_rows, start=2):
        item_number = row["Artikelnr."]
        language_code = row["Sprachcode"].upper()
        if not item_number or not language_code:
            errors.append(
                CatalogImportErrorV1(
                    row=row_number,
                    code="missing_translation_identifier",
                    message="Translation rows require Artikelnr. and Sprachcode.",
                )
            )
            continue
        key = (item_number, language_code)
        if key in translation_keys:
            errors.append(
                CatalogImportErrorV1(
                    row=row_number,
                    code="duplicate_translation",
                    message=f"Duplicate translation for {item_number}/{language_code}.",
                )
            )
            continue
        translation_keys.add(key)
        locale = LANGUAGE_MAP.get(language_code, language_code.casefold())
        if language_code not in LANGUAGE_MAP:
            warnings.append(f"Unknown language code preserved: {language_code}")
        description = row["Beschreibung"]
        description_2 = row["Beschreibung 2"]
        content_hash = stable_json_hash(
            {
                "language_code": language_code,
                "description": description,
                "description_2": description_2,
            }
        )
        translations.setdefault(item_number, []).append(
            ParsedTranslation(
                raw_language_code=language_code,
                locale=locale,
                description=description,
                description_2=description_2,
                content_hash=content_hash,
            )
        )

    items: list[ParsedCatalogItem] = []
    item_numbers: set[str] = set()
    for row_number, row in enumerate(article_rows, start=2):
        item_number = row["Nr."]
        if not item_number:
            errors.append(
                CatalogImportErrorV1(
                    row=row_number,
                    field="Nr.",
                    code="missing_item_number",
                    message="Every catalog row requires Nr.",
                )
            )
            continue
        if item_number in item_numbers:
            errors.append(
                CatalogImportErrorV1(
                    row=row_number,
                    field="Nr.",
                    code="duplicate_item_number",
                    message=f"Duplicate article number: {item_number}",
                )
            )
            continue
        item_numbers.add(item_number)
        try:
            on_hand = _quantity(row["Lagerbestand"], row=row_number, field="Lagerbestand")
            incoming = _quantity(
                row["Menge in Bestellung"], row=row_number, field="Menge in Bestellung"
            )
            committed = _quantity(
                row["Menge in Auftrag"], row=row_number, field="Menge in Auftrag"
            )
        except CatalogImportValidationError as exc:
            errors.extend(exc.errors)
            continue

        item_translations = tuple(
            sorted(
                translations.get(item_number, ()),
                key=lambda value: (
                    value.locale,
                    value.raw_language_code,
                    value.description,
                    value.description_2,
                ),
            )
        )
        descriptions = _unique_texts(
            [
                row["Beschreibung"],
                row["Beschreibung 2"],
                *[
                    value
                    for translation in item_translations
                    for value in (translation.description, translation.description_2)
                ],
            ]
        )
        category_code = row["Artikelkategoriencode"]
        domain = _domain(item_number, category_code)
        # Business Central base/master records have a 000 suffix and no parent number.
        # They describe a family, but they are not offerable inventory variants.
        master_item = item_number.endswith("000") and not row["Nummer 2"]
        matching_eligible = bool(
            descriptions and category_code[:1] in {"2", "4"} and not master_item
        )
        canonical_text = _canonical_text(
            descriptions,
            category_code=category_code,
            base_unit=row["Basiseinheit"],
        )
        content_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        items.append(
            ParsedCatalogItem(
                item_number=item_number,
                domain=domain,
                family_id=row["Nummer 2"] or None,
                descriptions=descriptions,
                translations=item_translations,
                base_unit=row["Basiseinheit"],
                category_code=category_code,
                t1=row["Zollware (T1)"].casefold() == "ja",
                replenishment_method=row["Wiederbeschaffungsverfahren"],
                on_hand=on_hand,
                incoming_purchase_order=incoming,
                committed_order=committed,
                master_item=master_item,
                matching_eligible=matching_eligible,
                canonical_text=canonical_text,
                content_hash=content_hash,
                record_hash=stable_json_hash(
                    {
                        "content_hash": content_hash,
                        "descriptions": descriptions,
                        "category_code": category_code,
                        "base_unit": row["Basiseinheit"],
                        "family_id": row["Nummer 2"] or None,
                        "replenishment_method": row["Wiederbeschaffungsverfahren"],
                        "t1": row["Zollware (T1)"].casefold() == "ja",
                        "master_item": master_item,
                    }
                ),
            )
        )

    orphaned = sorted(set(translations) - item_numbers)
    for item_number in orphaned:
        errors.append(
            CatalogImportErrorV1(
                code="orphan_translation",
                message=f"Translation references unknown article number {item_number}.",
            )
        )
    if errors:
        raise CatalogImportValidationError(errors)
    if not items:
        raise CatalogImportValidationError(
            [CatalogImportErrorV1(code="empty_catalog", message="The catalog contains no rows.")]
        )

    return ParsedCatalogImport(
        items=tuple(items),
        article_checksum=hashlib.sha256(article_data).hexdigest(),
        translation_checksum=hashlib.sha256(translation_data).hexdigest(),
        warnings=tuple(dict.fromkeys(warnings)),
    )
