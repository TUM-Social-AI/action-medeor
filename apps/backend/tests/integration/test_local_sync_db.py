"""Development fetches reserve a run before returning and share progress with the API."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.catalogue_fetch import router
from app.core.config import Settings, get_settings
from app.db.models import SharePointSyncRunRow
from app.db.session import get_session
from app.sharepoint import local_sync, run_status

pytestmark = pytest.mark.integration


async def test_local_fetch_commits_progress_and_accepts_only_one_concurrent_start(monkeypatch):
    url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job_name = "local-sync-test-" + uuid4().hex
    release = asyncio.Event()
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    monkeypatch.setattr(local_sync, "async_session", sessions)
    monkeypatch.setattr(run_status, "async_session", sessions)

    async def operation(command, api_url):
        assert command == "sync"
        await release.wait()
        return {"processed": 2, "failed": 0}

    monkeypatch.setattr(local_sync, "run_command", operation)

    async def settings():
        return Settings(
            _env_file=None, app_env="development",
            azure_sharepoint_job_resource_id="/jobs/" + job_name,
            sharepoint_tenant_id="tenant", sharepoint_client_id="client",
            sharepoint_client_secret="secret", sharepoint_drive_id="drive",
            sharepoint_root_folder_id="root",
        )

    async def session():
        async with sessions() as value:
            yield value

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = settings
    app.dependency_overrides[get_session] = session
    headers = {"origin": "http://localhost:5173", "x-catalogue-fetch": "true"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000",
        ) as client:
            responses = await asyncio.gather(*[
                client.post("/api/v1/catalogue/fetch", headers=headers) for _ in range(2)
            ])
            assert sorted(response.status_code for response in responses) == [202, 409]
            accepted = next(response.json() for response in responses if response.status_code == 202)
            response = await client.get("/api/v1/catalogue/fetch/status")
            assert response.status_code == 200
            running = response.json()["runs"]
            assert len(running) == 1
            assert running[0]["status"] == "running"
            assert running[0]["execution_name"] == accepted["execution_name"]
            task = local_sync._tasks[job_name]
            release.set()
            await asyncio.wait_for(task, timeout=5)
            response = await client.get("/api/v1/catalogue/fetch/status")
            completed = response.json()["runs"][0]
            assert completed["id"] == running[0]["id"]
            assert completed["status"] == "completed"
            assert completed["summary"]["processed"] == 2

            # A run owned by a different backend process must also prevent another start.
            async with sessions() as value:
                value.add(SharePointSyncRunRow(
                    id=uuid4(), job_name=job_name, execution_name="other-process",
                    status="running", summary={},
                ))
                await value.commit()
            assert (await client.post("/api/v1/catalogue/fetch", headers=headers)).status_code == 409
    finally:
        await local_sync.stop_local_syncs()
        async with sessions() as value:
            await value.execute(delete(SharePointSyncRunRow).where(
                SharePointSyncRunRow.job_name == job_name,
            ))
            await value.commit()
        await engine.dispose()
