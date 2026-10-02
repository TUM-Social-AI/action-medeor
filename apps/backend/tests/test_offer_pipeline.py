from dataclasses import replace
from datetime import UTC, date, datetime

import httpx
import pytest

from app.core.config import Settings
from app.offers.dates import resolve_validity
from app.offers.embeddings import represent_offer
from app.offers.extraction import ExtractedOffer, OfferExtraction
from app.sharepoint.changes import Item, SharePointChange, parse_item
from app.sharepoint.extraction import (
    DownloadedDocument,
    ExtractionFailure,
    UnsupportedDocument,
    normalize,
)
from app.sharepoint.graph import GraphClient
from app.sharepoint.scope import assign_domains, content_version, domain_folders, supported


def item(name="offer.pdf", item_id="file", parent_id="equipment", domain="equipment"):
    return Item(
        item_id,
        parent_id,
        name,
        name,
        "https://example.sharepoint.com/offer",
        "e1",
        "c1",
        datetime(2026, 10, 2, tzinfo=UTC),
        100,
        "application/pdf",
        False,
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
        domain=domain,
    )


def offered(**overrides):
    data = dict(
        source_id="Sheet!A2:supplier1",
        alternative_index=1,
        supplier="Supplier A",
        item_description="Sterile catheter 12 Fr",
        offer_reference=None,
        offer_date=None,
        date_kind=None,
        valid_until=None,
        validity_text="gültig 14 Tage",
        price_text="50 €/100 Stück",
        price_amount="50",
        currency="EUR",
        price_basis="100 Stück",
        price_conflict=False,
        evidence=[
            {"field": "supplier", "location": "Sheet!A2", "excerpt": "Supplier A"},
            {
                "field": "item_description",
                "location": "Sheet!B2",
                "excerpt": "Sterile catheter 12 Fr",
            },
        ],
        warnings=[],
    )
    return ExtractedOffer(**(data | overrides))


def batch_result(offers=None, **kwargs):
    return OfferExtraction(
        offers=offers if offers is not None else [offered()],
        chunks_attempted=1,
        chunks_succeeded=1,
        **kwargs,
    )


def normalize_result(result, source=None):
    source = source or item()
    return normalize(
        SharePointChange("new", source),
        DownloadedDocument(
            source.item_id,
            source.name,
            source.mime_type,
            b"content",
            source.modified_at,
            source.created_at,
        ),
        result,
    )


@pytest.mark.parametrize(
    ("wording", "anchor", "expected"),
    [
        ("In 14 Tagen", date(2026, 10, 2), date(2026, 10, 16)),
        ("Offer valid for 2 weeks from issue", date(2026, 10, 2), date(2026, 10, 16)),
        ("Gültigkeit: 1 Monat", date(2026, 1, 31), date(2026, 2, 28)),
        ("Valid 1 year", date(2024, 2, 29), date(2025, 2, 28)),
        ("Valid for 0 days", date(2026, 10, 2), date(2026, 10, 2)),
        ("valid 14 business days", date(2026, 10, 2), None),
        ("gültig 14 Tage ab Erhalt", date(2026, 10, 2), None),
        ("Delivery in 14 days", date(2026, 10, 2), None),
        ("Product expiry in 14 days", date(2026, 10, 2), None),
        ("Shelf life: 2 years", date(2026, 10, 2), None),
        ("Valid 14 days from today", date(2026, 10, 2), None),
        ("Valid 14 days after approval", date(2026, 10, 2), None),
        ("Valid 14 days from the date of issue.", date(2026, 10, 2), date(2026, 10, 16)),
        ("Bindefrist 14 Tage ab Angebotsdatum", date(2026, 10, 2), date(2026, 10, 16)),
        ("Not valid for 14 days", date(2026, 10, 2), None),
        ("Valid 14 or 30 days", date(2026, 10, 2), None),
        ("Valid 14 days", None, None),
        ("Valid 999999999 years", date(2026, 10, 2), None),
    ],
)
def test_relative_validity(wording, anchor, expected):
    actual, source, warnings = resolve_validity(None, wording, anchor)
    assert actual == expected
    assert bool(warnings) == (expected is None)
    assert source == ("relative" if expected else None)


def test_explicit_validity_takes_precedence():
    assert resolve_validity(date(2026, 12, 1), "14 days", None) == (
        date(2026, 12, 1),
        "explicit",
        [],
    )


