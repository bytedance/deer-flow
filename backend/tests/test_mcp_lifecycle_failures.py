"""Migration, unverifiable versions and post-commit failure handling.

These tests cover the *writer-side* rules: an absent block is migration grace,
not a retirement; a malformed block is replaced by a fresh baseline instead of
bricking the writer; an unverifiable previous config falls back to ``None`` so a
repair can still land; and a commit whose outcome is unknown must retire local
MCP state and never report "state unchanged".

Reader-side lifecycle classification, the discovery publish gate and
``prepare_mcp_reconciliation_from_revision`` are deliberately not exercised
here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import deerflow.mcp.cache as cache_module
from app.gateway.routers import mcp as mcp_router
from app.gateway.routers import skills as skills_router
from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerConfigUpdateRequest,
    McpServerStateUpdateRequest,
    delete_mcp_server,
    update_mcp_configuration,
    update_mcp_server_state,
)
from deerflow.config.extensions_config import (
    ExtensionsConfig,
    extensions_config_write_lock,
    read_raw_extensions_config,
    validate_raw_extensions_config,
)
from deerflow.mcp.client import build_server_params
from deerflow.mcp.commit import (
    MCPCommitOutcomeUnknownError,
    MCPCommittedNotReconciledError,
    MCPCommittedReloadFailedError,
    commit_extensions_config,
    validate_previous_config_lenient,
)
from deerflow.mcp.session_pool import (
    StaleMCPBindingError,
    get_session_pool,
    normalized_connection_fingerprint,
    reset_session_pool,
)
from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, set_mcp_task_config_snapshot

_MISSING = object()

_TRACKED_GLOBALS = (
    "_mcp_tools_cache",
    "_cache_initialized",
    "_config_path",
    "_config_signature",
    "_init_lock",
    "_init_condition",
    "_initializing_generation",
    "_cache_generation",
    "_mcp_config_snapshot",
    "_initialized_without_config",
    "_mcp_applied_servers",
    "_mcp_applied_order",
    "_mcp_applied_connections",
    "_mcp_applied_interceptors",
    "_mcp_applied_path",
    "_mcp_applied_signature",
    "_mcp_applied_lifecycle",
    "_mcp_applied_lifecycle_invalid",
)

_CLEARED_GLOBALS = (
    "_config_path",
    "_config_signature",
    "_mcp_config_snapshot",
    "_initialized_without_config",
    "_mcp_applied_servers",
    "_mcp_applied_order",
    "_mcp_applied_connections",
    "_mcp_applied_interceptors",
    "_mcp_applied_path",
    "_mcp_applied_signature",
    "_mcp_applied_lifecycle",
)

_INVALID_BLOCK_CASES = {
    "unsupported-schema": {"schemaVersion": 3, "lifecycleId": "x", "configRevision": 0, "globalGeneration": 0, "serverGenerations": {}},
    "missing-field": {"schemaVersion": 2, "configRevision": 0, "globalGeneration": 0, "serverGenerations": {}},
    "negative-counter": {"schemaVersion": 2, "lifecycleId": "x", "configRevision": -1, "globalGeneration": 0, "serverGenerations": {}},
    "non-object": ["not", "an", "object"],
}


def _stdio(command: str = "npx", **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command, "args": [], **extra}


def _write_config(path: Path, servers: dict, *, skills: dict | None = None, lifecycle: Any = _MISSING) -> None:
    payload: dict = {"mcpServers": servers, "skills": skills or {}}
    if lifecycle is not _MISSING:
        payload["mcpLifecycle"] = lifecycle
    path.write_text(json.dumps(payload), encoding="utf-8")


def _without_lifecycle_id(block: dict) -> dict:
    """Drop the lineage id so a fresh-baseline assertion can ignore its value."""
    return {key: value for key, value in block.items() if key != "lifecycleId"}


def _lifecycle(path: Path) -> dict:
    return read_raw_extensions_config(path)["mcpLifecycle"]


@pytest.fixture()
def cache_globals():
    """Snapshot/restore ``deerflow.mcp.cache`` globals and reset the pool."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in _CLEARED_GLOBALS:
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
    cache_module._mcp_applied_lifecycle_invalid = False
    cache_module._init_lock = threading.RLock()
    cache_module._init_condition = threading.Condition(cache_module._init_lock)
    cache_module._initializing_generation = None
    cache_module._cache_generation = 0
    set_mcp_task_config_snapshot(None)
    reset_session_pool()

    try:
        yield
    finally:
        reset_session_pool()
        set_mcp_task_config_snapshot(None)
        for name, value in saved.items():
            if value is _MISSING:
                if hasattr(cache_module, name):
                    delattr(cache_module, name)
            else:
                setattr(cache_module, name, value)


