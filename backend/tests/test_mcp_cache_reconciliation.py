"""Deterministic coverage for process-local selective MCP reconciliation.

Design invariants (every test below targets at least one):

* Unchanged-session preservation:
    A stdio server whose connection identity did not change keeps its binding,
    its pooled session and its owner task — not merely "``close`` was not
    called" on some other object.
* Superseded-binding exclusion:
    After a connection-identity change or a removal, the old wrapper/creator/
    joiner capability can never recreate, commit or return the old session.
* Applied-state monotonicity:
    Every *applied* transition advances the binding epoch, even while the tool
    cache is empty, and an older revision can never be applied after a newer
    one.  A(v1) -> A(v2) -> A(v1) still produces a new epoch.
* Publication consistency:
    Published tools always belong to a revision that is still current: a
    superseded discovery, a shared reset and a config change all fence it.
* Ownership and teardown safety:
    Retirement notifies the target owner and never blocks reconciliation
    behind an owner stuck in ``__aexit__``; unchanged servers are untouched.
* Conservative uncertainty:
    An unverifiable/absent-but-configured revision is never treated as
    "unchanged", yet the "config deleted after a successful load" fail-soft
    contract is preserved.

Every assertion is written against observable state (pool identity, binding
epoch/identity, session/owner identity, create/exit counts, cache generation,
applied revision, published tools) rather than the private object layout of the
pool, and every interleaving is forced with an explicit barrier instead of
``asyncio.sleep`` ordering.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

import deerflow.mcp.cache as cache_module
from deerflow.config.extensions_config import ExtensionsConfig, atomic_write_extensions_config
from deerflow.config.file_signature import get_config_signature
from deerflow.mcp import session_pool as session_pool_module
from deerflow.mcp.client import build_server_params, build_servers_config
from deerflow.mcp.session_pool import (
    MCPSessionPool,
    StaleMCPBindingError,
    normalized_connection_fingerprint,
)
from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, set_mcp_task_config_snapshot

_MISSING = object()

# ``_applied_mcp_revision`` is the process-local reconciliation baseline; it must
# be snapshotted/restored like the published-cache globals so no state leaks
# between tests.
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
    "_cache_reset_marker_signature",
    "_applied_mcp_revision",
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _write_config(
    path: Path,
    servers: dict,
    *,
    skills: dict | None = None,
    interceptors: list | str | None = None,
) -> None:
    payload: dict = {"mcpServers": servers, "skills": skills or {}}
    if interceptors is not None:
        payload["mcpInterceptors"] = interceptors
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stdio(command: str = "npx", **extra) -> dict:
    server = {"enabled": True, "type": "stdio", "command": command}
    server.update(extra)
    return server


def _http(url: str = "https://example.test/mcp", **extra) -> dict:
    server = {"enabled": True, "type": "http", "url": url}
    server.update(extra)
    return server


@pytest.fixture()
def reconciler():
    """Isolate cache coordination state *and* the session-pool singleton."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in (
        "_config_path",
        "_config_signature",
        "_mcp_config_snapshot",
        "_initialized_without_config",
        "_cache_reset_marker_signature",
        "_applied_mcp_revision",
    ):
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
    cache_module._init_lock = threading.RLock()
    cache_module._init_condition = threading.Condition(cache_module._init_lock)
    cache_module._initializing_generation = None
    cache_module._cache_generation = 0
    session_pool_module.reset_session_pool()
    # A task server's frozen snapshot is process-global.
    set_mcp_task_config_snapshot(None)

    try:
        yield
    finally:
        set_mcp_task_config_snapshot(None)
        session_pool_module.reset_session_pool()
        for name, value in saved.items():
            if value is _MISSING:
                if hasattr(cache_module, name):
                    delattr(cache_module, name)
            else:
                setattr(cache_module, name, value)


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<tool {self.name}>"


class _FakeSession:
    __slots__ = ("key",)

    def __init__(self, key: str) -> None:
        self.key = key

    async def initialize(self) -> None:
        return None


class _RecordingSessionCm:
    """Stand-in for ``create_session()``'s context manager."""

    def __init__(self, key: str, log: dict) -> None:
        self.key = key
        self.log = log
        self.closed = False
        self.session = _FakeSession(key)

    async def __aenter__(self):
        return self.session

    async def initialize(self) -> None:
        return None

    async def __aexit__(self, *_exc) -> None:
        started = self.log.setdefault("exit_started", {})
        started[self.key] = started.get(self.key, 0) + 1
        gate = self.log.get("exit_gate")
        if gate is not None:
            await gate.wait()
        self.closed = True
        self.log["exited"][self.key] = self.log["exited"].get(self.key, 0) + 1


def _session_log() -> dict:
    return {"created": {}, "exited": {}, "exit_started": {}, "cms": {}}


def _record_sessions(monkeypatch, log: dict) -> None:
    """Route ``create_session(connection)`` to a per-server recording CM."""

    def _create(connection, **_kwargs):
        key = connection.get("command") or connection.get("url") or "unknown"
        log["created"][key] = log["created"].get(key, 0) + 1
        cm = _RecordingSessionCm(key, log)
        log["cms"].setdefault(key, []).append(cm)
        return cm

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", _create)


def _install_discovery(
    monkeypatch,
    *,
    before_bindings=None,
    after_bindings=None,
    fail_after_bindings: bool = False,
    create_sessions: bool = True,
    hooks: dict | None = None,
):
    """Replace ``tools.get_mcp_tools`` with a deterministic stand-in.

    It mirrors the real discovery prologue (``build_servers_config`` +
    ``ensure_binding`` before the first awaited session creation) so the cache
    layer is exercised against the same ordering discovery itself guarantees.
    """
    from deerflow.mcp import tools as tools_module

    async def _fake_get_mcp_tools(*, extensions_config, session_pool=None):
        pool = session_pool if session_pool is not None else session_pool_module.get_session_pool()
        servers = build_servers_config(extensions_config)
        if hooks is not None:
            hooks["servers"] = servers
        if before_bindings is not None:
            await before_bindings(servers, pool)
        bindings = {}
        for name, connection in servers.items():
            if connection.get("transport", "stdio") == "stdio":
                bindings[name] = pool.ensure_binding(
                    name,
                    normalized_connection_fingerprint(connection),
                    domain="deployment",
                )
        if hooks is not None:
            hooks["bindings"] = bindings
        if after_bindings is not None:
            await after_bindings(servers, pool, bindings)
        if fail_after_bindings:
            raise RuntimeError("discovery failed after binding install")
        if not create_sessions:
            return []
        sessions = {}
        for name, binding in bindings.items():
            sessions[name] = await pool.get_session(name, "u:t", servers[name], binding=binding)
        if hooks is not None:
            hooks["sessions"] = sessions
        return [_FakeTool(name) for name in servers]

    monkeypatch.setattr(tools_module, "get_mcp_tools", _fake_get_mcp_tools)


def _write_remote_marker(config_path: Path, generation: str) -> Path:
    """Simulate a shared cache reset published by another worker."""
    marker_path = cache_module._cache_reset_marker_path(config_path)
    atomic_write_extensions_config(marker_path, {"version": 1, "generation": generation})
    return marker_path


