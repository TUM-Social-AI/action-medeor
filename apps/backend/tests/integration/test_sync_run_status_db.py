"""Run status commits must be visible to independent readers before processing finishes."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.catalogue_fetch import router
from app.core.config import Settings, get_settings
from app.db.models import SharePointSyncRunRow
from app.db.session import get_session
from app.sharepoint import run_status

pytestmark = pytest.mark.integration


async def test_job_commits_running_heartbeat_and_completion_for_separate_api_session(monkeypatch):
    url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job_name = "status-test-" + uuid4().hex
    execution_name = job_name + "-execution"
    monkeypatch.setenv("CONTAINER_APP_JOB_EXECUTION_NAME", execution_name)
    monkeypatch.setattr(run_status, "async_session", sessions)
    monkeypatch.setattr(run_status, "HEARTBEAT_SECONDS", 0.02)
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation():
        entered.set()
        await release.wait()
        return {"processed": 2, "failed": 0, "processing_enabled": True,
                "embeddings": [{"embedded": 5, "failed": 0}]}

    async def settings():
        return Settings(_env_file=None, azure_sharepoint_job_resource_id="/jobs/" + job_name)

    async def session():
        async with sessions() as value:
            yield value

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = settings
    app.dependency_overrides[get_session] = session
    task = asyncio.create_task(run_status.track_sync(job_name, operation))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/catalogue/fetch/status")
            assert response.status_code == 200
            running = response.json()["runs"]
            assert len(running) == 1
            assert running[0]["status"] == "running"
            assert running[0]["finished_at"] is None
            assert running[0]["execution_name"] == execution_name
            assert not task.done()

            # Observe a heartbeat written by another session, with a bounded wait.
            for _ in range(50):
                await asyncio.sleep(0.02)
                response = await client.get("/api/v1/catalogue/fetch/status")
                if response.json()["runs"][0]["updated_at"] != running[0]["updated_at"]:
                    break
            else:
                pytest.fail("The running job did not commit its heartbeat")

            release.set()
            await asyncio.wait_for(task, timeout=5)
            response = await client.get("/api/v1/catalogue/fetch/status")
            completed = response.json()["runs"][0]
            assert completed["id"] == running[0]["id"]
            assert completed["status"] == "completed"
            assert completed["finished_at"] is not None
            assert completed["summary"] == {
                "processed": 2, "failed": 0, "processing_enabled": True,
                "embedded": 5, "embedding_failed": 0,
            }
            assert response.headers["cache-control"] == "no-store"

        # No web read changed the terminal record.
        async with sessions() as value:
            persisted = await value.scalar(select(SharePointSyncRunRow).where(
                SharePointSyncRunRow.job_name == job_name
            ))
            assert persisted.status == "completed"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        async with sessions() as value:
            await value.execute(delete(SharePointSyncRunRow).where(SharePointSyncRunRow.job_name == job_name))
            await value.commit()
        await engine.dispose()