class _FakeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def initialize(self) -> None:
        return None


class _FakeSessionCm:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.session = _FakeSession(str(connection.get("command")))

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        self.session.closed = True
        return False


@pytest.fixture(autouse=True)
def _no_real_subprocesses(monkeypatch):
    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", _FakeSessionCm)


@pytest.fixture()
def owner_loop():
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        try:
            get_session_pool().close_all_sync()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
        loop.close()


def _install_discovery(monkeypatch) -> None:
    async def _fake_get_mcp_tools(*, extensions_config):
        pool = get_session_pool()
        tools = []
        for name, server in extensions_config.get_enabled_mcp_servers().items():
            params = build_server_params(name, server)
            if params.get("transport") != "stdio":
                continue
            pool.ensure_binding(name, normalized_connection_fingerprint(params))
            tools.append(f"{name}:{server.description or server.command}")
        return tools

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)


def _publish(monkeypatch, cfg: Path, servers: dict, **kwargs) -> list[str]:
    _write_config(cfg, servers, **kwargs)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)
    tools = asyncio.run(cache_module.initialize_mcp_tools())
    assert cache_module._cache_initialized is True
    return tools


def _connection(command: str) -> dict:
    return {"transport": "stdio", "command": command, "args": []}


def _open_session(loop, pool, name: str, *, scope: str = "thread-1"):
    binding = pool.active_binding(name)
    assert binding is not None, f"{name} has no active binding"
    return loop.run_until_complete(pool.get_session(name, scope, _connection(name), binding=binding))


def _entry(pool, name: str, loop, *, scope: str = "thread-1"):
    return pool._entries.get((name, scope, loop))


async def _wait_for_pending_teardowns() -> None:
    while cache_module._pending_teardowns:
        await asyncio.gather(*tuple(cache_module._pending_teardowns), return_exceptions=True)


def _allow_router_admin(monkeypatch) -> None:
    async def _noop_admin(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)


def _server_model(server: dict) -> McpServerConfigResponse:
    return McpServerConfigResponse.model_validate(server)


def _assert_stale(pool, owner_loop, name: str, binding) -> None:
    with pytest.raises(StaleMCPBindingError):
        owner_loop.run_until_complete(pool.get_session(name, "thread-1", _connection(name), binding=binding))


# ---------------------------------------------------------------------------
# An absent block is migration grace, not a lifecycle event
# ---------------------------------------------------------------------------


def test_first_write_over_a_legacy_file_does_not_bump_preexisting_servers(tmp_path: Path) -> None:
    cfg = tmp_path / "extensions_config.json"
    raw = {"mcpServers": {"A": _stdio("npx"), "B": _stdio("uvx")}, "skills": {}}
    _write_config(cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    mutated = json.loads(json.dumps(raw))
    mutated["skills"]["demo"] = {"enabled": True}
    new_config = validate_raw_extensions_config(mutated)

    committed = commit_extensions_config(
        config_path=cfg,
        raw_data=mutated,
        previous_config=previous_config,
        new_config=new_config,
    )

    assert committed.lifecycle.server_generations == {"A": 0, "B": 0}
    assert committed.lifecycle.config_revision == 1
    on_disk = _lifecycle(cfg)
    assert on_disk["schemaVersion"] == 2
    assert on_disk["lifecycleId"]
    assert on_disk["serverGenerations"] == {"A": 0, "B": 0}


def test_migration_guarantee_applies_from_the_second_commit(tmp_path: Path) -> None:
    cfg = tmp_path / "extensions_config.json"
    legacy = {"mcpServers": {"A": _stdio("npx"), "B": _stdio("uvx")}, "skills": {}}
    _write_config(cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(legacy)))
    _commit(cfg, legacy, previous_config, previous_config)

    # The block now exists, so the guarantee covers the next (deletion) event.
    raw = read_raw_extensions_config(cfg)
    mutated = json.loads(json.dumps(raw))
    del mutated["mcpServers"]["A"]
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    new_config = validate_raw_extensions_config(mutated)
    _commit(cfg, mutated, previous_config, new_config)

    on_disk = _lifecycle(cfg)
    assert on_disk["configRevision"] == 2
    assert on_disk["serverGenerations"]["A"] == 1
    assert on_disk["serverGenerations"]["B"] == 0


