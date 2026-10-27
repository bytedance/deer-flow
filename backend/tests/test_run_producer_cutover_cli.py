"""Offline activation must be explicit and must not disclose database secrets."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_cli_requires_stopped_cluster_acknowledgement():
    from scripts.run_producer_fencing import main

    with pytest.raises(SystemExit) as stopped:
        main(["--cutover-id", "upgrade-1"])
    assert stopped.value.code == 2


def test_cli_redacts_connection_failure(monkeypatch, capsys):
    from scripts import run_producer_fencing as cli

    monkeypatch.setattr(cli, "activate", AsyncMock(side_effect=RuntimeError("postgresql://user:secret@host/db")))
    assert cli.main(["--cutover-id", "upgrade-1", "--all-gateways-stopped"]) == 1
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    assert "RuntimeError" in output.err


@pytest.mark.asyncio
async def test_cli_activation_uses_configured_schema_and_closes_engine(monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence import engine
    from deerflow.persistence.run import producer
    from scripts import run_producer_fencing as cli

    config = SimpleNamespace(database=SimpleNamespace(backend="postgres", model_copy=lambda **kw: "database-config"))
    monkeypatch.setattr(AppConfig, "from_file", lambda path: config)
    initialize, close, dispose, activate = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(engine, "init_engine_from_config", initialize)
    monkeypatch.setattr(engine, "get_engine", lambda: SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(engine, "get_session_factory", lambda: "session-factory")
    monkeypatch.setattr(engine, "close_engine", close)
    monkeypatch.setattr(producer, "activate_producer_fencing", activate)
    await cli.activate(config_path="operator.yaml", cutover_id="upgrade-1")
    initialize.assert_awaited_once_with("database-config")
    dispose.assert_awaited_once()
    activate.assert_awaited_once_with("session-factory", cutover_id="upgrade-1")
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_offline_command_bootstraps_and_activates_postgres(tmp_path):
    import asyncio
    import os
    import sys
    from pathlib import Path
    from uuid import uuid4

    import yaml
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "cutover_cli_" + uuid4().hex
    config = tmp_path / "operator.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"backend": "postgres", "postgres_url": "$TEST_POSTGRES_URI", "postgres_schema": schema},
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "run_events": {"backend": "db", "producer_fencing": "strict", "producer_cutover_id": "cli-test"},
            }
        ),
        encoding="utf-8",
    )
    engine = create_async_engine(uri, connect_args={"server_settings": {"search_path": schema}})
    try:
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_producer_fencing.py"
        process = await asyncio.create_subprocess_exec(sys.executable, str(script), "--config", str(config), "--cutover-id", "cli-test", "--all-gateways-stopped", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, (stdout, stderr)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT strict,cutover_id FROM run_producer_policy WHERE id=1"))).one() == (True, "cli-test")
            assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard'")) == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
