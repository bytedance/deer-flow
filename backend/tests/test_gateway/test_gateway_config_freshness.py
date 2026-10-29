"""Regression tests for gateway config freshness on the request hot path.

Bytedance/deer-flow issue #3107 BUG-001: the worker and lead-agent path
captured ``app.state.config`` at gateway startup. ``config.yaml`` edits during
runtime were therefore ignored — ``get_app_config()``'s mtime-based reload
existed but was bypassed because the snapshot object was passed through
explicitly.

These tests pin the desired behaviour: a request-time ``get_config`` call must
observe the most recent on-disk ``config.yaml`` (mtime reload), and the
runtime ``ContextVar`` override must keep working for per-request injection.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import deerflow.config.app_config as app_config_module
from app.gateway import deps as gateway_deps
from app.gateway.deps import get_config
from deerflow.config.app_config import (
    AppConfig,
    get_app_config,
    pop_current_app_config,
    push_current_app_config,
    reset_app_config,
    set_app_config,
)
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture(autouse=True)
def _isolate_app_config_singleton():
    """Ensure each test starts with a clean module-level cache."""
    reset_app_config()
    yield
    reset_app_config()


def _write_config_yaml(
    path: Path,
    *,
    log_level: str,
    checkpoint_channel_mode: str | None = None,
) -> None:
    database = (
        ""
        if checkpoint_channel_mode is None
        else f"""
database:
  checkpoint_channel_mode: {checkpoint_channel_mode}
"""
    )
    path.write_text(
        f"""
sandbox:
  use: deerflow.sandbox.local.provider:LocalSandboxProvider