async def _wait_until(predicate, *, timeout: float = 2.0, message: str = "condition not met") -> None:
    """Bounded wait for an observable side effect (never used for ordering)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(message)
        await asyncio.sleep(0)


def _binding(pool: MCPSessionPool, name: str, domain: str = "deployment"):
    return pool._bindings[(domain, name)]


def _entry(pool: MCPSessionPool, name: str, scope: str = "u:t", domain: str = "deployment"):
    for key, entry in pool._entries.items():
        if key[0] == name and key[1] == scope and key[3] == domain:
            return entry
    return None


async def _initialize(monkeypatch, cfg: Path, servers: dict, log: dict, **kwargs) -> list:
    _write_config(cfg, servers, **{k: v for k, v in kwargs.items() if k in {"skills", "interceptors"}})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _record_sessions(monkeypatch, log)
    hooks: dict = {}
    _install_discovery(monkeypatch, hooks=hooks)
    tools = await cache_module.initialize_mcp_tools()
    return tools


def _task_toolset() -> dict:
    return {
        "name": "jobs",
        "submit_tool": "submit_job",
        "status_tool": "job_status",
        "cancel_tool": "cancel_job",
    }


def _task_server(command: str = "cmd-A1", **extra) -> dict:
    """A stdio server whose durable task contract freezes its connection."""
    return _stdio(command, task_toolsets=[_task_toolset()], **extra)


def _freeze_task_snapshot(servers: dict, *, interceptors: list | str | None = None) -> None:
    payload: dict = {"mcpServers": servers}
    if interceptors is not None:
        payload["mcpInterceptors"] = interceptors
    set_mcp_task_config_snapshot(ExtensionsConfig.model_validate(payload))


def _startup_connection(servers: dict, name: str):
    config = ExtensionsConfig.model_validate({"mcpServers": servers})
    connection = build_server_params(name, config.mcp_servers[name])
    return connection, normalized_connection_fingerprint(connection)


def _fingerprint(servers: dict, name: str) -> str:
    return normalized_connection_fingerprint(build_servers_config(ExtensionsConfig.model_validate({"mcpServers": servers}))[name])


# ---------------------------------------------------------------------------
# Classification and selective retirement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_change_retires_only_changed_server(reconciler, monkeypatch, tmp_path):
    """Only the server whose connection identity changed loses its session."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")
    session_b, _loop_b, owner_b, _close_b = _entry(pool, "B")
    published = cache_module._mcp_tools_cache

    _write_config(cfg, {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is not binding_a
    assert _binding(pool, "A").epoch > binding_a.epoch
    assert _binding(pool, "B") is binding_b
    assert _entry(pool, "B")[0] is session_b
    assert _entry(pool, "B")[2] is owner_b
    assert log["created"]["cmd-B"] == 1

    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert log["exited"].get("cmd-B") is None

    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None
    assert published is not None


@pytest.mark.asyncio
async def test_metadata_only_change_rebuilds_tools_without_retiring_sessions(reconciler, monkeypatch, tmp_path):
    """Presentation-only fields rebuild tools but never the session."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")
    session_a, _l, owner_a, _c = _entry(pool, "A")
    generation = cache_module._cache_generation

    for field, value in (("description", "renamed"), ("routing", {"mode": "prefer", "priority": 5}), ("tool_name_prefix", False)):
        _write_config(cfg, {"A": _stdio("cmd-A", **{field: value}), "B": _stdio("cmd-B")})
        assert cache_module.refresh_mcp_cache_if_active() is True

        assert session_pool_module.get_session_pool() is pool
        assert _binding(pool, "A") is binding_a
        assert _binding(pool, "B") is binding_b
        assert _entry(pool, "A")[0] is session_a
        assert _entry(pool, "A")[2] is owner_a
        assert log["exited"] == {}
        assert cache_module._cache_generation == generation + 1
        assert cache_module._cache_initialized is False
        generation += 1


@pytest.mark.asyncio
async def test_declaration_order_change_does_not_retire_sessions(reconciler, monkeypatch, tmp_path):
    """Reordering servers rebuilds the tool catalogue but not the sessions."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")

    _write_config(cfg, {"B": _stdio("cmd-B"), "A": _stdio("cmd-A")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert _binding(pool, "A") is binding_a
    assert _binding(pool, "B") is binding_b
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_disabling_a_server_tombstones_only_that_server(reconciler, monkeypatch, tmp_path):
    """A disabled/removed server gets a tombstone; its peer is untouched."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_b = _binding(pool, "B")

    _write_config(cfg, {"A": {**_stdio("cmd-A"), "enabled": False}, "B": _stdio("cmd-B")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A").fingerprint is None
    assert _binding(pool, "B") is binding_b
    assert _entry(pool, "B") is not None
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert log["exited"].get("cmd-B") is None

    # Deleting the entry entirely must behave identically.
    _write_config(cfg, {"B": _stdio("cmd-B")})
    assert _binding(pool, "A").fingerprint is None


@pytest.mark.asyncio
async def test_disabling_the_last_server_retires_without_pool_swap(reconciler, monkeypatch, tmp_path):
    """Emptying the server list still retires the last binding, same pool."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    _write_config(cfg, {})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A").fingerprint is None
    assert cache_module._cache_initialized is False
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)


@pytest.mark.asyncio
async def test_new_server_gets_a_binding_while_others_are_preserved(reconciler, monkeypatch, tmp_path):
    """An added stdio server installs a fresh epoch; peers keep theirs."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")

    _write_config(cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B"), "C": _stdio("cmd-C")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert _binding(pool, "A") is binding_a
    assert _binding(pool, "B") is binding_b
    assert _binding(pool, "C").fingerprint == _fingerprint({"C": _stdio("cmd-C")}, "C")
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_stdio_to_http_transition_tombstones_only_changed_server(reconciler, monkeypatch, tmp_path):
    """A stdio server turned into HTTP retires its subprocess only."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)

    binding_b = _binding(pool, "B")

    _write_config(cfg, {"A": _http("https://example.test/a"), "B": _stdio("cmd-B")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert _binding(pool, "A").fingerprint is None
    assert _binding(pool, "B") is binding_b
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert log["exited"].get("cmd-B") is None


@pytest.mark.asyncio
async def test_http_to_stdio_transition_installs_new_binding(reconciler, monkeypatch, tmp_path):
    """An HTTP server turned into stdio gets a stdio binding epoch."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _http("https://example.test/a")}, log)
    assert ("deployment", "A") not in pool._bindings

    _write_config(cfg, {"A": _stdio("cmd-A")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A")}, "A")


@pytest.mark.asyncio
async def test_http_only_change_does_not_retire_stdio_sessions(reconciler, monkeypatch, tmp_path):
    """HTTP/SSE edits rebuild tools but never retire a stdio session."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A"), "H": _http("https://example.test/one")}, log)

    binding_a = _binding(pool, "A")
    session_a, _l, owner_a, _c = _entry(pool, "A")

    _write_config(cfg, {"A": _stdio("cmd-A"), "H": _http("https://example.test/two")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is binding_a
    assert _entry(pool, "A")[0] is session_a
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_skills_only_change_is_a_noop(reconciler, monkeypatch, tmp_path):
    """Skills/middleware edits are invisible to the MCP slice."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log, skills={"skill-a": {"enabled": True}})

    binding_a = _binding(pool, "A")
    generation = cache_module._cache_generation
    published = cache_module._mcp_tools_cache

    _write_config(cfg, {"A": _stdio("cmd-A")}, skills={"skill-a": {"enabled": False}})
    assert cache_module.refresh_mcp_cache_if_active() is False

    assert cache_module.get_cached_mcp_tools() is published
    assert _binding(pool, "A") is binding_a
    assert log["exited"] == {}
    assert cache_module._cache_generation == generation
    assert cache_module._config_signature == get_config_signature(cfg)


@pytest.mark.asyncio
async def test_equivalent_transport_alias_is_a_noop(reconciler, monkeypatch, tmp_path):
    """``type=stdio`` and ``transport=stdio`` are the same connection."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    binding_a = _binding(pool, "A")
    generation = cache_module._cache_generation

    _write_config(cfg, {"A": {"enabled": True, "transport": "stdio", "command": "cmd-A"}})
    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_a
    assert cache_module._cache_generation == generation


@pytest.mark.asyncio
async def test_path_switch_with_equivalent_config_keeps_bindings(reconciler, monkeypatch, tmp_path):
    """An equivalent MCP slice in another file is not an invalidation."""
    cfg_a = tmp_path / "a.json"
    cfg_b = tmp_path / "b.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg_a, {"A": _stdio("cmd-A")}, log)
    _write_config(cfg_b, {"A": _stdio("cmd-A")}, skills={"other": {"enabled": True}})

    binding_a = _binding(pool, "A")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg_b))

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_a
    assert cache_module._config_path == cfg_b
    assert cache_module._config_signature == get_config_signature(cfg_b)
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_path_switch_with_changed_connection_retires_changed_server(reconciler, monkeypatch, tmp_path):
    """A path switch that really changes a connection still retires it."""
    cfg_a = tmp_path / "a.json"
    cfg_b = tmp_path / "b.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg_a, {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}, log)
    _write_config(cfg_b, {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B")})

    binding_b = _binding(pool, "B")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg_b))

    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "B") is binding_b
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)


