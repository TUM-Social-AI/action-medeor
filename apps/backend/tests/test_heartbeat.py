from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.jobs import heartbeat


@pytest.mark.asyncio
async def test_run_heartbeat_inserts_row_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran_at = datetime(2026, 8, 20, 12, 30, tzinfo=timezone.utc)
    result = MagicMock()
    result.one.return_value = SimpleNamespace(id=42, ran_at=ran_at)

    connection = AsyncMock()
    connection.execute.side_effect = [MagicMock(), result]

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.begin.return_value = transaction
    engine.dispose = AsyncMock()
    monkeypatch.setattr(heartbeat, "engine", engine)

    await heartbeat.run_heartbeat()

    engine.begin.assert_called_once_with()
    connection.execute.assert_has_awaits(
        [
            call(heartbeat.CREATE_TABLE),
            call(
                heartbeat.INSERT_HEARTBEAT,
                {
                    "job_name": "allocura-heartbeat",
                    "message": "Scheduled Azure job executed successfully",
                },
            ),
        ]
    )
    engine.dispose.assert_awaited_once_with()
    assert capsys.readouterr().out == (
        "Heartbeat inserted successfully: id=42, ran_at=2026-08-20T12:30:00+00:00\n"
    )


@pytest.mark.asyncio
async def test_run_heartbeat_propagates_database_errors_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = AsyncMock()
    connection.execute.side_effect = RuntimeError("database unavailable")

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.begin.return_value = transaction
    engine.dispose = AsyncMock()
    monkeypatch.setattr(heartbeat, "engine", engine)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await heartbeat.run_heartbeat()

    engine.dispose.assert_awaited_once_with()
