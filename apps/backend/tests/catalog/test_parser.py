from decimal import Decimal
from pathlib import Path

import pytest

from app.catalog.contracts import CatalogImportValidationError
from app.catalog.parser import parse_catalog_files

ARTICLE_HEADER = (
    "Nr.;Nummer 2;Beschreibung;Beschreibung 2;Basiseinheit;Artikelkategoriencode;"
    "Zollware (T1);Lagerbestand;Menge in Bestellung;Menge in Auftrag;"
    "Wiederbeschaffungsverfahren;Gesperrt;Verkauf gesperrt;Einkauf gesperrt\r\n"
)
TRANSLATION_HEADER = "Artikelnr.;Sprachcode;Beschreibung;Beschreibung 2\r\n"


def article_row(
    *,
    description: str = "Foley catheter CH18",
    on_hand: str = "1.187",
    incoming: str = "20",
    committed: str = "1.200",
    replenishment: str = "2",
) -> bytes:
    return (
        ARTICLE_HEADER + f"410001001;410001000;{description};;STÜCK;404;nein;"
        f"{on_hand};{incoming};{committed};{replenishment};nein;nein;nein\r\n"
    ).encode()


def translations(description: str = "Sonde de Foley CH18", language: str = "FRS") -> bytes:
    return (TRANSLATION_HEADER + f"410001001;{language};{description};;\r\n").encode()


def test_parser_preserves_identity_and_calculates_search_hash() -> None:
    parsed = parse_catalog_files(article_row(), translations())
    item = parsed.items[0]

    assert item.item_number == "410001001"
    assert item.domain == "equipment"
    assert item.on_hand == Decimal("1187")
    assert item.incoming_purchase_order == Decimal("20")
    assert item.committed_order == Decimal("1200")
    assert item.translations[0].locale == "fr"
    assert item.matching_eligible is True
    assert "sonde de foley ch18" in item.canonical_text


def test_quantity_only_change_reuses_text_hash_but_description_change_does_not() -> None:
    baseline = parse_catalog_files(article_row(on_hand="1"), translations()).items[0]
    quantity_change = parse_catalog_files(article_row(on_hand="999"), translations()).items[0]
    description_change = parse_catalog_files(
        article_row(description="Foley urinary catheter sterile CH18"), translations()
    ).items[0]

    assert quantity_change.content_hash == baseline.content_hash
    assert description_change.content_hash != baseline.content_hash


def test_non_text_metadata_change_versions_record_but_reuses_embedding_text() -> None:
    baseline = parse_catalog_files(article_row(replenishment="2"), translations()).items[0]
    metadata_change = parse_catalog_files(article_row(replenishment="4"), translations()).items[0]

    assert metadata_change.content_hash == baseline.content_hash
    assert metadata_change.record_hash != baseline.record_hash


def test_pseudo_item_is_retained_but_not_matching_eligible() -> None:
    data = (
        ARTICLE_HEADER + "99990;;Artikelnummer bei Anfragen;;STÜCK;;nein;0;0;0;0;nein;nein;nein\r\n"
    ).encode()
    parsed = parse_catalog_files(data, TRANSLATION_HEADER.encode())

    assert parsed.items[0].domain == "unknown"
    assert parsed.items[0].matching_eligible is False


def test_master_item_is_retained_but_only_variant_is_matching_eligible() -> None:
    data = (
        ARTICLE_HEADER
        + "201100000;;Lidocaine HCl 2% injection;;STÜCK;201;nein;0;0;0;0;nein;nein;nein\r\n"
        + "201100001;201100000;Lidocaine vial;;STÜCK;201;nein;10;0;0;2;nein;nein;nein\r\n"
    ).encode()
    parsed = parse_catalog_files(data, TRANSLATION_HEADER.encode())

    assert parsed.items[0].master_item is True
    assert parsed.items[0].matching_eligible is False
    assert parsed.items[1].master_item is False
    assert parsed.items[1].matching_eligible is True


def test_invalid_numeric_row_rejects_complete_import() -> None:
    with pytest.raises(CatalogImportValidationError) as exc_info:
        parse_catalog_files(article_row(on_hand="not-a-number"), translations())

    assert exc_info.value.errors[0].code == "invalid_quantity"


@pytest.mark.parametrize(
    "flag,expected",
    [("ja", True), (" JA ", True), ("nein", False), ("", False), ("unknown", False)],
)
def test_suspension_flags_default_to_unblocked_and_do_not_change_text(flag, expected) -> None:
    baseline = parse_catalog_files(article_row(), translations())
    data = article_row().replace(b";nein;nein;nein\r\n", f";{flag};{flag};{flag}\r\n".encode())
    parsed = parse_catalog_files(data, translations())
    value = parsed.items[0]
    assert (value.blocked, value.sales_blocked, value.purchasing_blocked) == (expected,) * 3
    assert value.content_hash == baseline.items[0].content_hash
    assert (value.record_hash != baseline.items[0].record_hash) is expected
    assert bool(parsed.warnings) is (flag == "unknown")


def test_old_export_headers_are_rejected() -> None:
    data = article_row().replace(b";Gesperrt;Verkauf gesperrt;Einkauf gesperrt", b"")
    with pytest.raises(CatalogImportValidationError) as exc:
        parse_catalog_files(data, translations())
    assert exc.value.errors[0].code == "missing_headers"
    assert "Gesperrt" in exc.value.errors[0].message


def test_two_digit_master_suffix_and_child_variant_with_parent() -> None:
    data = (
        ARTICLE_HEADER
        + "401108100;;Base article;;STÜCK;404;nein;0;0;0;2;nein;nein;nein\r\n"
        + "401108110;401108100;Variant;;STÜCK;404;nein;10;0;0;2;nein;nein;nein\r\n"
        + "401108200;401108100;Child with 00 suffix;;STÜCK;404;nein;10;0;0;2;nein;nein;nein\r\n"
    ).encode()
    parsed = parse_catalog_files(data, TRANSLATION_HEADER.encode())
    assert [value.master_item for value in parsed.items] == [True, False, False]
    assert [value.matching_eligible for value in parsed.items] == [False, True, True]


def test_supplied_updated_exports_parse_together() -> None:
    data = Path(__file__).resolve().parents[4] / "data"
    if not all(
        (data / name).exists() for name in ("Artikeldaten (2).csv", "Artikeluebersetzungen (2).csv")
    ):
        pytest.skip("Private ERP sample exports are not available")
    parsed = parse_catalog_files(
        (data / "Artikeldaten (2).csv").read_bytes(),
        (data / "Artikeluebersetzungen (2).csv").read_bytes(),
    )
    assert len(parsed.items) == 3576
    assert sum(value.blocked for value in parsed.items) == 10
    assert sum(value.master_item for value in parsed.items) == 1430