def test_router_write_over_a_legacy_file_keeps_live_sessions(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a = pool.active_binding("A")
    _allow_router_admin(monkeypatch)

    async def _run() -> None:
        await update_mcp_server_state(None, McpServerStateUpdateRequest(server_name="A", enabled=True))
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert pool.active_binding("A") == binding_a
    assert _entry(pool, "A", owner_loop)[0] is session_a
    assert session_a.closed is False
    on_disk = _lifecycle(cfg)
    assert on_disk["schemaVersion"] == 2
    assert on_disk["lifecycleId"]
    assert on_disk["configRevision"] == 1
    assert on_disk["globalGeneration"] == 0
    assert on_disk["serverGenerations"] == {"A": 0, "B": 0}


def _commit(cfg: Path, raw_data: dict, previous_config, new_config) -> None:
    commit_extensions_config(
        config_path=cfg,
        raw_data=raw_data,
        previous_config=previous_config,
        new_config=new_config,
    )


# ---------------------------------------------------------------------------
# A malformed block is replaced, never left in place
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(_INVALID_BLOCK_CASES))
def test_invalid_block_is_replaced_and_every_enabled_server_bumped(tmp_path: Path, case: str) -> None:
    cfg = tmp_path / "extensions_config.json"
    raw = {
        "mcpServers": {"A": _stdio("npx"), "B": _stdio("uvx")},
        "skills": {},
        "mcpLifecycle": _INVALID_BLOCK_CASES[case],
    }
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    new_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))

    _commit(cfg, raw, previous_config, new_config)

    fresh = _lifecycle(cfg)
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1, "B": 1},
    }
    assert fresh["lifecycleId"]


def test_explicit_null_lifecycle_block_is_malformed_not_legacy(tmp_path: Path) -> None:
    """``"mcpLifecycle": null`` is a present-but-unusable block, not migration grace."""
    cfg = tmp_path / "extensions_config.json"
    raw = {"mcpServers": {"A": _stdio("npx"), "B": _stdio("uvx")}, "skills": {}, "mcpLifecycle": None}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))

    _commit(cfg, raw, previous_config, previous_config)

    fresh = _lifecycle(cfg)
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1, "B": 1},
    }
    assert fresh["lifecycleId"]


def test_router_write_repairs_an_invalid_block(cache_globals, monkeypatch, tmp_path) -> None:
    cfg = tmp_path / "extensions_config.json"
    _write_config(
        cfg,
        {"A": _stdio("npx"), "B": _stdio("uvx")},
        lifecycle={"schemaVersion": 3, "configRevision": 4, "globalGeneration": 1, "serverGenerations": {"A": 3}},
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)
    asyncio.run(cache_module.initialize_mcp_tools())
    _allow_router_admin(monkeypatch)

    asyncio.run(update_mcp_server_state(None, McpServerStateUpdateRequest(server_name="A", enabled=True)))

    fresh = _lifecycle(cfg)
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1, "B": 1},
    }
    assert fresh["lifecycleId"]


def test_unverifiable_baselines_force_a_whole_pool_bump(tmp_path: Path) -> None:
    """Ruling 1: an unprovable baseline retires the whole pool, not only servers."""
    # (a) ordinary migration grace: absent block + valid previous config -> no bump
    graceful = tmp_path / "graceful.json"
    raw = {"mcpServers": {"A": _stdio("npx")}, "skills": {}}
    graceful.write_text(json.dumps(raw), encoding="utf-8")
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    _commit(graceful, raw, previous_config, previous_config)
    assert _lifecycle(graceful)["globalGeneration"] == 0
    assert _lifecycle(graceful)["serverGenerations"] == {"A": 0}

    # (b) malformed block -> fresh baseline whose global generation advances
    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        json.dumps({**_stdlib_servers(), "mcpLifecycle": {"schemaVersion": 3, "configRevision": 4, "globalGeneration": 9, "serverGenerations": {"A": 3}}}),
        encoding="utf-8",
    )
    raw = read_raw_extensions_config(malformed)
    previous_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    _commit(malformed, raw, previous_config, previous_config)
    assert _lifecycle(malformed)["globalGeneration"] == 1

    # (c) unverifiable previous document, block present and valid -> +1
    unverifiable = tmp_path / "unverifiable.json"
    unverifiable.write_text(
        json.dumps({**_stdlib_servers(), "mcpLifecycle": {"schemaVersion": 2, "lifecycleId": "lineage-old", "configRevision": 5, "globalGeneration": 4, "serverGenerations": {"A": 2}}}),
        encoding="utf-8",
    )
    raw = read_raw_extensions_config(unverifiable)
    new_config = validate_raw_extensions_config(json.loads(json.dumps(raw)))
    _commit(unverifiable, raw, None, new_config)
    assert _lifecycle(unverifiable)["globalGeneration"] == 5
    assert _lifecycle(unverifiable)["serverGenerations"] == {"A": 3}


