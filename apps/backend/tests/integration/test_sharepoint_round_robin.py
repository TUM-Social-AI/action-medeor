"""Real PostgreSQL queue turns and checkpoints, with local workbooks and a controlled model."""

import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.jobs import sharepoint_sync
from app.parsing.llm_client import LlmUnavailable
from app.sharepoint import extraction, processing
from app.sharepoint.changes import SharePointChange
from app.sharepoint.extraction import DownloadedDocument, normalize
from tests.test_offer_extraction import workbook_bytes
from tests.test_offer_pipeline import batch_result, item, offered

pytestmark = pytest.mark.integration


@pytest.fixture
async def queue(monkeypatch):
    url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    drive = "round-robin-" + uuid4().hex

    class Queue:
        drive_id = drive
        settings = Settings(
            _env_file=None,
            sharepoint_equipment_folder_id="equipment",
            sharepoint_max_documents_per_run=5,
            sharepoint_max_extraction_chunks=32,
        )
        sources = {}
        documents = {}
        requests = []
        fail_once = set()

        async def seed(self, sizes):
            async with sessions() as session:
                for key, chunks in sizes.items():
                    source = item(name=f"{key}.xlsx", item_id=f"{drive}-{key}")
                    self.sources[key] = source
                    self.documents[source.item_id] = workbook_bytes(
                        {
                            "Offers": [["Supplier I", "Item offered"]]
                            + [["Supplier A", f"{key} product {n}"] for n in range(chunks * 24)]
                        }
                    )
                    await processing.enqueue(session, drive, "root", source)
                await session.commit()

        async def rediscover(self):
            async with sessions() as session:
                for source in self.sources.values():
                    await processing.enqueue(session, drive, "root", source)
                await session.commit()

        async def state(self, key):
            async with sessions() as session:
                return (
                    (
                        await session.execute(
                            text("""
                    SELECT * FROM sharepoint_offer_jobs WHERE drive_id=:drive AND item_id=:item
                """),
                            {"drive": drive, "item": self.sources[key].item_id},
                        )
                    )
                    .mappings()
                    .one()
                )

        async def descriptions(self, key):
            async with sessions() as session:
                return list(
                    (
                        await session.execute(
                            text("""
                    SELECT offered_description FROM historical_offers
                    WHERE source_drive_id=:drive AND source_item_id=:item AND is_current AND active
                """),
                            {"drive": drive, "item": self.sources[key].item_id},
                        )
                    ).scalars()
                )

        async def previous_offers(self, key):
            previous = replace(self.sources[key], ctag="previous")
            async with sessions() as session:
                await processing.enqueue(session, drive, "root", previous)
                await session.commit()
                job = await processing.claim(
                    session, drive, "root", self.settings, previous.item_id
                )
                await processing.publish(
                    session,
                    job,
                    normalize(
                        SharePointChange("new", previous),
                        DownloadedDocument(previous.item_id, previous.name, None, b"old", None),
                        batch_result([offered(item_description="Previous successful offer")]),
                    ),
                )
            await self.rediscover()

        async def download(self, item_id, **kwargs):
            return self.documents[item_id]

        async def resolve(self, graph, folder, item_id, folders):
            return next(source for source in self.sources.values() if source.item_id == item_id)

        def model(self, prompt, schema):
            row = json.loads(prompt.split("Document data:\n", 1)[1].splitlines()[1])
            number = row["row"]
            description = row["cells"][f"B{number}"]["value"]
            key = description.split()[0]
            identity = (key, number)
            self.requests.append(identity)
            if identity in self.fail_once:
                self.fail_once.remove(identity)
                raise LlmUnavailable("API timeout")
            return schema(
                offers=[
                    offered(
                        source_id=f"Offers!A{number}",
                        item_description=description,
                        evidence=[
                            {
                                "field": "supplier",
                                "location": f"Offers!A{number}",
                                "excerpt": "Supplier A",
                            },
                            {
                                "field": "item_description",
                                "location": f"Offers!B{number}",
                                "excerpt": description,
                            },
                        ],
                    )
                ],
                warnings=[],
            )

        async def run(self):
            return await processing.process_pending(self, "root", self.settings, sessions)

        def turns(self, result):
            reverse = {source.item_id: key for key, source in self.sources.items()}
            return [reverse[id] for id in result["attempted_item_ids"]]

    harness = Queue()
    original_extract = extraction.extract_offers

    def controlled(*args, **kwargs):
        return original_extract(*args, **kwargs, llm=harness.model)

    monkeypatch.setattr(processing, "resolve_item", harness.resolve)
    monkeypatch.setattr(extraction, "extract_offers", controlled)
    harness.sessions = sessions
    try:
        yield harness
    finally:
        async with sessions() as session:
            await session.execute(
                text("DELETE FROM historical_offers WHERE source_drive_id=:drive"), {"drive": drive}
            )
            await session.execute(
                text("DELETE FROM sharepoint_offer_files WHERE external_id LIKE :prefix"),
                {"prefix": drive + "%"},
            )
            await session.execute(
                text("DELETE FROM source_snapshots WHERE document_id LIKE :prefix"),
                {"prefix": drive + "%"},
            )
            await session.execute(
                text("DELETE FROM sharepoint_offer_jobs WHERE drive_id=:drive"), {"drive": drive}
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.parametrize(
    ("sizes", "turns", "deferred"),
    [
        ({"A": 39}, ["A", "A"], 0),
        ({"A": 33, "B": 33, "C": 33, "D": 33, "E": 33}, ["A", "B", "C", "D", "E"], 5),
        ({"A": 65, "B": 1, "C": 1}, ["A", "B", "C", "A", "A"], 0),
    ],
)
async def test_round_robin_gives_other_documents_their_turn_before_continuation(
    queue, sizes, turns, deferred
):
    await queue.seed(sizes)
    result = await queue.run()
    assert queue.turns(result) == turns
    assert result["turns"] == len(turns) and result["deferred"] == deferred
    assert result["failed"] == 0
    assert len(queue.requests) == len(set(queue.requests))
    for key in sizes:
        state = await queue.state(key)
        assert state["status"] == ("pending" if deferred else "completed")
        assert state["attempts"] == (0 if deferred else 1)


async def test_huge_file_stops_after_five_turns_and_resumes_without_republishing_partial_data(
    queue,
):
    await queue.seed({"A": 193})
    await queue.previous_offers("A")
    first = await queue.run()
    assert first["turns"] == 5 and first["deferred"] == 1 and first["processed"] == 0
    assert len(queue.requests) == 160
    state = await queue.state("A")
    assert state["attempts"] == 0 and state["next_attempt_at"] is None
    assert await queue.descriptions("A") == ["Previous successful offer"]
    await queue.rediscover()
    assert (await queue.state("A"))["updated_at"] == state["updated_at"]
    assert (await queue.state("A"))["result_json"] == state["result_json"]
    second = await queue.run()
    assert second["turns"] == 2 and second["deferred"] == 0 and second["processed"] == 1
    assert len(queue.requests) == len(set(queue.requests)) == 193
    assert len(await queue.descriptions("A")) == 193
    assert "Previous successful offer" not in await queue.descriptions("A")
    assert (await queue.state("A"))["attempts"] == 1


async def test_rediscovery_does_not_move_unvisited_documents_behind_a_paused_document(queue):
    await queue.seed({"A": 33, "B": 1, "C": 1})
    queue.settings.sharepoint_max_documents_per_run = 1
    first = await queue.run()
    assert queue.turns(first) == ["A"] and first["deferred"] == 1
    before = {key: (await queue.state(key))["updated_at"] for key in queue.sources}
    await queue.rediscover()
    assert {key: (await queue.state(key))["updated_at"] for key in queue.sources} == before
    queue.settings.sharepoint_max_documents_per_run = 5
    second = await queue.run()
    assert queue.turns(second) == ["B", "C", "A"]
    assert second["deferred"] == 0 and len(queue.requests) == 35


async def test_api_failure_keeps_backoff_and_retries_only_the_missing_chunk(queue):
    await queue.seed({"A": 3, "B": 1})
    queue.fail_once.add(("A", 26))
    first = await queue.run()
    assert queue.turns(first) == ["A", "B"]
    assert first["failed"] == 1 and first["deferred"] == 0
    state = await queue.state("A")
    assert state["status"] == "failed" and state["next_attempt_at"] > state["updated_at"]
    assert len(state["result_json"]["checkpoint"]["chunks"]) == 2
    await queue.rediscover()
    assert (await queue.state("A"))["error"] == state["error"]
    async with queue.sessions() as session:
        await session.execute(
            text("UPDATE sharepoint_offer_jobs SET next_attempt_at=NULL WHERE item_id=:item"),
            {"item": queue.sources["A"].item_id},
        )
        await session.commit()
    second = await queue.run()
    assert second["processed"] == 1 and second["failed"] == second["deferred"] == 0
    assert queue.requests == [("A", 2), ("A", 26), ("A", 50), ("B", 2), ("A", 26)]
    assert (await queue.state("A"))["attempts"] == 2


async def test_actual_failures_still_stop_after_three_attempts(queue):
    await queue.seed({"A": 1})
    for attempt in range(1, 4):
        queue.fail_once.add(("A", 2))
        result = await queue.run()
        assert result["turns"] == result["failed"] == 1 and result["deferred"] == 0
        assert (await queue.state("A"))["attempts"] == attempt
        async with queue.sessions() as session:
            await session.execute(
                text("UPDATE sharepoint_offer_jobs SET next_attempt_at=NULL WHERE item_id=:item"),
                {"item": queue.sources["A"].item_id},
            )
            await session.commit()
        await queue.rediscover()
    result = await queue.run()
    assert result["turns"] == 0 and len(queue.requests) == 3
    assert (await queue.state("A"))["status"] == "failed"


async def test_oversized_files_are_unsupported_and_do_not_take_repeated_turns(queue):
    await queue.seed({"A": 1})
    queue.settings.sharepoint_max_document_bytes = 5
    result = await queue.run()
    assert result["turns"] == result["failed"] == 1 and result["deferred"] == 0
    assert (await queue.state("A"))["status"] == "unsupported"
    assert queue.requests == []


async def test_process_one_does_not_embed_or_match_until_its_continuation_completes(
    queue, monkeypatch
):
    await queue.seed({"A": 39})
    embeddings, matches = [], []

    async def embed(*args, **kwargs):
        embeddings.append(kwargs["item_id"])
        return []

    async def match(*args):
        matches.append(args[2])
        return {"verified": True}

    monkeypatch.setattr(sharepoint_sync, "resolve_item", queue.resolve)
    monkeypatch.setattr(sharepoint_sync, "async_session", queue.sessions)
    monkeypatch.setattr(sharepoint_sync, "embed_pending", embed)
    monkeypatch.setattr(sharepoint_sync, "verify_matching", match)
    source_id = queue.sources["A"].item_id
    first = await sharepoint_sync.process_one(queue, "root", source_id, queue.settings)
    assert first["status"] == "pending" and first["turns"] == first["deferred"] == 1
    assert embeddings == matches == []
    second = await sharepoint_sync.process_one(queue, "root", source_id, queue.settings)
    assert second["status"] == "completed" and second["turns"] == 1 and second["deferred"] == 0
    assert embeddings == matches == [source_id]
    assert len(queue.requests) == 39


@pytest.mark.parametrize("reason", ["content", "extraction", "expired", "archived"])
async def test_checkpoint_and_pause_are_fenced_from_superseded_or_expired_workers(
    queue, monkeypatch, reason
):
    await queue.seed({"A": 1})
    source = queue.sources["A"]
    async with queue.sessions() as session:
        job = await processing.claim(session, queue.drive_id, "root", queue.settings)
        await processing.save_checkpoint(
            session, job, "fingerprint", {"chunk": {"offers": [], "warnings": []}}
        )
        if reason == "content":
            await processing.enqueue(
                session, queue.drive_id, "root", replace(source, ctag="changed")
            )
        elif reason == "extraction":
            monkeypatch.setattr(processing, "EXTRACTION_VERSION", "next-version")
            await processing.enqueue(session, queue.drive_id, "root", source)
        elif reason == "archived":
            await processing.archive_file(session, queue.drive_id, "root", source.item_id)
        else:
            await session.execute(
                text(
                    "UPDATE sharepoint_offer_jobs SET lease_until=now()-interval '1 second' WHERE item_id=:item"
                ),
                {"item": source.item_id},
            )
        await session.commit()
        with pytest.raises(RuntimeError, match="checkpoint discarded"):
            await processing.save_checkpoint(session, job, "fingerprint", {"stale": {}})
        await session.rollback()
        assert not await processing.defer(session, job)
    if reason in ("content", "extraction"):
        assert (await queue.state("A"))["result_json"] is None
    else:
        assert "stale" not in (await queue.state("A"))["result_json"]["checkpoint"]["chunks"]


@pytest.mark.parametrize(
    ("error", "reset"),
    [
        ("ExtractionFailure: Document needs 39 chunks; limit is 32", True),
        ("ExtractionFailure: Chunk 1: API timeout", False),
    ],
)
async def test_only_legacy_whole_document_chunk_limit_failures_are_automatically_requeued(
    queue, error, reset
):
    await queue.seed({"A": 1})
    async with queue.sessions() as session:
        await session.execute(
            text("""
            UPDATE sharepoint_offer_jobs SET status='failed',attempts=3,error=:error,
                next_attempt_at=now()+interval '1 day' WHERE item_id=:item
        """),
            {"item": queue.sources["A"].item_id, "error": error},
        )
        await session.commit()
    await queue.rediscover()
    state = await queue.state("A")
    assert state["status"] == ("pending" if reset else "failed")
    assert state["attempts"] == (0 if reset else 3)
    assert (state["next_attempt_at"] is None) == reset
    assert state["error"] == (None if reset else error)