@pytest.mark.asyncio
async def test_interceptor_change_falls_back_to_full_reset(reconciler, monkeypatch, tmp_path):
    """A global interceptor change keeps the conservative full reset."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log, interceptors=["pkg.a:build"])

    _write_config(cfg, {"A": _stdio("cmd-A")}, interceptors=["pkg.b:build"])
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is not pool
    assert cache_module._applied_mcp_revision is None
    assert cache_module._cache_initialized is False


@pytest.mark.asyncio
async def test_disabled_server_edit_is_a_noop(reconciler, monkeypatch, tmp_path):
    """Editing a disabled server never touches an active session."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(
        monkeypatch,
        cfg,
        {"A": _stdio("cmd-A"), "D": {**_stdio("cmd-D"), "enabled": False}},
        log,
    )

    binding_a = _binding(pool, "A")
    _write_config(cfg, {"A": _stdio("cmd-A"), "D": {**_stdio("cmd-D2"), "enabled": False}})

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_a
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_repeated_identical_revision_does_not_retire_again(reconciler, monkeypatch, tmp_path):
    """Applying the same revision twice is idempotent."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    binding_after_first = _binding(pool, "A")
    generation = cache_module._cache_generation

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_after_first
    assert cache_module._cache_generation == generation
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert log["exited"]["cmd-A"] == 1


@pytest.mark.asyncio
async def test_committed_delete_then_identical_readd_installs_a_new_epoch(reconciler, monkeypatch, tmp_path):
    """The committed handoff must not coalesce a delete/readd back to one revision."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    servers = {"A": _stdio("cmd-A")}
    await _initialize(monkeypatch, cfg, servers, log)

    old_binding = _binding(pool, "A")
    old_entry = _entry(pool, "A")
    assert old_entry is not None
    old_cm = log["cms"]["cmd-A"][0]
    assert old_cm.closed is False

    _write_config(cfg, {})
    deleted = ExtensionsConfig.from_file(str(cfg))
    cache_module.finish_mcp_reconciliation(cache_module.prepare_mcp_reconciliation(deleted, config_path=cfg))
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert old_cm.closed is True

    _write_config(cfg, servers)
    readded = ExtensionsConfig.from_file(str(cfg))
    cache_module.finish_mcp_reconciliation(cache_module.prepare_mcp_reconciliation(readded, config_path=cfg))

    new_binding = _binding(pool, "A")
    assert new_binding.epoch > old_binding.epoch
    with pytest.raises(StaleMCPBindingError):
        await pool.get_session("A", "u:t", servers["A"], binding=old_binding)


