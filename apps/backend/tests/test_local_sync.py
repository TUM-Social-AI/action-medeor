import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql.elements import TextClause

from app.sharepoint import local_sync, run_status


@pytest.fixture
async def recorded_local_sync(monkeypatch):
    state = SimpleNamespace(locked=True, active=None, added=[], committed=[], updates=[])

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def scalar(self, statement, params=None):
            if isinstance(statement, TextClause):
                assert params == {"key": "local-sharepoint-sync:sync-job"}
                return state.locked
            return state.active

        def add(self, row):
            state.added.append(row)

        async def commit(self):
            state.committed[:] = state.added

    async def update(run_id, **values):
        assert any(row.id == run_id for row in state.committed)
        state.updates.append(values)

    async def unexpected_begin(_job_name):
        pytest.fail("The backend must reuse the committed reservation")

    monkeypatch.setattr(local_sync, "async_session", Session)
    monkeypatch.setattr(run_status, "update_run", update)
    monkeypatch.setattr(run_status, "begin_run", unexpected_begin)
    yield state
    await local_sync.stop_local_syncs()


async def test_local_sync_commits_progress_before_running_and_rejects_duplicates(
    recorded_local_sync, monkeypatch,
):
    state = recorded_local_sync
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation(command, api_url):
        assert command == "sync"
        assert api_url == ""
        assert state.committed[-1].status == "running"
        entered.set()
        await release.wait()
        return {"processed": 2, "failed": 0}

    monkeypatch.setattr(local_sync, "run_command", operation)
    execution_name = await local_sync.start_local_sync("sync-job")
    row = state.committed[0]
    assert row.execution_name == execution_name
    assert execution_name.startswith("local-")
    assert row.status == "running"
    await asyncio.wait_for(entered.wait(), timeout=1)
    task = local_sync._tasks["sync-job"]
    with pytest.raises(local_sync.SyncAlreadyRunning):
        await local_sync.start_local_sync("sync-job")
    assert len(state.committed) == 1
    release.set()
    await asyncio.wait_for(task, timeout=1)
    assert state.updates[-1]["status"] == "completed"
    assert state.updates[-1]["summary"]["processed"] == 2
    await local_sync.start_local_sync("sync-job")
    await asyncio.wait_for(local_sync._tasks["sync-job"], timeout=1)
    assert len(state.committed) == 2
    assert state.updates[-1]["status"] == "completed"


@pytest.mark.parametrize("blocked", ["lock", "active"])
async def test_database_reservation_blocks_other_backend_processes(recorded_local_sync, blocked):
    state = recorded_local_sync
    state.locked = blocked != "lock"
    state.active = uuid4() if blocked == "active" else None
    with pytest.raises(local_sync.SyncAlreadyRunning):
        await local_sync.start_local_sync("sync-job")
    assert state.committed == []


async def test_local_sync_failures_are_reported_without_leaking_details(
    recorded_local_sync, monkeypatch, caplog,
):
    async def operation(*_args):
        raise RuntimeError("private-secret-and-document-url")

    monkeypatch.setattr(local_sync, "run_command", operation)
    await local_sync.start_local_sync("sync-job")
    await asyncio.wait_for(local_sync._tasks["sync-job"], timeout=1)
    assert recorded_local_sync.updates[-1]["status"] == "failed"
    assert "private-secret" not in str(recorded_local_sync.updates)
    assert "private-secret" not in caplog.text


async def test_backend_shutdown_cancels_local_sync_and_records_interruption(
    recorded_local_sync, monkeypatch,
):
    entered = asyncio.Event()

    async def operation(*_args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(local_sync, "run_command", operation)
    await local_sync.start_local_sync("sync-job")
    await asyncio.wait_for(entered.wait(), timeout=1)
    await local_sync.stop_local_syncs()
    assert local_sync._tasks == {}
    assert recorded_local_sync.updates[-1]["status"] == "failed"
    assert "interrupted" in recorded_local_sync.updates[-1]["message"]
