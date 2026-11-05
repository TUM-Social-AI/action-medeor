"""The actual Docker commands must migrate successfully before starting HTTP."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "apps/backend/Dockerfile"])
@pytest.mark.parametrize("migration_status", [0, 19])
def test_container_waits_for_migrations(tmp_path, dockerfile, migration_status):
    command = next(
        json.loads(line.removeprefix("CMD "))
        for line in (ROOT / dockerfile).read_text().splitlines() if line.startswith("CMD ")
    )
    for name, body in {
        "alembic": f'echo "migrate $*" >> "$STARTUP_LOG"\nexit {migration_status}\n',
        "uvicorn": 'echo "serve $*" >> "$STARTUP_LOG"\n',
    }.items():
        executable = tmp_path / name
        executable.write_text("#!/bin/sh\n" + body)
        executable.chmod(0o755)
    log = tmp_path / "startup.log"
    result = subprocess.run(
        command,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "STARTUP_LOG": str(log)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == migration_status, result.stderr
    expected = ["migrate upgrade head"]
    if migration_status == 0:
        expected.append("serve app.main:app --host 0.0.0.0 --port 8000")
    assert log.read_text().splitlines() == expected
