import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.catalogue_fetch import router
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.jobs import sharepoint_sync
from app.sharepoint import run_status


@pytest.fixture
def recorded(monkeypatch):
    events = []
    run_id = uuid4()

    async def begin(job_name):
        events.append(("begin", job_name))
        return run_id

    async def update(id, **values):
        assert id == run_id
        events.append(("update", values))

    monkeypatch.setattr(run_status, "begin_run", begin)
    monkeypatch.setattr(run_status, "update_run", update)
    return events


@pytest.mark.parametrize("result,status", [
    ({"processed": 2, "failed": 0, "embeddings": [{"embedded": 3, "failed": 0}]}, "completed"),
    ({"processed": 1, "failed": 1}, "failed"),
    ({"processed": 1, "failed": 0, "embeddings": [{"failed": 1}]}, "failed"),
    ({"skipped": "Another discovery is running", "processed": 0}, "skipped"),
    ({"processing_enabled": False, "processed": 0}, "completed"),
])
async def test_sync_reports_committed_start_then_terminal_summary(recorded, result, status):
    async def operation():
        assert recorded == [("begin", "sync-job")]
        return result

    assert await run_status.track_sync("sync-job", operation) is result
    terminal = recorded[-1][1]
    assert terminal["status"] == status
    assert terminal["finished_at"] is not None
    assert terminal["summary"]["processed"] == result.get("processed", 0)
    if status == "failed":
        assert terminal["message"]


@pytest.mark.parametrize("error", [RuntimeError("private-key-and-document-url"), asyncio.CancelledError()])
async def test_sync_records_failures_and_cancellation_without_leaking_errors(recorded, error):
    async def operation():
        raise error

    with pytest.raises(type(error)):
        await run_status.track_sync("sync-job", operation)
    assert recorded[-1][1]["status"] == "failed"
    assert "private-key" not in str(recorded)


async def test_sync_keeps_heartbeat_running_during_work_and_cancels_it_at_finish(recorded, monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def heartbeat(_id):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def operation():
        await entered.wait()
        return {"processed": 0}

    monkeypatch.setattr(run_status, "heartbeat", heartbeat)
    await run_status.track_sync("sync-job", operation)
    assert cancelled.is_set()


async def test_sync_entrypoint_tracks_configuration_errors_and_disposes_after_reporting(monkeypatch):
    events = []

    async def track(job_name, operation):
        assert job_name == "azure-sync-job"
        events.append("tracking")
        try:
            return await operation()
        except ValueError:
            events.append("failure recorded")
            raise

    async def operation(*args):
        raise ValueError("Missing configuration")

    async def dispose():
        events.append("disposed")

    monkeypatch.setenv("CONTAINER_APP_JOB_NAME", "azure-sync-job")
    monkeypatch.setattr(sharepoint_sync, "track_sync", track)
    monkeypatch.setattr(sharepoint_sync, "run_command", operation)
    monkeypatch.setattr(sharepoint_sync, "engine", SimpleNamespace(dispose=dispose))
    with pytest.raises(ValueError, match="Missing configuration"):
        await sharepoint_sync.run("sync", "unused")
    assert events == ["tracking", "failure recorded", "disposed"]


async def test_status_api_reads_only_and_marks_stale_without_changing_database():
    now = datetime.now(UTC)
    rows = [SimpleNamespace(
        id=uuid4(), execution_name="job-execution", status=status,
        started_at=now - timedelta(minutes=10), updated_at=now - timedelta(seconds=age),
        finished_at=None if status == "running" else now,
        summary={"processed": 2}, message=None,
    ) for status, age in [("running", 0), ("running", 600), ("completed", 0), ("failed", 0)]]
    calls = []

    class ReadSession:
        async def scalars(self, statement):
            calls.append(statement)
            assert statement.compile().params["job_name_1"] == "sync-job"
            return SimpleNamespace(all=lambda: rows)

    async def settings():
        return Settings(_env_file=None, app_env="production", azure_sharepoint_job_resource_id="/jobs/sync-job")

    async def session():
        return ReadSession()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = settings
    app.dependency_overrides[get_session] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        forbidden = await client.get("/api/v1/catalogue/fetch/status")
        assert forbidden.status_code == 401
        assert calls == []
        result = await client.get("/api/v1/catalogue/fetch/status", headers={"x-ms-client-principal-id": "user"})
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert [row["status"] for row in result.json()["runs"]] == ["running", "stale", "completed", "failed"]
    assert rows[1].status == "running"
    assert len(calls) == 1