@pytest.mark.asyncio
async def test_committed_handoff_tombstones_durable_only_binding_without_cache(reconciler, tmp_path):
    """A pre-discovery durable binding is local state even when tools never published."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    pool.ensure_binding(
        "A",
        _fingerprint({"A": _stdio("cmd-A")}, "A"),
        domain="deployment",
    )
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None

    _write_config(cfg, {})
    committed = ExtensionsConfig.from_file(str(cfg))
    cache_module.finish_mcp_reconciliation(cache_module.prepare_mcp_reconciliation(committed, config_path=cfg))

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A").fingerprint is None


@pytest.mark.asyncio
async def test_committed_handoff_reconciles_every_changed_server_in_one_revision(reconciler, monkeypatch, tmp_path):
    """A multi-server commit reconciles the whole effective diff, not just one name."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(
        monkeypatch,
        cfg,
        {"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1"), "C": _stdio("cmd-C1")},
        log,
    )

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")
    binding_c = _binding(pool, "C")
    session_c = _entry(pool, "C")[0]
    owner_c = _entry(pool, "C")[2]

    _write_config(
        cfg,
        {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B2"), "C": _stdio("cmd-C1")},
    )
    committed = ExtensionsConfig.from_file(str(cfg))
    cache_module.finish_mcp_reconciliation(cache_module.prepare_mcp_reconciliation(committed, config_path=cfg))

    assert _binding(pool, "A").epoch > binding_a.epoch
    assert _binding(pool, "B").epoch > binding_b.epoch
    assert _binding(pool, "C") is binding_c
    assert _entry(pool, "C")[0] is session_c
    assert _entry(pool, "C")[2] is owner_c


# ---------------------------------------------------------------------------
# Applied baseline and state machine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_records_matching_published_and_applied_baselines(reconciler, monkeypatch, tmp_path):
    """The applied revision and the published snapshot describe one revision."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    baseline = cache_module._applied_mcp_revision
    assert baseline is not None
    assert baseline.effective_snapshot == cache_module._mcp_config_snapshot
    assert baseline.stdio_connections == {"A": _fingerprint({"A": _stdio("cmd-A")}, "A")}


@pytest.mark.asyncio
async def test_metadata_only_change_keeps_the_applied_stdio_baseline(reconciler, monkeypatch, tmp_path):
    """Rebuilding tools must not throw the binding baseline away."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    before = cache_module._applied_mcp_revision
    _write_config(cfg, {"A": _stdio("cmd-A", description="renamed")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    after = cache_module._applied_mcp_revision
    assert after is not None
    assert after.stdio_connections == before.stdio_connections
    assert after.effective_snapshot != before.effective_snapshot


@pytest.mark.asyncio
async def test_consecutive_connection_changes_keep_advancing_the_baseline(reconciler, monkeypatch, tmp_path):
    """V1 -> v2 -> v3 advances every epoch with no publish in between."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    epochs = [_binding(pool, "A").epoch]
    assert cache_module._cache_initialized is True

    for command in ("cmd-A2", "cmd-A3"):
        _write_config(cfg, {"A": _stdio(command)})
        assert cache_module.refresh_mcp_cache_if_active() is True
        epochs.append(_binding(pool, "A").epoch)
        # The tool cache never republishes between the transitions.
        assert cache_module._cache_initialized is False
        assert cache_module._mcp_tools_cache is None
        assert session_pool_module.get_session_pool() is pool

    assert epochs == sorted(set(epochs)) and len(epochs) == 3
    assert cache_module._applied_mcp_revision.stdio_connections["A"] == _fingerprint({"A": _stdio("cmd-A3")}, "A")
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A3")}, "A")


@pytest.mark.asyncio
async def test_returning_to_the_same_fingerprint_still_advances_the_epoch(reconciler, monkeypatch, tmp_path):
    """A(v1) -> A(v2) -> A(v1) is three transitions, not an ABA no-op."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    original = _binding(pool, "A")
    first_fingerprint = original.fingerprint

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    middle = _binding(pool, "A")

    _write_config(cfg, {"A": _stdio("cmd-A1")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    restored = _binding(pool, "A")

    assert restored.fingerprint == first_fingerprint
    assert restored is not original
    assert restored.epoch > middle.epoch > original.epoch


@pytest.mark.asyncio
async def test_two_successive_transitions_touch_only_their_own_server(reconciler, monkeypatch, tmp_path):
    """A then B advance independently; C is never rebuilt."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    servers = {"A": _stdio("cmd-A"), "B": _stdio("cmd-B"), "C": _stdio("cmd-C")}
    await _initialize(monkeypatch, cfg, servers, log)

    binding_b = _binding(pool, "B")
    binding_c = _binding(pool, "C")
    session_c, _l, owner_c, _e = _entry(pool, "C")

    _write_config(cfg, {**servers, "A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert _binding(pool, "B") is binding_b

    _write_config(cfg, {**servers, "A": _stdio("cmd-A2"), "B": _stdio("cmd-B2")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert _binding(pool, "C") is binding_c
    assert _entry(pool, "C")[0] is session_c
    assert _entry(pool, "C")[2] is owner_c
    await _wait_until(lambda: log["exited"].get("cmd-A") == 1 and log["exited"].get("cmd-B") == 1)
    assert log["exited"].get("cmd-C") is None


@pytest.mark.asyncio
async def test_failed_first_discovery_leaves_a_reconcilable_residual(reconciler, monkeypatch, tmp_path):
    """A residual binding from a failed discovery is repaired in place."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _record_sessions(monkeypatch, log)
    _install_discovery(monkeypatch, fail_after_bindings=True)

    with pytest.raises(RuntimeError):
        await cache_module.initialize_mcp_tools()

    assert cache_module._cache_initialized is False
    residual = _binding(pool, "A")
    assert residual.fingerprint == _fingerprint({"A": _stdio("cmd-A1")}, "A")
    assert cache_module._applied_mcp_revision is not None

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is not residual

    _install_discovery(monkeypatch)
    published = await cache_module.initialize_mcp_tools()
    assert [tool.name for tool in published] == ["A"]
    assert cache_module._cache_initialized is True
    assert _entry(pool, "A") is not None


@pytest.mark.asyncio
async def test_removed_server_without_published_tools_gets_a_tombstone(reconciler, monkeypatch, tmp_path):
    """An unpublished residual binding is still tombstoned on removal."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _record_sessions(monkeypatch, log)
    _install_discovery(monkeypatch, fail_after_bindings=True)

    with pytest.raises(RuntimeError):
        await cache_module.initialize_mcp_tools()

    _write_config(cfg, {})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A").fingerprint is None


@pytest.mark.asyncio
async def test_personal_domain_binding_is_never_touched(reconciler, monkeypatch, tmp_path):
    """Deployment/A changes cannot retire personal/A."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A")}, log)

    personal_binding = pool.ensure_binding("A", "personal-fingerprint", domain="personal")
    personal_session = await pool.get_session(
        "A",
        "u:t",
        {"transport": "stdio", "command": "cmd-personal-A"},
        binding=personal_binding,
    )

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session
    assert log["exited"].get("cmd-personal-A") is None
    assert pool._bindings[("deployment", "A")].fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")


def test_never_initialized_process_pays_no_config_read(reconciler, monkeypatch):
    """No published/applied/in-flight state means no config read at all."""
    reads: list[str] = []
    monkeypatch.setattr(cache_module, "_current_config_state", lambda: reads.append("stat") or (None, None))

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert cache_module._is_cache_stale() is False
    assert reads == []


@pytest.mark.asyncio
async def test_failed_reconciliation_does_not_commit_a_new_baseline(reconciler, monkeypatch, tmp_path):
    """A raising transition leaves the applied state untouched and retryable."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    baseline = cache_module._applied_mcp_revision
    binding_before = _binding(pool, "A")

    real_reconcile = pool.reconcile_bindings
    fail_next = {"armed": True}

    def _maybe_fail(active, removed, *, domain="deployment"):
        if fail_next["armed"]:
            fail_next["armed"] = False
            raise RuntimeError("reconcile failed")
        return real_reconcile(active, removed, domain=domain)

    monkeypatch.setattr(pool, "reconcile_bindings", _maybe_fail)
    _write_config(cfg, {"A": _stdio("cmd-A2")})

    with pytest.raises(RuntimeError):
        cache_module.refresh_mcp_cache_if_active()

    assert cache_module._applied_mcp_revision is baseline
    assert _binding(pool, "A") is binding_before
    assert cache_module._cache_initialized is True

    # Retrying converges instead of being stuck behind the failed attempt.
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert cache_module._applied_mcp_revision is not baseline
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")


# ---------------------------------------------------------------------------
# Deterministic concurrency and failure recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superseded_discovery_result_is_fenced_during_flight(reconciler, monkeypatch, tmp_path):
    """A discovery superseded mid-flight must not publish stale tools."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _park(servers, active_pool, bindings):
        entered.set()
        await release.wait()

    _install_discovery(monkeypatch, after_bindings=_park)

    owner = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 1)

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    binding_after = _binding(pool, "A")

    release.set()
    assert await asyncio.wait_for(owner, 5) == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None
    assert _binding(pool, "A") is binding_after
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")

    # A direct retry must succeed without any extra lazy refresh.
    _install_discovery(monkeypatch)
    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)
    assert [tool.name for tool in published] == ["A"]
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
async def test_late_binding_seed_cannot_resurrect_a_superseded_revision(reconciler, monkeypatch, tmp_path):
    """A stale revision that installs its binding last is still rejected."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _park_before_bindings(servers, active_pool):
        entered.set()
        await release.wait()

    _install_discovery(monkeypatch, before_bindings=_park_before_bindings)

    owner = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 1)

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    binding_after = _binding(pool, "A")

    release.set()
    assert await asyncio.wait_for(owner, 5) == []

    # The superseded discovery never seeded its own (v1) binding.
    assert _binding(pool, "A") is binding_after
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")
    assert cache_module._cache_initialized is False

    _install_discovery(monkeypatch)
    assert [tool.name for tool in await cache_module.initialize_mcp_tools()] == ["A"]
    assert cache_module._cache_initialized is True
    assert log["created"].get("cmd-A2") == 1


@pytest.mark.asyncio
async def test_repeated_supersession_never_regresses_the_applied_state(reconciler, monkeypatch, tmp_path):
    """V2 and v3 land while the v1 discovery is still parked."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _park_before_bindings(servers, active_pool):
        entered.set()
        await release.wait()

    _install_discovery(monkeypatch, before_bindings=_park_before_bindings)

    owner = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 1)

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    _write_config(cfg, {"A": _stdio("cmd-A3")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    release.set()
    assert await asyncio.wait_for(owner, 5) == []

    expected = _fingerprint({"A": _stdio("cmd-A3")}, "A")
    assert cache_module._applied_mcp_revision.stdio_connections["A"] == expected
    assert _binding(pool, "A").fingerprint == expected
    assert cache_module._cache_initialized is False


@pytest.mark.asyncio
async def test_concurrent_reconcilers_serialize_read_and_apply(reconciler, monkeypatch, tmp_path):
    """A second reader cannot classify or apply while the first transition runs."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    real_reconcile = pool.reconcile_bindings
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _slow_reconcile(active, removed, *, domain="deployment"):
        calls.append("enter")
        entered.set()
        release.wait(timeout=5)
        result = real_reconcile(active, removed, domain=domain)
        calls.append("exit")
        return result

    monkeypatch.setattr(pool, "reconcile_bindings", _slow_reconcile)
    _write_config(cfg, {"A": _stdio("cmd-A2")})

    results: dict[str, bool] = {}
    first = threading.Thread(target=lambda: results.__setitem__("first", cache_module.refresh_mcp_cache_if_active()))
    second_attempted = threading.Event()

    def _second():
        second_attempted.set()
        results["second"] = cache_module.refresh_mcp_cache_if_active()

    second = threading.Thread(target=_second)

    first.start()
    assert entered.wait(timeout=5), "first reconciler never installed the epoch"
    second.start()
    assert second_attempted.wait(timeout=5)
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    # Exactly one transition ran: the second reader observed the revision the
    # first had already applied and therefore never classified a second time.
    assert calls == ["enter", "exit"]
    assert results == {"first": True, "second": False}
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")
    assert cache_module._applied_mcp_revision.stdio_connections["A"] == _fingerprint({"A": _stdio("cmd-A2")}, "A")


@pytest.mark.asyncio
async def test_slow_teardown_does_not_block_reconciling_another_server(reconciler, monkeypatch, tmp_path):
    """A parked in __aexit__ must not hold up B's reconciliation."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    exit_gate = asyncio.Event()
    log = _session_log()
    log["exit_gate"] = exit_gate
    servers = {"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1"), "C": _stdio("cmd-C1")}
    await _initialize(monkeypatch, cfg, servers, log)

    binding_c = _binding(pool, "C")

    try:
        _write_config(cfg, {**servers, "A": _stdio("cmd-A2")})
        assert cache_module.refresh_mcp_cache_if_active() is True
        await _wait_until(lambda: log["exit_started"].get("cmd-A1") == 1)

        # A's owner is now parked inside __aexit__; B's transition must still finish.
        _write_config(cfg, {**servers, "A": _stdio("cmd-A2"), "B": _stdio("cmd-B2")})
        assert cache_module.refresh_mcp_cache_if_active() is True
        assert _binding(pool, "B").fingerprint == _fingerprint({"B": _stdio("cmd-B2")}, "B")
        assert _binding(pool, "C") is binding_c
        assert cache_module._applied_mcp_revision.stdio_connections["B"] == _fingerprint({"B": _stdio("cmd-B2")}, "B")
    finally:
        # Never leave an owner parked in __aexit__: the loop shutdown would
        # block cancelling it and mask the real assertion failure.
        exit_gate.set()

    await _wait_until(
        lambda: log["exited"].get("cmd-A1") == 1 and log["exited"].get("cmd-B1") == 1,
        message="both retired owners must finish exactly once",
    )
    assert log["exited"]["cmd-A1"] == 1
    assert log["exited"]["cmd-B1"] == 1
    assert log["exited"].get("cmd-C1") is None


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_drop_a_handed_off_teardown(reconciler, monkeypatch, tmp_path):
    """An already-installed epoch keeps its owner cleanup."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1")}, log)

    _write_config(cfg, {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B1")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    owner = asyncio.create_task(asyncio.sleep(0))
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    await _wait_until(lambda: log["exited"].get("cmd-A1") == 1)
    assert log["exited"]["cmd-A1"] == 1
    assert log["exited"].get("cmd-B1") is None


@pytest.mark.asyncio
async def test_cancelled_initializer_keeps_its_baseline_for_the_successor(reconciler, monkeypatch, tmp_path):
    """Cancelling discovery must not strand a residual or a stale claim."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    started = asyncio.Event()
    release = asyncio.Event()

    async def _park(servers, active_pool, bindings):
        started.set()
        await release.wait()

    _install_discovery(monkeypatch, after_bindings=_park)

    owner = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(started.wait(), 1)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert cache_module._initializing_generation is None

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert cache_module._applied_mcp_revision.stdio_connections["A"] == _fingerprint({"A": _stdio("cmd-A2")}, "A")

    _install_discovery(monkeypatch)
    assert [tool.name for tool in await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)] == ["A"]
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
async def test_shared_reset_outranks_selective_reconciliation(reconciler, monkeypatch, tmp_path):
    """A shared reset must stay a full reset, never a selective one."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1")}, log)

    # A would be selectively reconciled, but a reset marker published by another
    # worker arrives in the same window and must take precedence.
    _write_config(cfg, {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B1")})
    _write_remote_marker(cfg, "remote-worker-reset")
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is not pool
    assert pool._retired is True
    assert cache_module._applied_mcp_revision is None
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_config_snapshot is None


@pytest.mark.asyncio
async def test_stale_wrapper_cannot_open_a_session_after_reconciliation(reconciler, monkeypatch, tmp_path):
    """The pre-change binding capability is fenced by the pool's check."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    stale_binding = _binding(pool, "A")
    created_before = log["created"]["cmd-A1"]

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    with pytest.raises(StaleMCPBindingError):
        await pool.get_session(
            "A",
            "u:t",
            {"transport": "stdio", "command": "cmd-A1"},
            binding=stale_binding,
        )
    assert log["created"]["cmd-A1"] == created_before