# ---------------------------------------------------------------------------
# An unverifiable previous config must not block a repair
# ---------------------------------------------------------------------------

_INVALID_STORED_SERVER = {"enabled": True, "type": "stdio", "command": "npx", "args": "not-a-list"}


def _stdlib_servers() -> dict:
    return {"mcpServers": {"A": _stdio("npx")}, "skills": {}}


def test_delete_repairs_an_invalid_stored_server(cache_globals, monkeypatch, tmp_path) -> None:
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio("npx"), "broken": _INVALID_STORED_SERVER})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _allow_router_admin(monkeypatch)

    asyncio.run(delete_mcp_server(None, "broken"))

    written = read_raw_extensions_config(cfg)
    assert "broken" not in written["mcpServers"]
    fresh = written["mcpLifecycle"]
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1},
    }
    assert fresh["lifecycleId"]


def test_full_put_repairs_an_invalid_stored_server(cache_globals, monkeypatch, tmp_path) -> None:
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio("npx"), "broken": _INVALID_STORED_SERVER})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _allow_router_admin(monkeypatch)

    body = McpConfigUpdateRequest(
        mcp_servers={
            "A": _server_model(_stdio("npx")),
            "B": _server_model(_stdio("uvx")),
        },
    )
    asyncio.run(update_mcp_configuration(None, body))

    written = read_raw_extensions_config(cfg)
    assert set(written["mcpServers"]) == {"A", "B"}
    fresh = written["mcpLifecycle"]
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1, "B": 1},
    }
    assert fresh["lifecycleId"]


def test_full_put_can_replace_an_invalid_stored_server_by_name(cache_globals, monkeypatch, tmp_path) -> None:
    """The stored server is unparseable, so there are no stored secrets to merge."""
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"broken": _INVALID_STORED_SERVER})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _allow_router_admin(monkeypatch)

    body = McpConfigUpdateRequest(mcp_servers={"broken": _server_model(_stdio("uvx"))})
    asyncio.run(update_mcp_configuration(None, body))

    written = read_raw_extensions_config(cfg)
    assert written["mcpServers"]["broken"]["args"] == []
    assert written["mcpServers"]["broken"]["command"] == "uvx"
    assert written["mcpLifecycle"]["globalGeneration"] == 1
    assert written["mcpLifecycle"]["serverGenerations"] == {"broken": 1}


def test_skills_write_survives_an_unverifiable_previous_document(monkeypatch, tmp_path) -> None:
    # A non-object skills entry fails validation but is exactly what the toggle
    # repairs; the lenient previous-config derivation must not raise first.
    cfg = tmp_path / "extensions_config.json"
    raw = {"mcpServers": {"A": _stdio("npx")}, "skills": {"demo-skill": ["broken"]}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda _path=None: cfg))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig())

    skills_router._write_extensions_skill_state(None, "demo-skill", True, rebuild_public_projection=False)

    written = read_raw_extensions_config(cfg)
    assert written["skills"]["demo-skill"] == {"enabled": True}
    fresh = written["mcpLifecycle"]
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1},
    }
    assert fresh["lifecycleId"]


def test_client_mcp_write_survives_an_invalid_stored_server(cache_globals, monkeypatch, tmp_path) -> None:
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio("npx"), "broken": _INVALID_STORED_SERVER})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)

    app_config = MagicMock()
    app_config.database.checkpoint_channel_mode = "full"
    app_config.database.checkpoint_delta.snapshot_frequency = 10
    monkeypatch.setattr(client_module, "get_app_config", lambda: app_config)
    client = DeerFlowClient()

    client.update_mcp_config({"B": _stdio("uvx")})

    written = read_raw_extensions_config(cfg)
    assert set(written["mcpServers"]) == {"B"}
    assert written["mcpLifecycle"]["globalGeneration"] == 1
    assert written["mcpLifecycle"]["serverGenerations"] == {"B": 1}


def test_client_skill_write_survives_an_unverifiable_previous_document(monkeypatch, tmp_path) -> None:
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    cfg = tmp_path / "extensions_config.json"
    raw = {"mcpServers": {"A": _stdio("npx")}, "skills": {"demo-skill": ["broken"]}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(client_module, "reload_extensions_config", lambda: None)

    DeerFlowClient._commit_skill_enabled_state(cfg, "demo-skill", True)

    written = read_raw_extensions_config(cfg)
    assert written["skills"]["demo-skill"] == {"enabled": True}
    fresh = written["mcpLifecycle"]
    assert _without_lifecycle_id(fresh) == {
        "schemaVersion": 2,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"A": 1},
    }
    assert fresh["lifecycleId"]


