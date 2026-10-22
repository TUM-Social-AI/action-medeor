"""Time budgets and cancellation across the async adapter's worker boundary."""

import asyncio
import threading

import pytest

from app.offers.extraction import _LlmResult, extract_offers
from app.sharepoint import extraction
from app.sharepoint.changes import SharePointChange
from app.sharepoint.extraction import DownloadedDocument, ExtractionDeferred, ExtractionFailure
from tests.test_offer_extraction import offer, workbook_bytes
from tests.test_offer_pipeline import item


def document():
    source = item(name="offers.xlsx")
    content = workbook_bytes(
        {
            "Offers": [["Supplier I", "Item offered"]]
            + [["Supplier A", "Needle 19G"] for _ in range(80)]
        }
    )
    return SharePointChange("new", source), DownloadedDocument(
        source.item_id,
        source.name,
        source.mime_type,
        content,
        None,
    )


async def test_soft_deadline_reserves_70_seconds_and_resumes(monkeypatch):
    change, downloaded = document()
    clock, calls = [0], []
    checkpoint = {"chunks": {}}

    def controlled(*args, **kwargs):
        def model(*args):
            calls.append(True)
            return _LlmResult(offers=[offer()], warnings=[])

        return extract_offers(*args, **kwargs, llm=model)

    async def save(fingerprint, chunks):
        checkpoint["fingerprint"] = fingerprint
        checkpoint["chunks"].update(chunks)
        if len(checkpoint["chunks"]) == 1:
            clock[0] = 51

    monkeypatch.setattr(extraction, "monotonic", lambda: clock[0])
    monkeypatch.setattr(extraction, "extract_offers", controlled)
    with pytest.raises(ExtractionDeferred, match="1/4 chunks"):
        await extraction.extract(change, downloaded, save_checkpoint=save, time_budget_seconds=120)
    assert len(calls) == 1 and len(checkpoint["chunks"]) == 1
    complete = await extraction.extract(
        change, downloaded, checkpoint=checkpoint, save_checkpoint=save, time_budget_seconds=120
    )
    assert len(calls) == 4 and complete.extraction.chunks_remaining == 0


async def test_preparation_exhausting_budget_fails_without_a_model_request(monkeypatch):
    def controlled(*args, **kwargs):
        return extract_offers(*args, **kwargs, llm=lambda *_: pytest.fail("No request budget"))

    monkeypatch.setattr(extraction, "extract_offers", controlled)
    with pytest.raises(ExtractionFailure, match="No new chunk"):
        await extraction.extract(*document(), time_budget_seconds=69)


async def test_cancellation_keeps_saved_chunk_and_stops_further_requests(monkeypatch):
    loop = asyncio.get_running_loop()
    second_request = asyncio.Event()
    release, worker_finished = threading.Event(), threading.Event()
    saved, calls = [], []

    def controlled(*args, **kwargs):
        def model(*args):
            calls.append(True)
            if len(calls) == 2:
                loop.call_soon_threadsafe(second_request.set)
                assert release.wait(timeout=5)
            return _LlmResult(offers=[offer()], warnings=[])

        try:
            return extract_offers(*args, **kwargs, llm=model)
        finally:
            worker_finished.set()

    async def save(fingerprint, chunks):
        saved.append(chunks)

    monkeypatch.setattr(extraction, "extract_offers", controlled)
    task = asyncio.create_task(extraction.extract(*document(), save_checkpoint=save))
    try:
        async with asyncio.timeout(5):
            await second_request.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert await asyncio.to_thread(worker_finished.wait, timeout=5)
    assert len(calls) == 2 and len(saved) == 1