def test_creation_fallback_and_price_remain_literal():
    offer = normalize_result(batch_result()).offers[0]
    assert offer.offer_date == datetime(2026, 10, 2, tzinfo=UTC)
    assert offer.valid_until == date(2026, 10, 16)
    assert offer.metadata["offer_date_source"] == "sharepoint_created"
    assert offer.metadata["offer_validity_source"] == "relative_sharepoint_created"
    assert str(offer.price) == "50" and offer.price_basis == "100 Stück"
    assert offer.unit_price is None and offer.metadata["matching_eligible"]


def test_document_date_precedes_metadata_and_uses_berlin_calendar():
    offer = normalize_result(batch_result([offered(offer_date=date(2026, 3, 28))])).offers[0]
    assert offer.offer_date.date() == date(2026, 3, 28)
    assert offer.valid_until == date(2026, 4, 11)
    assert offer.metadata["offer_validity_source"] == "relative_document"


def test_missing_creation_does_not_use_modified_or_current_date():
    offer = normalize_result(batch_result(), replace(item(), created_at=None)).offers[0]
    assert offer.offer_date is None and offer.valid_until is None
    assert offer.metadata["offer_date_source"] is None


def test_blocks_alternatives_conflicts_and_review_eligibility():
    records = [
        offered(),
        offered(alternative_index=2, price_conflict=True),
        offered(source_id="Sheet!A2:supplier2", supplier="Supplier B"),
        offered(source_id="Sheet!A3:supplier1", supplier=None),
        offered(source_id="Sheet!A4:supplier1", evidence=[]),
        offered(
            source_id="Sheet!A5:supplier1",
            warnings=["Unverified source evidence: supplier at Sheet!A5"],
        ),
    ]
    result = normalize_result(batch_result(records)).offers
    assert len(result) == 6
    assert [o.supplier for o in result[:3]] == ["Supplier A", "Supplier A", "Supplier B"]
    assert result[1].price is None and result[1].metadata["price_conflict"]
    assert all(not o.metadata["matching_eligible"] for o in result[3:])


def test_partial_failures_and_scans_do_not_publish_partial_batches():
    with pytest.raises(ExtractionFailure, match="chunk failed"):
        normalize_result(batch_result(failures=["chunk failed"]))
    with pytest.raises(UnsupportedDocument, match="unsupported"):
        normalize_result(batch_result(warnings=["page:2: scanned/empty page unsupported"]))
    assert normalize_result(batch_result([])).offers == []


def test_missing_product_is_retained_for_review_without_failing_the_document():
    offer = normalize_result(batch_result([offered(item_description="")])).offers[0]
    assert offer.offered_description is None
    assert not offer.metadata["matching_eligible"]
    assert offer.raw_request_text.startswith("Unidentified offered item")


@pytest.mark.parametrize("name", ["message.eml", "MESSAGE.EML", "~$offers.xlsx", "offer.docx"])
def test_files_ignored_before_download(name):
    assert not supported(item(name))


def test_domains_are_explicit_and_optional_until_uploaded():
    settings = Settings(_env_file=None, sharepoint_equipment_folder_id="equipment")
    root = replace(item(item_id="root", parent_id=None), is_folder=True)
    folder = replace(item(item_id="equipment", parent_id="root"), is_folder=True)
    other = replace(item(item_id="partner", parent_id="root"), is_folder=True)
    docs = {
        "root": root,
        "equipment": folder,
        "file": item(),
        "partner": other,
        "request": item(item_id="request", parent_id="partner", domain=None),
    }
    result = assign_domains(docs, "root", domain_folders(settings))
    assert result["file"].domain == "equipment" and result["request"].domain is None
    with pytest.raises(ValueError, match="immediate"):
        assign_domains(docs, "root", {"partner-request": "medicine"})


def test_created_timestamp_is_preserved_and_metadata_rename_is_not_content_change():
    parsed = parse_item(
        {"id": "file", "name": "offer.pdf", "file": {}, "createdDateTime": "2026-01-01T23:30:00Z"}
    )
    assert parsed.created_at == datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    assert content_version(item()) == content_version(
        replace(item(), name="renamed.pdf", etag="e2")
    )
    assert content_version(item()) != content_version(replace(item(), domain="medicine"))
    assert represent_offer("Sterile catheter", "equipment") != represent_offer(
        "Sterile catheter", "medicine"
    )


@pytest.mark.asyncio
async def test_download_byte_limit_stops_oversized_content():
    class Token:
        async def get_token(self):
            return "test"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"too many bytes"),
        )
    ) as client:
        with pytest.raises(ValueError, match="byte limit"):
            await GraphClient("drive", Token(), client).download("file", max_bytes=3)