def test_lenient_previous_config_swallows_non_http_errors(monkeypatch) -> None:
    """A non-HTTPException escape must not turn a repair into a 500."""
    import deerflow.mcp.commit as commit_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("previous-snapshot validation exploded")

    monkeypatch.setattr(commit_module, "validate_raw_extensions_config", _boom)
    monkeypatch.setattr(mcp_router, "_validate_extensions_config_candidate", _boom)

    assert mcp_router._lenient_previous_mcp_config({"mcpServers": {}}) is None


# ---------------------------------------------------------------------------
# Post-commit failure semantics
# ---------------------------------------------------------------------------


def _publish_with_sessions(monkeypatch, cfg: Path, owner_loop):
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    return pool, session_a, session_b


def test_indeterminate_commit_retires_local_state_and_reports_unknown_outcome(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    cfg = tmp_path / "extensions_config.json"
    pool, session_a, _session_b = _publish_with_sessions(monkeypatch, cfg, owner_loop)
    binding_a = pool.active_binding("A")

    def _truncate_then_raise(path, data):
        Path(path).write_text("", encoding="utf-8")
        raise OSError("simulated EBUSY in-place overwrite failure")

    monkeypatch.setattr("deerflow.mcp.commit.atomic_write_extensions_config", _truncate_then_raise)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", lambda: None)
    _allow_router_admin(monkeypatch)

    with pytest.raises(MCPCommitOutcomeUnknownError) as exc_info:
        mcp_router._apply_mcp_server_delete("A")

    # The write may already have landed, so the outcome must not be "unchanged".
    assert cfg.read_text(encoding="utf-8") == ""
    message = str(exc_info.value).lower()
    assert "unknown" in message
    # P2: raised before the caller invalidates, so it must not claim retirement.
    assert "sessions were retired" not in message

    # Local state is conservatively invalidated: the old binding is fenced out
    # and its session torn down.
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


def test_committed_but_not_reconciled_retires_local_state(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    cfg = tmp_path / "extensions_config.json"
    pool, session_a, _session_b = _publish_with_sessions(monkeypatch, cfg, owner_loop)
    binding_a = pool.active_binding("A")

    def _boom(_committed):
        raise RuntimeError("fence exploded")

    monkeypatch.setattr(mcp_router, "prepare_mcp_reconciliation_from_revision", _boom)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", lambda: None)
    _allow_router_admin(monkeypatch)

    with pytest.raises(MCPCommittedNotReconciledError) as exc_info:
        mcp_router._apply_mcp_server_delete("A")

    # The commit landed on disk even though the fence failed.
    written = read_raw_extensions_config(cfg)
    assert "A" not in written["mcpServers"]
    assert written["mcpLifecycle"]["configRevision"] == 1

    assert "committed" in str(exc_info.value).lower()
    assert "retired" not in str(exc_info.value).lower()
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


def test_reload_failure_after_fence_reports_the_commit_happened(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a_before = pool.active_binding("A")

    def _boom():
        raise RuntimeError("reload exploded")

    monkeypatch.setattr(mcp_router, "reload_extensions_config", _boom)
    body = McpServerConfigUpdateRequest(server_name="A", server=_server_model(_stdio("npx-next")))
    with pytest.raises(MCPCommittedReloadFailedError) as exc_info:
        mcp_router._apply_mcp_server_config_update(body)

    # The fence already ran: the binding was re-epoch'd and the counters committed.
    assert pool.active_binding("A") != binding_a_before
    written = read_raw_extensions_config(cfg)
    assert written["mcpServers"]["A"]["command"] == "npx-next"
    assert written["mcpLifecycle"]["serverGenerations"] == {"A": 1, "B": 0}
    assert "committed" in str(exc_info.value).lower()
    # Ruling 2: the post-lock ``finish`` still reaped the prepared owner.
    assert session_a.closed is True
    assert _entry(pool, "A", owner_loop) is None


def test_client_reload_failure_still_reaps_the_prepared_owner(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """Ruling 2 applies to the embedded client MCP writer too."""
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a_before = pool.active_binding("A")

    app_config = MagicMock()
    app_config.database.checkpoint_channel_mode = "full"
    app_config.database.checkpoint_delta.snapshot_frequency = 10
    monkeypatch.setattr(client_module, "get_app_config", lambda: app_config)

    def _boom():
        raise RuntimeError("reload exploded")

    monkeypatch.setattr(client_module, "reload_extensions_config", _boom)
    client = DeerFlowClient()

    with pytest.raises(MCPCommittedReloadFailedError) as exc_info:
        client.update_mcp_config({"A": _stdio("npx-next"), "B": _stdio("uvx")})

    assert "committed" in str(exc_info.value).lower()
    assert pool.active_binding("A") != binding_a_before
    assert session_a.closed is True
    written = read_raw_extensions_config(cfg)
    assert written["mcpServers"]["A"]["command"] == "npx-next"
    assert written["mcpLifecycle"]["serverGenerations"] == {"A": 1, "B": 0}


# ---------------------------------------------------------------------------
# P2 — conservative invalidation must never wait for teardown under the config lock
# ---------------------------------------------------------------------------


def _blocking_exit_session_cm(monkeypatch, teardown_started: threading.Event, release_exit: threading.Event):
    class _BlockingExitSessionCm(_FakeSessionCm):
        async def __aexit__(self, *exc):
            self.session.closed = True
            teardown_started.set()
            assert release_exit.wait(timeout=10)
            return False

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", _BlockingExitSessionCm)


def _run_writer_and_probe_config_lock(writer, teardown_started: threading.Event, release_exit: threading.Event) -> list[BaseException]:
    """Run *writer* on a worker thread and assert the config lock is free mid-teardown."""
    errors: list[BaseException] = []

    def _target() -> None:
        try:
            writer()
        except BaseException as exc:  # noqa: BLE001 - the writer is expected to raise
            errors.append(exc)

    thread = threading.Thread(target=_target)
    thread.start()
    try:
        assert teardown_started.wait(timeout=10), "conservative teardown never started"
        acquired = extensions_config_write_lock.acquire(timeout=2)
        if acquired:
            extensions_config_write_lock.release()
        assert acquired, "extensions_config_write_lock was held while waiting for conservative teardown"
    finally:
        release_exit.set()
        thread.join(timeout=15)

    assert not thread.is_alive(), "writer thread did not finish"
    return errors


def test_force_local_mcp_invalidation_never_raises(cache_globals, monkeypatch) -> None:
    """The conservative-invalidation helper must never mask the original error."""

    def _boom():
        raise RuntimeError("conservative reset exploded")

    monkeypatch.setattr(cache_module, "_reset_mcp_tools_cache_state_and_retire_pool_locked", _boom)

    cache_module.force_local_mcp_invalidation()  # must not raise


def test_mid_write_failure_invalidates_outside_the_config_lock(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """The outcome-unknown path must not wait for teardown holding the write lock."""
    teardown_started = threading.Event()
    release_exit = threading.Event()
    _blocking_exit_session_cm(monkeypatch, teardown_started, release_exit)

    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a = pool.active_binding("A")

    def _truncate_then_raise(path, data):
        Path(path).write_text("", encoding="utf-8")
        raise OSError("simulated EBUSY in-place overwrite failure")

    monkeypatch.setattr("deerflow.mcp.commit.atomic_write_extensions_config", _truncate_then_raise)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", lambda: None)

    errors = _run_writer_and_probe_config_lock(
        lambda: mcp_router._apply_mcp_server_delete("A"),
        teardown_started,
        release_exit,
    )

    assert len(errors) == 1
    assert isinstance(errors[0], MCPCommitOutcomeUnknownError)
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


def test_fence_failure_invalidates_outside_the_config_lock(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """A fence failure must not wait for teardown holding the write lock either."""
    teardown_started = threading.Event()
    release_exit = threading.Event()
    _blocking_exit_session_cm(monkeypatch, teardown_started, release_exit)

    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a = pool.active_binding("A")

    def _boom(_committed):
        raise RuntimeError("fence exploded")

    monkeypatch.setattr(mcp_router, "prepare_mcp_reconciliation_from_revision", _boom)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", lambda: None)

    errors = _run_writer_and_probe_config_lock(
        lambda: mcp_router._apply_mcp_server_delete("A"),
        teardown_started,
        release_exit,
    )

    assert len(errors) == 1
    assert isinstance(errors[0], MCPCommittedNotReconciledError)
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


def test_task_config_conflict_escaping_the_fence_still_invalidates(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """A ``McpTaskConfigurationError`` from the fence must not skip invalidation.

    The durable-task 409 is raised for a write that has *already*
    committed, so the local pool must be conservatively invalidated on the way
    out. Mapping straight to 409 (the pre-fix behaviour) leaves the committed
    change unfenced and an old session usable.
    """
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    _allow_router_admin(monkeypatch)

    def _conflict(_committed):
        raise McpTaskConfigurationError("frozen task config changed", changed_servers=("A",))

    monkeypatch.setattr(mcp_router, "prepare_mcp_reconciliation_from_revision", _conflict)
    monkeypatch.setattr(mcp_router, "reload_extensions_config", lambda: None)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(delete_mcp_server(None, "A"))

    assert excinfo.value.status_code == 409
    assert "MCP task-enabled server configuration changed" in excinfo.value.detail
    # Conservative invalidation: no session may survive the committed write.
    assert cache_module._cache_initialized is False
    assert get_session_pool() is not pool
    assert session_a.closed is True
    assert session_b.closed is True


# ---------------------------------------------------------------------------
# Skills writes: no-op vs repair vs indeterminate outcome
# ---------------------------------------------------------------------------


def _patch_skills_writer(monkeypatch, cfg: Path) -> None:
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda _path=None: cfg))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig())


def test_skill_write_keeps_sessions_and_advances_only_config_revision(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """An ordinary skills edit is not an MCP lifecycle event."""
    cfg = tmp_path / "extensions_config.json"
    pool, session_a, _session_b = _publish_with_sessions(monkeypatch, cfg, owner_loop)
    binding_a = pool.active_binding("A")
    _patch_skills_writer(monkeypatch, cfg)

    skills_router._write_extensions_skill_state(None, "demo-skill", True, rebuild_public_projection=False)

    assert get_session_pool() is pool
    assert pool.active_binding("A") == binding_a
    assert _entry(pool, "A", owner_loop)[0] is session_a
    assert session_a.closed is False
    on_disk = _lifecycle(cfg)
    assert on_disk["configRevision"] == 1
    assert on_disk["globalGeneration"] == 0
    assert on_disk["serverGenerations"] == {"A": 0, "B": 0}


def test_skill_write_repairing_an_invalid_block_fences_local_state(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """A skills write that re-bases the lifecycle must fence the writing process."""
    cfg = tmp_path / "extensions_config.json"
    _publish(
        monkeypatch,
        cfg,
        {"A": _stdio("npx"), "B": _stdio("uvx")},
        lifecycle={
            "schemaVersion": 2,
            "lifecycleId": "lineage-1",
            "configRevision": 5,
            "globalGeneration": 0,
            "serverGenerations": {"A": 0, "B": 0},
        },
    )
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a = pool.active_binding("A")
    applied_id_before = cache_module._mcp_applied_lifecycle.lifecycle_id
    assert applied_id_before == "lineage-1"

    # Corrupt the block out of band; the skills write is what repairs it.
    raw = read_raw_extensions_config(cfg)
    raw["mcpLifecycle"] = {"schemaVersion": 2, "configRevision": 1, "globalGeneration": 1, "serverGenerations": {"A": 1, "B": 1}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    _patch_skills_writer(monkeypatch, cfg)

    skills_router._write_extensions_skill_state(None, "demo-skill", True, rebuild_public_projection=False)

    # The repair established a new lineage, so the local ownership transfer ran.
    assert _lifecycle(cfg)["lifecycleId"] != applied_id_before
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


def test_skill_write_indeterminate_outcome_invalidates_local_state(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """An EBUSY-style partial write must not be reported as "state unchanged"."""
    cfg = tmp_path / "extensions_config.json"
    pool, session_a, _session_b = _publish_with_sessions(monkeypatch, cfg, owner_loop)
    binding_a = pool.active_binding("A")
    _patch_skills_writer(monkeypatch, cfg)

    def _truncate_then_raise(path, data):
        Path(path).write_text("", encoding="utf-8")
        raise OSError("simulated EBUSY in-place overwrite failure")

    monkeypatch.setattr("deerflow.mcp.commit.atomic_write_extensions_config", _truncate_then_raise)

    with pytest.raises(MCPCommitOutcomeUnknownError) as exc_info:
        skills_router._write_extensions_skill_state(None, "demo-skill", True, rebuild_public_projection=False)

    assert cfg.read_text(encoding="utf-8") == ""
    message = str(exc_info.value).lower()
    assert "unknown" in message
    assert "sessions were retired" not in message
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a)
    assert session_a.closed is True


# ---------------------------------------------------------------------------
# Resolved credentials must never reach the logs
# ---------------------------------------------------------------------------

_LEAK_SECRET = "ghp_do_not_log_me_1234567890"


def test_lenient_validation_failure_never_logs_resolved_secrets(monkeypatch, tmp_path, caplog) -> None:
    """The lenient previous-config path must not echo a resolved $VAR value."""
    monkeypatch.setenv("DEERFLOW_LEAK_PROBE", _LEAK_SECRET)
    cfg = tmp_path / "extensions_config.json"
    # ``enabled`` is a boolean, so the resolved secret becomes the failing input.
    cfg.write_text(
        json.dumps({"mcpServers": {"A": {"enabled": "$DEERFLOW_LEAK_PROBE"}}, "skills": {}}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        assert validate_previous_config_lenient(read_raw_extensions_config(cfg)) is None

    assert caplog.records, "the unverifiable previous config should be reported"
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert _LEAK_SECRET not in joined
    assert "ValidationError" in joined


def test_config_load_failure_never_embeds_resolved_secrets(monkeypatch, tmp_path) -> None:
    """``from_file`` must not chain a ValidationError that carries a secret."""
    import traceback

    from deerflow.config.extensions_config import ExtensionsConfig

    monkeypatch.setenv("DEERFLOW_LEAK_PROBE", _LEAK_SECRET)
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"A": {"enabled": "$DEERFLOW_LEAK_PROBE"}}, "skills": {}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as exc_info:
        ExtensionsConfig.from_file(str(cfg))

    rendered = "".join(traceback.format_exception(type(exc_info.value), exc_info.value, exc_info.value.__traceback__))
    assert _LEAK_SECRET not in str(exc_info.value)
    assert _LEAK_SECRET not in rendered


# ---------------------------------------------------------------------------
# Stored-server merge failures must not log the stored value
# ---------------------------------------------------------------------------

_STORED_LITERAL_SECRET = "sk-live-do-not-log-0123456789"


def test_stored_server_merge_failure_never_logs_the_stored_value(cache_globals, monkeypatch, tmp_path, caplog) -> None:
    """A full PUT that repairs an unparseable stored server must not echo it."""
    cfg = tmp_path / "extensions_config.json"
    _write_config(
        cfg,
        {
            "A": _stdio("npx"),
            # ``env`` must be a mapping, so the credential pasted here is the
            # failing input value and would be echoed by the exception chain.
            "broken": {"enabled": True, "type": "stdio", "command": "npx", "args": [], "env": _STORED_LITERAL_SECRET},
        },
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _allow_router_admin(monkeypatch)
    _install_discovery(monkeypatch)

    # The incoming replacement uses the same name as the unparseable stored
    # entry, which is what drives the secret-preserving merge branch.
    body = McpConfigUpdateRequest(mcp_servers={"broken": _server_model(_stdio("npx"))})
    with caplog.at_level(logging.DEBUG):
        asyncio.run(update_mcp_configuration(None, body))

    # Render exactly what a log handler would emit, including any exc_info chain.
    rendered = "\n".join(logging.Formatter().format(record) for record in caplog.records)
    assert caplog.records, "the unparseable stored server should be reported"
    assert _STORED_LITERAL_SECRET not in rendered


# ---------------------------------------------------------------------------
# The embedded client must hand ``pending`` over before reloading
# ---------------------------------------------------------------------------


def test_client_skill_reload_failure_still_reaps_the_prepared_owner(cache_globals, monkeypatch, tmp_path, owner_loop) -> None:
    """A reload failure must not lose the detached-owner teardown."""
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    cfg = tmp_path / "extensions_config.json"
    _publish(
        monkeypatch,
        cfg,
        {"A": _stdio("npx"), "B": _stdio("uvx")},
        lifecycle={
            "schemaVersion": 2,
            "lifecycleId": "lineage-1",
            "configRevision": 5,
            "globalGeneration": 0,
            "serverGenerations": {"A": 0, "B": 0},
        },
    )
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a_before = pool.active_binding("A")

    # Corrupt the block so the skills write re-bases the lifecycle and therefore
    # detaches A's owner before the reload runs.
    raw = read_raw_extensions_config(cfg)
    raw["mcpLifecycle"] = {"schemaVersion": 2, "configRevision": 1, "globalGeneration": 1, "serverGenerations": {"A": 1, "B": 1}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")

    def _boom():
        raise RuntimeError("reload exploded")

    monkeypatch.setattr(client_module, "reload_extensions_config", _boom)

    with pytest.raises(MCPCommittedReloadFailedError) as exc_info:
        DeerFlowClient._commit_skill_enabled_state(cfg, "demo-skill", True)

    assert "committed" in str(exc_info.value).lower()
    # The ownership transfer already ran, so the detached owner must still be
    # reaped even though the reload raised.
    assert get_session_pool() is not pool
    _assert_stale(pool, owner_loop, "A", binding_a_before)
    assert session_a.closed is True