# ---------------------------------------------------------------------------
# Failure modes and conservative uncertainty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_config_falls_back_to_a_full_reset(reconciler, monkeypatch, tmp_path):
    """An unparseable existing config is never treated as unchanged."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    cfg.write_text("{not json", encoding="utf-8")
    assert cache_module._is_cache_stale() is True
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is not pool
    assert cache_module._applied_mcp_revision is None


@pytest.mark.asyncio
async def test_unverifiable_signature_is_never_adopted(reconciler, monkeypatch, tmp_path):
    """A signature without a digest cannot prove the revision is unchanged."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    real = cache_module._get_config_signature

    def _no_digest(path):
        signature = real(path)
        return None if signature is None else (signature[0], signature[1], None)

    monkeypatch.setattr(cache_module, "_get_config_signature", _no_digest)

    assert cache_module._is_cache_stale() is True
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is not pool


@pytest.mark.asyncio
async def test_config_deleted_after_load_keeps_last_known_good_tools(reconciler, monkeypatch, tmp_path):
    """The fail-soft contract for a deleted config survives reconciliation."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    published = await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    cfg.unlink()
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: cfg),
    )

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert cache_module._is_cache_stale() is False
    assert session_pool_module.get_session_pool() is pool
    assert cache_module.get_cached_mcp_tools() is published
    assert log["exited"] == {}


@pytest.mark.asyncio
async def test_discovery_failure_does_not_lock_the_generation_claim(reconciler, monkeypatch, tmp_path):
    """A non-stale discovery error is surfaced but leaves the cache retryable."""
    from deerflow.mcp import tools as tools_module

    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    async def _boom(**_kwargs):
        raise RuntimeError("discovery failed")

    monkeypatch.setattr(tools_module, "get_mcp_tools", _boom)
    with pytest.raises(RuntimeError):
        await cache_module.initialize_mcp_tools()

    assert cache_module._initializing_generation is None
    assert cache_module._cache_initialized is False

    _record_sessions(monkeypatch, log)
    _install_discovery(monkeypatch)
    assert [tool.name for tool in await cache_module.initialize_mcp_tools()] == ["A"]
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
async def test_stale_binding_error_without_supersession_is_not_swallowed(reconciler, monkeypatch, tmp_path):
    """A binding conflict on a still-valid pool stays a real error."""
    from deerflow.mcp import tools as tools_module

    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    async def _conflict(**_kwargs):
        raise StaleMCPBindingError("A")

    monkeypatch.setattr(tools_module, "get_mcp_tools", _conflict)

    with pytest.raises(StaleMCPBindingError):
        await cache_module.initialize_mcp_tools()
    assert cache_module._initializing_generation is None


@pytest.mark.asyncio
async def test_applied_baseline_never_carries_resolved_credentials(reconciler, monkeypatch, tmp_path):
    """The connection-identity baseline exposes no resolved credentials.

    ``effective_snapshot`` necessarily holds the resolved MCP slice (it is the
    same string the published baseline records), so it is excluded from repr to
    keep an accidental log line from leaking ``$VAR`` values; the digest map and
    interceptor list stay inspectable.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    monkeypatch.setenv("MCP_TOKEN", "TOPSECRET123")

    await _initialize(
        monkeypatch,
        cfg,
        {"A": _stdio("cmd-A1", env={"TOKEN": "$MCP_TOKEN"})},
        log,
    )

    baseline = cache_module._applied_mcp_revision
    assert baseline is not None
    assert "TOPSECRET123" not in repr(baseline)
    assert all(len(digest) == 64 for digest in baseline.stdio_connections.values())