log_level: {log_level}
{database}""".strip()
        + "\n",
        encoding="utf-8",
    )


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):
        return {"log_level": cfg.log_level}

    return app


def test_get_config_reflects_file_mtime_reload(tmp_path, monkeypatch):
    """Editing config.yaml at runtime must be visible to /probe without restart.

    This is the literal repro for the issue: the gateway must not freeze the
    config to whatever was on disk when the process started.
    """
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "info"}

    # Edit the file and bump its mtime — simulating a maintainer changing
    # max_tokens / model settings in production while the gateway is live.
    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    assert client.get("/probe").json() == {"log_level": "debug"}


def _install_edit_during_load(monkeypatch, config_file: Path, *, log_level: str) -> None:
    """Rewrite ``config_file`` once, from inside the next config load.

    ``AppConfig._check_config_version`` runs after the YAML has been parsed and
    before the loader records its cache metadata, so an edit written there
    lands in exactly the window between "content parsed" and "signature
    recorded".
    """
    original = AppConfig._check_config_version.__func__
    fired = False

    def racy(cls, config_data, resolved_path):
        nonlocal fired
        if not fired:
            fired = True
            _write_config_yaml(config_file, log_level=log_level)
        return original(cls, config_data, resolved_path)

    monkeypatch.setattr(AppConfig, "_check_config_version", classmethod(racy))


def test_edit_landing_during_load_is_applied_on_the_next_call(tmp_path, monkeypatch):
    """An edit that lands while the previous edit is being loaded must not be lost.

    The loader used to parse the file and then hash the file again to record
    the cache signature. A write between those two reads left the cache holding
    the older content under the newer content's signature, so ``get_app_config``
    saw "unchanged" forever after and the edit only surfaced on the *next* edit.
    """
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))
    assert get_app_config().log_level == "info"

    _write_config_yaml(config_file, log_level="warning")  # edit #1: triggers a reload
    _install_edit_during_load(monkeypatch, config_file, log_level="debug")  # edit #2: lands mid-load

    assert get_app_config().log_level == "warning"  # the load that was in flight parsed edit #1
    assert get_app_config().log_level == "debug"  # edit #2 must be visible on the very next call


def test_recorded_signature_is_the_signature_of_the_parsed_content(tmp_path, monkeypatch):
    """The cache metadata must describe the bytes that were parsed, not whatever is on disk afterwards."""
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))
    assert get_app_config().log_level == "info"

    _write_config_yaml(config_file, log_level="warning")
    parsed_bytes = config_file.read_bytes()
    _install_edit_during_load(monkeypatch, config_file, log_level="debug")

    assert get_app_config().log_level == "warning"

    recorded = app_config_module._app_config_signature
    assert recorded is not None
    assert recorded[1] == len(parsed_bytes)
    assert recorded[2] == hashlib.sha256(parsed_bytes).hexdigest()
    assert recorded != app_config_module._get_config_signature(config_file)  # disk already holds edit #2


def test_parsed_content_is_the_signed_content_even_across_an_edit_and_revert(tmp_path, monkeypatch):
    """Signing the file before parsing it is not enough: the parsed bytes must *be* the signed bytes.

    A loader that hashes the file, then re-opens it to parse, can parse a
    revision it never signed. If that revision is then reverted, the disk
    matches the recorded signature again and the stale parse is served
    forever. Reading once and parsing those bytes makes the scenario moot.
    """
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))
    assert get_app_config().log_level == "info"

    _write_config_yaml(config_file, log_level="warning")  # edit #1: triggers a reload
    real_read = app_config_module._read_config_with_signature
    fired = False

    def read_then_edit(path):
        nonlocal fired
        result = real_read(path)
        if not fired:  # edit #2 lands right after the signed read, before parsing
            fired = True
            _write_config_yaml(config_file, log_level="debug")
        return result

    monkeypatch.setattr(app_config_module, "_read_config_with_signature", read_then_edit)

    assert get_app_config().log_level == "warning"  # what was signed is what was parsed

    _write_config_yaml(config_file, log_level="warning")  # edit #3 reverts edit #2; disk matches the recorded signature again
    assert get_app_config().log_level == "warning"  # correct for the disk; a re-reading loader would serve "debug" here forever


def test_get_config_respects_runtime_context_override(tmp_path, monkeypatch):
    """Per-request ``push_current_app_config`` injection must still win."""
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    override = AppConfig(sandbox=SandboxConfig(use="test"), log_level="trace")
    push_current_app_config(override)
    try:
        app = _build_app()
        client = TestClient(app)
        assert client.get("/probe").json() == {"log_level": "trace"}
    finally:
        pop_current_app_config()


def test_get_config_respects_test_set_app_config():
    """``set_app_config`` (used by upload/skills router tests) keeps working."""
    injected = AppConfig(sandbox=SandboxConfig(use="test"), log_level="warning")
    set_app_config(injected)

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "warning"}


def test_run_context_app_config_reflects_yaml_edit(tmp_path, monkeypatch):
    """``RunContext.app_config`` must follow live `config.yaml` edits.

    BUG-001 review feedback: the run-context that feeds worker / lead-agent
    factories must observe the same mtime reload that `get_config()` does;
    otherwise stale config slips back in through the run path even after the
    request dependency is fixed.
    """
    from unittest.mock import MagicMock

    from app.gateway.deps import get_run_context

    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = FastAPI()
    # Sentinel values for the rest of the RunContext wiring — we only care
    # about ``ctx.app_config`` for this assertion.
    app.state.checkpointer = MagicMock()
    app.state.store = MagicMock()
    app.state.run_event_store = MagicMock()
    app.state.run_events_config = {"frozen": "startup"}
    app.state.thread_store = MagicMock()

    @app.get("/run-ctx-log-level")
    def probe(ctx=Depends(get_run_context)):
        return {
            "log_level": ctx.app_config.log_level,
            "run_events_config": ctx.run_events_config,
        }

    client = TestClient(app)
    first = client.get("/run-ctx-log-level").json()
    assert first == {"log_level": "info", "run_events_config": {"frozen": "startup"}}

    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    second = client.get("/run-ctx-log-level").json()
    # app_config follows the edit; run_events_config stays frozen to the
    # startup snapshot we wrote onto app.state above.
    assert second == {"log_level": "debug", "run_events_config": {"frozen": "startup"}}


def test_run_context_freezes_checkpoint_channel_mode_at_startup(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from app.gateway.deps import get_run_context

    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info", checkpoint_channel_mode="delta")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    request = MagicMock()
    request.app.state.checkpointer = MagicMock()
    request.app.state.store = MagicMock()
    request.app.state.run_event_store = MagicMock()
    request.app.state.run_events_config = {"frozen": "startup"}
    request.app.state.thread_store = MagicMock()
    request.app.state.checkpoint_channel_mode = "full"

    ctx = get_run_context(request)
    assert ctx.app_config.database.checkpoint_channel_mode == "delta"
    assert ctx.checkpoint_channel_mode == "full"


@pytest.mark.parametrize(
    "exception",
    [
        FileNotFoundError("config.yaml not found"),
        PermissionError("config.yaml not readable"),
        ValueError("invalid config"),
        RuntimeError("yaml parse error"),
    ],
)
def test_get_config_returns_503_on_any_load_failure(monkeypatch, exception):
    """Any failure to materialise the config must surface as 503, not 500.

    Bytedance/deer-flow issue #3107 BUG-001 review: the original snapshot
    contract returned 503 when ``app.state.config is None``. The first cut of
    this fix only mapped ``FileNotFoundError`` to 503, which left
    ``PermissionError`` / ``yaml.YAMLError`` / ``ValidationError`` etc. bubbling
    up as 500. Catch every load failure at the request boundary.
    """

    def _broken_get_app_config():
        raise exception

    monkeypatch.setattr(gateway_deps, "get_app_config", _broken_get_app_config)

    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/probe")

    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration not available"}
