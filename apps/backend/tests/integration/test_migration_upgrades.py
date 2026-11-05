"""Rehearse releases in disposable databases, including both feature histories."""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def migration_database():
    target = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not target:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    # Never migrate or downgrade the caller's database. The configured test role
    # needs CREATEDB, as provided by the PostgreSQL service in CI.
    name = f"allocura_migration_{uuid4().hex}"
    admin = create_async_engine(target, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    url = make_url(target).set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield url, engine
        finally:
            await engine.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        await admin.dispose()


async def upgrade(url: str, revision: str = "head") -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", "upgrade", revision,
        cwd=BACKEND, env={**os.environ, "DATABASE_URL": url},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    assert process.returncode == 0, output.decode()


@pytest.mark.parametrize("starting_revision", [
    "base", "20261022_0001", "20261104_0001", "20261028_0001",
])
async def test_upgrade_preserves_existing_requests(migration_database, starting_revision):
    url, engine = migration_database
    if starting_revision != "base":
        await upgrade(url, starting_revision)
        async with engine.begin() as connection:
            await connection.execute(text("""
                INSERT INTO import_requests (
                    request_id, source_file_name, rows_detected, partner, region,
                    contact, confirmed, used_llm_fallback, parser_warnings
                ) VALUES ('migration-legacy', 'request.xlsx', 1, '', '', '', false, false, '[]')
            """))
            await connection.execute(text("""
                INSERT INTO request_items (
                    request_id, position, name, quantity, unit, notes, priority, status
                ) VALUES ('migration-legacy', 0, 'Sterile needle 21G', 2, 'piece', '',
                          'medium', 'verified')
            """))
            if starting_revision == "20261104_0001":
                await connection.execute(text("""
                    UPDATE request_items SET german_translation =
                        '{"source": "Sterile needle 21G", "text": "Sterile Nadel 21G"}'
                """))
            if starting_revision == "20261028_0001":
                await connection.execute(text("UPDATE import_requests SET review_revision = 7"))
                await connection.execute(text("""
                    UPDATE request_items SET field_reviews = '{"unit": {"accepted": true}}'
                """))

    await upgrade(url)
    await upgrade(url)  # Repeating the manual upgrade must be harmless.
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).all() == [
            ("20261105_0001",),
        ]
        for table in ("request_review_issues", "request_review_operations", "import_progress"):
            assert await connection.scalar(text("SELECT to_regclass(:name)"), {"name": table})
        if starting_revision == "base":
            return
        request = (await connection.execute(text("SELECT * FROM import_requests"))).mappings().one()
        item = (await connection.execute(text("SELECT * FROM request_items"))).mappings().one()
        assert (item["name"], item["quantity"], item["unit"]) == ("Sterile needle 21G", 2, "piece")
        assert item["status"] == "verified"
        assert item["source_active"] is True
        assert item["removed_at"] is None
        assert item["review_findings"] == []
        if starting_revision == "20261104_0001":
            assert item["german_translation"] == json.loads(
                '{"source": "Sterile needle 21G", "text": "Sterile Nadel 21G"}'
            )
        else:
            assert item["german_translation"] is None
        if starting_revision == "20261028_0001":
            assert request["review_revision"] == 7
            assert item["field_reviews"] == {"unit": {"accepted": True}}
        else:
            assert request["review_revision"] == 0
            assert item["field_reviews"] == {}