# ---------------------------------------------------------------------------
# Claimed-revision recovery and reset precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claimed_revision_reconciles_a_preexisting_stale_binding(reconciler, monkeypatch, tmp_path):
    """A binding installed outside the cache must not block the first discovery.

    Durable-task callers bind a stdio server from the config revision *they*
    read, so the pool can already hold ``A(v1)`` when discovery starts against
    ``A(v2)``. Recording an applied baseline for v2 therefore cannot stand in for
    installing its epoch: ``ensure_binding()`` fails closed on a differing
    fingerprint, and with no later config change the observed revision would
    always equal the recorded baseline, so nothing would ever reconcile and the
    cache could never publish again.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    # A durable task call binds A(v1) before the tool cache ever initialized.
    stale = pool.ensure_binding("A", _fingerprint({"A": _stdio("cmd-A1")}, "A"), domain="deployment")
    await pool.get_session("A", "task:1", {"transport": "stdio", "command": "cmd-A1"}, binding=stale)
    assert log["created"]["cmd-A1"] == 1

    _write_config(cfg, {"A": _stdio("cmd-A2")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)

    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["A"]
    assert cache_module._cache_initialized is True
    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is not stale
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A2")}, "A")
    assert _entry(pool, "A") is not None
    assert log["created"]["cmd-A2"] == 1
    await _wait_until(lambda: log["exited"].get("cmd-A1") == 1)
    assert log["exited"].get("cmd-A2") is None


@pytest.mark.asyncio
async def test_unpublished_deployment_cache_never_retires_personal_sessions(reconciler, monkeypatch, tmp_path):
    """Deployment recovery stays inside the deployment ownership domain."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    personal_binding = pool.ensure_binding("A", "personal-fingerprint", domain="personal")
    personal_session = await pool.get_session(
        "A",
        "u:t",
        {"transport": "stdio", "command": "cmd-personal-A"},
        binding=personal_binding,
    )

    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    # No deployment cache, no applied baseline and no discovery: a deployment
    # config change is not a reason to touch the shared pool at all.
    assert cache_module.refresh_mcp_cache_if_active() is False
    assert session_pool_module.get_session_pool() is pool

    # The first deployment discovery reconciles only deployment bindings.
    _install_discovery(monkeypatch)
    published = await cache_module.initialize_mcp_tools()
    assert [tool.name for tool in published] == ["A"]
    assert _binding(pool, "A").fingerprint == _fingerprint({"A": _stdio("cmd-A1")}, "A")
    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session

    # And so does every later deployment-only transition.
    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert session_pool_module.get_session_pool() is pool
    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session
    assert log["exited"].get("cmd-personal-A") is None
    await _wait_until(lambda: log["exited"].get("cmd-A1") == 1)


@pytest.mark.asyncio
async def test_shared_reset_during_discovery_fences_the_selective_commit(reconciler, monkeypatch, tmp_path):
    """A shared reset must not be re-authorized by an in-flight reconciliation.

    Forced ordering: a reader claims revision v2 and parks; another worker
    publishes a reset marker and completes the reset; the parked reader then
    resumes and tries to install its epoch and publish. It must be refused, the
    retired pool must stay retired, and the reset marker must not be recorded as
    already handled.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1")}, log)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _park(servers, active_pool):
        entered.set()
        await release.wait()

    # v2 is observed and applied, then a discovery for v2 parks mid-flight.
    _write_config(cfg, {"A": _stdio("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    _install_discovery(monkeypatch, before_bindings=_park)
    claim = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 1)

    # Another worker publishes a reset generation and this process resets fully.
    marker_path = cache_module._cache_reset_marker_path(cfg)
    assert cache_module.publish_mcp_tools_cache_reset() is not None
    assert session_pool_module.get_session_pool() is not pool
    assert cache_module._applied_mcp_revision is None

    release.set()
    assert await asyncio.wait_for(claim, 5) == []

    # The stale claim neither revived the retired pool nor swallowed the reset.
    assert pool._retired is True
    assert session_pool_module.get_session_pool() is not pool
    assert cache_module._cache_reset_marker_signature is None
    assert cache_module._applied_mcp_revision is None
    assert cache_module._cache_initialized is False

    # A fresh initialization adopts the *new* marker generation.
    _install_discovery(monkeypatch)
    assert [tool.name for tool in await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)] == ["A"]
    assert cache_module._cache_reset_marker_signature == get_config_signature(marker_path)


@pytest.mark.asyncio
async def test_shared_reset_published_before_a_claim_is_not_swallowed(reconciler, monkeypatch, tmp_path):
    """A reset that lands between the staleness check and the claim still retires.

    A selective transition legitimately keeps an unaffected server's session, so
    the next claim is the first place a shared reset generation published in that
    window can be observed. Recording its marker without retiring the pool would
    swallow the reset and keep serving a session from before it.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    await _initialize(monkeypatch, cfg, {"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1")}, log)
    binding_b = _binding(pool, "B")

    # A(v2) is applied selectively, so B keeps its session and the tool cache is
    # empty; this leaves no published baseline to re-check the marker against.
    _write_config(cfg, {"A": _stdio("cmd-A2"), "B": _stdio("cmd-B1")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert _binding(pool, "B") is binding_b
    assert _entry(pool, "B") is not None

    marker_path = _write_remote_marker(cfg, "reset-arrived-before-claim")
    _install_discovery(monkeypatch)

    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["A", "B"]
    assert cache_module._cache_initialized is True
    # The reset retired the pool that still held B, instead of being adopted.
    assert pool._retired is True
    assert session_pool_module.get_session_pool() is not pool
    await _wait_until(lambda: log["exited"].get("cmd-B1") == 1)
    assert cache_module._cache_reset_marker_signature == get_config_signature(marker_path)


@pytest.mark.asyncio
async def test_first_claim_tombstones_a_deployment_binding_the_config_dropped(reconciler, monkeypatch, tmp_path):
    """With no applied baseline, a retained deployment binding is still retired.

    After a restart the applied baseline is empty, so a durable-task caller's
    binding is the only record that a server exists. When the first revision that
    is ever claimed no longer declares that server, it must still be tombstoned
    (and never a personal-domain binding of the same name).
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    stale = pool.ensure_binding("A", _fingerprint({"A": _stdio("cmd-A1")}, "A"), domain="deployment")
    await pool.get_session("A", "task:1", {"transport": "stdio", "command": "cmd-A1"}, binding=stale)
    personal_binding = pool.ensure_binding("A", "personal-fingerprint", domain="personal")
    personal_session = await pool.get_session(
        "A",
        "u:t",
        {"transport": "stdio", "command": "cmd-personal-A"},
        binding=personal_binding,
    )

    # The first revision this process ever claims declares B, not A.
    _write_config(cfg, {"B": _stdio("cmd-B1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)

    assert cache_module._applied_mcp_revision is None
    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["B"]
    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is not stale
    assert _binding(pool, "A").fingerprint is None
    assert _binding(pool, "B").fingerprint == _fingerprint({"B": _stdio("cmd-B1")}, "B")
    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session
    assert log["exited"].get("cmd-personal-A") is None
    await _wait_until(lambda: log["exited"].get("cmd-A1") == 1)


@pytest.mark.asyncio
async def test_shared_reset_retires_a_durable_only_deployment_session(reconciler, monkeypatch, tmp_path):
    """A shared reset retires durable-only deployment state, not just cache state.

    Durable-task callers may install a deployment binding and hold a persistent
    session before this process ever publishes an MCP tool cache, so neither
    ``_cache_initialized`` nor an applied baseline records it. A reset generation
    published in that state must still retire the session instead of being
    adopted as already handled.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    durable = pool.ensure_binding("A", _fingerprint({"A": _stdio("cmd-A1")}, "A"), domain="deployment")
    await pool.get_session("A", "task:1", {"transport": "stdio", "command": "cmd-A1"}, binding=durable)
    assert cache_module._cache_initialized is False
    assert cache_module._applied_mcp_revision is None

    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    marker_path = _write_remote_marker(cfg, "reset-before-first-claim")
    _install_discovery(monkeypatch)

    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["A"]
    assert pool._retired is True
    assert session_pool_module.get_session_pool() is not pool
    await _wait_until(lambda: log["exited"].get("cmd-A1") == 1)
    assert cache_module._cache_reset_marker_signature == get_config_signature(marker_path)
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
async def test_shared_reset_with_only_personal_state_is_adopted_without_a_reset(reconciler, monkeypatch, tmp_path):
    """Personal-domain state alone must not turn a shared reset into a full reset.

    The deployment-domain reset decision stays inside its own domain: a process
    whose only pooled state is personal has nothing for a deployment-side reset to
    retire, so it adopts the observed generation and keeps the personal session.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    personal_binding = pool.ensure_binding("A", "personal-fingerprint", domain="personal")
    personal_session = await pool.get_session(
        "A",
        "u:t",
        {"transport": "stdio", "command": "cmd-personal-A"},
        binding=personal_binding,
    )

    _write_config(cfg, {"A": _stdio("cmd-A1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    marker_path = _write_remote_marker(cfg, "reset-with-personal-only-state")
    _install_discovery(monkeypatch)

    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["A"]
    assert session_pool_module.get_session_pool() is pool
    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session
    assert log["exited"] == {}
    assert cache_module._cache_reset_marker_signature == get_config_signature(marker_path)


@pytest.mark.asyncio
async def test_first_claim_atomically_tombstones_a_concurrently_retained_server(reconciler, monkeypatch, tmp_path):
    """Enumerating and applying the first-claim tombstones must be one pool-lock step.

    A durable-task caller never takes the cache lock, so it can install a binding
    for a server the current revision does not declare after the cache listed the
    pool's retained names but before it applied the reconciliation. Computing the
    unlisted names inside the pool lock that installs the epochs closes that gap.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)

    personal_binding = pool.ensure_binding("A", "personal-fingerprint", domain="personal")
    personal_session = await pool.get_session(
        "A",
        "u:t",
        {"transport": "stdio", "command": "cmd-personal-A"},
        binding=personal_binding,
    )

    real_reconcile = pool.reconcile_bindings
    interleaved = {"done": False, "binding": None}

    def _reconcile_with_racing_retainer(active, removed, *, domain="deployment", retire_unlisted=False):
        if not interleaved["done"]:
            interleaved["done"] = True
            # The durable caller slips in after the cache listed the retained
            # names and before the reconciliation is applied.
            interleaved["binding"] = pool.ensure_binding(
                "A",
                _fingerprint({"A": _stdio("cmd-A1")}, "A"),
                domain="deployment",
            )
        kwargs = {"domain": domain}
        if retire_unlisted:
            kwargs["retire_unlisted"] = True
        return real_reconcile(active, removed, **kwargs)

    monkeypatch.setattr(pool, "reconcile_bindings", _reconcile_with_racing_retainer)
    _write_config(cfg, {"B": _stdio("cmd-B1")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)

    published = await asyncio.wait_for(cache_module.initialize_mcp_tools(), 5)

    assert [tool.name for tool in published] == ["B"]
    assert interleaved["done"] is True, "the racing durable binding was never installed"
    assert session_pool_module.get_session_pool() is pool
    # A was retained by the pool, is not declared by this revision, and the
    # enumerating + applying happened under one lock, so it is tombstoned.
    assert _binding(pool, "A") is not interleaved["binding"]
    assert _binding(pool, "A").fingerprint is None
    assert _binding(pool, "B").fingerprint == _fingerprint({"B": _stdio("cmd-B1")}, "B")
    # The in-lock enumeration stays domain-scoped.
    assert pool._bindings[("personal", "A")] is personal_binding
    assert _entry(pool, "A", domain="personal")[0] is personal_session
    assert log["exited"].get("cmd-personal-A") is None


@pytest.mark.asyncio
async def test_rejected_hot_change_keeps_background_task_callers_working(reconciler, monkeypatch, tmp_path):
    """A rejected hot reload must not fence the durable callers that still use it.

    Durable background calls resolve their connection from the configuration
    frozen at Gateway startup, so the moment a newer revision's binding epoch is
    installed every status/cancel call fails closed with ``StaleMCPBindingError``
    — even though the same revision is correctly rejected for hot reload. The
    rejection must therefore land *before* the epoch is installed.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    startup = {"A": _task_server("cmd-A1")}
    _freeze_task_snapshot(startup)
    await _initialize(monkeypatch, cfg, startup, log)

    startup_connection, startup_fingerprint = _startup_connection(startup, "A")

    _write_config(cfg, {"A": _task_server("cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    # The rejected revision never became the applied baseline...
    assert cache_module._applied_mcp_revision is None
    # ...so the background caller rebinds from its frozen startup configuration
    # instead of being fenced by an epoch it can never satisfy.
    active_pool = session_pool_module.get_session_pool()
    binding = active_pool.ensure_binding("A", startup_fingerprint, domain="deployment")
    session = await active_pool.get_session("A", "task:1", startup_connection, binding=binding)
    assert session is not None


@pytest.mark.asyncio
async def test_rejected_revision_installs_no_epoch_and_no_tombstone(reconciler, monkeypatch, tmp_path):
    """A claim must not touch the pool for a revision the frozen snapshot rejects.

    Covers both shapes of rejection: a changed connection (which would install a
    new epoch) and a disabled server (which would install a tombstone).
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    startup = {"A": _task_server("cmd-A1")}
    _freeze_task_snapshot(startup)
    startup_connection, startup_fingerprint = _startup_connection(startup, "A")

    durable = pool.ensure_binding("A", startup_fingerprint, domain="deployment")
    await pool.get_session("A", "task:1", startup_connection, binding=durable)

    revisions = (
        {"A": _task_server("cmd-A2")},
        {"A": {**_task_server("cmd-A1"), "enabled": False}},
    )
    for revised in revisions:
        _write_config(cfg, revised)
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
        _install_discovery(monkeypatch)

        with pytest.raises(McpTaskConfigurationError):
            await cache_module.initialize_mcp_tools()

        assert _binding(pool, "A") is durable
        assert _binding(pool, "A").fingerprint == startup_fingerprint
        assert cache_module._applied_mcp_revision is None
        assert cache_module._initializing_generation is None
        assert session_pool_module.get_session_pool() is pool

    # The frozen caller's session was never retired by a rejected revision, and
    # no rejected revision was published.
    assert log["exited"].get("cmd-A1") is None
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None

    # A corrected configuration recovers on the next attempt without a restart.
    _write_config(cfg, startup)
    published = await cache_module.initialize_mcp_tools()
    assert [tool.name for tool in published] == ["A"]
    assert cache_module._cache_initialized is True
    assert _binding(pool, "A") is durable
    assert session_pool_module.get_session_pool() is pool


@pytest.mark.asyncio
async def test_unrelated_server_change_stays_selective_while_a_task_server_is_frozen(reconciler, monkeypatch, tmp_path):
    """Freezing one task server must not disable selective reconciliation for others."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    startup = {"A": _task_server("cmd-A1"), "B": _stdio("cmd-B1")}
    _freeze_task_snapshot(startup)
    await _initialize(monkeypatch, cfg, startup, log)

    binding_a = _binding(pool, "A")
    binding_b = _binding(pool, "B")
    session_a, _loop, owner_a, _close = _entry(pool, "A")

    _write_config(cfg, {**startup, "B": _stdio("cmd-B2")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_pool_module.get_session_pool() is pool
    assert _binding(pool, "A") is binding_a
    assert _entry(pool, "A")[0] is session_a
    assert _entry(pool, "A")[2] is owner_a
    assert _binding(pool, "B") is not binding_b
    assert _binding(pool, "B").fingerprint == _fingerprint({"B": _stdio("cmd-B2")}, "B")
    assert log["exited"].get("cmd-A1") is None


@pytest.mark.asyncio
async def test_rejected_revision_still_tears_down_the_pool_a_shared_reset_retired(reconciler, monkeypatch, tmp_path):
    """A claim that fails after retiring a pool must still tear that pool down.

    ``reset_session_pool()`` only fences and unlinks the singleton; the owners
    are signalled by ``close_all_sync()``. A claim that retires the pool for a new
    shared-reset generation and *then* rejects the loaded revision must not skip
    that teardown, or the retired pool's sessions keep running without ever
    receiving a close signal.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    startup = {"A": _task_server("cmd-A1")}
    _freeze_task_snapshot(startup)
    startup_connection, startup_fingerprint = _startup_connection(startup, "A")

    durable = pool.ensure_binding("A", startup_fingerprint, domain="deployment")
    await pool.get_session("A", "task:1", startup_connection, binding=durable)
    assert log["created"]["cmd-A1"] == 1

    # A shared reset retires the pool, and the revision loaded right after it is
    # rejected by the frozen task snapshot.
    _write_config(cfg, {"A": _task_server("cmd-A2")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    marker_path = _write_remote_marker(cfg, "reset-then-rejected-revision")
    _install_discovery(monkeypatch)

    with pytest.raises(McpTaskConfigurationError):
        await cache_module.initialize_mcp_tools()

    replacement = session_pool_module.get_session_pool()
    assert replacement is not pool
    assert pool._retired is True
    assert cache_module._initializing_generation is None
    assert cache_module._cache_reset_marker_signature == get_config_signature(marker_path)

    # The retired pool's owner observes exactly one close signal.
    await _wait_until(
        lambda: log["exited"].get("cmd-A1") == 1,
        message="the retired pool's owner must still be torn down",
    )
    assert log["exit_started"]["cmd-A1"] == 1
    assert log["exited"]["cmd-A1"] == 1

    # The rejected revision was never installed in the replacement pool.
    assert ("deployment", "A") not in replacement._bindings

    # Restoring the startup configuration initializes normally.
    _write_config(cfg, startup)
    published = await cache_module.initialize_mcp_tools()
    assert [tool.name for tool in published] == ["A"]
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["interceptor", "shared_reset"])
async def test_reader_waiting_for_discovery_still_cleans_a_retired_pool(reconciler, monkeypatch, tmp_path, trigger):
    """A reader that waits for discovery must still clean up the pool it retired.

    While a discovery is in flight, a synchronous ``get_cached_mcp_tools()`` reader
    can observe an interceptor change or a new shared-reset generation and apply a
    full reconciliation. Its wait/retry branch must not skip the retired pool's
    teardown: ``reset_session_pool()`` only fences and unlinks the singleton, so the
    owners only exit once ``close_all_sync()`` runs.
    """
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    _record_sessions(monkeypatch, log)
    servers = {"A": _stdio("cmd-A1")}
    _write_config(cfg, servers)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    # A persistent session established before discovery starts.
    connection = build_servers_config(ExtensionsConfig.model_validate({"mcpServers": servers}))["A"]
    binding = pool.ensure_binding("A", normalized_connection_fingerprint(connection), domain="deployment")
    await pool.get_session("A", "task:1", connection, binding=binding)
    assert log["created"]["cmd-A1"] == 1

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _park(active_servers, active_pool, bindings):
        entered.set()
        await release.wait()

    # No sessions from this stub, so the exit log only counts the pre-discovery owner.
    _install_discovery(monkeypatch, after_bindings=_park, create_sessions=False)
    claim = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 1)

    if trigger == "interceptor":
        _write_config(cfg, servers, interceptors=["pkg.trigger:build"])
    else:
        _write_remote_marker(cfg, "reset-while-discovery-in-flight")

    applied = threading.Event()
    real_reset = session_pool_module.reset_session_pool

    def _record_reset():
        retired = real_reset()
        applied.set()
        return retired

    monkeypatch.setattr(session_pool_module, "reset_session_pool", _record_reset)

    outcome: dict = {}

    def _run_reader():
        outcome["tools"] = cache_module.get_cached_mcp_tools()

    reader = threading.Thread(target=_run_reader)
    reader.start()
    assert applied.wait(timeout=5), "the reader never retired the pool"
    release.set()
    assert await asyncio.wait_for(claim, 5) == []
    reader.join(timeout=10)
    assert not reader.is_alive(), "the cache reader did not settle"

    # Fencing alone is not the assertion: the retired pool's owner must have exited.
    assert pool._retired is True
    assert session_pool_module.get_session_pool() is not pool
    await _wait_until(
        lambda: log["exited"].get("cmd-A1") == 1,
        message="the retired pool's owner must be torn down even when the reader waits",
    )
    assert log["exit_started"]["cmd-A1"] == 1
    assert log["exited"]["cmd-A1"] == 1
    assert pool._entries == {}
    assert pool._inflight == {}
    assert outcome.get("tools") == []
