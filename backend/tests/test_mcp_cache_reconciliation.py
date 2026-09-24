"""Server-scoped MCP cache reconciliation (PR2 Task 5).

``extensions_config.json`` edits must be classified per server: only servers
whose base stdio connection changed (or that were removed/disabled) retire their
pooled sessions, while metadata-only edits and declaration-order changes keep
every live session. The applied baseline must survive tool-cache clearing so
back-to-back edits diff against the latest reconciled revision (I8), and owner
teardown must never run under ``cache._init_condition`` or ``pool._lock``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

import deerflow.mcp.cache as cache_module
from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerConfigUpdateRequest,
    McpServerStateUpdateRequest,
    create_mcp_servers,
    delete_mcp_server,
    reset_mcp_tools_cache_endpoint,
    update_mcp_server,
    update_mcp_server_state,
)
from deerflow.mcp.cache import _McpCacheTransition
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import (
    StaleMCPBindingError,
    get_session_pool,
    normalized_connection_fingerprint,
    reset_session_pool,
)
from deerflow.mcp.tasks.runtime import (
    McpTaskConfigurationError,
    set_mcp_task_config_snapshot,
)

_MISSING = object()

# Module globals that hold cache state, including the PR2 applied baseline that
# must survive ``_reset_mcp_tools_cache_state()``. Snapshotted and restored
# around every test so nothing leaks between tests.
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
)


def _write_config(
    path: Path,
    servers: dict,
    *,
    skills: dict | None = None,
    interceptors: list | None = None,
) -> None:
    payload: dict = {"mcpServers": servers, "skills": skills or {}}
    if interceptors is not None:
        payload["mcpInterceptors"] = interceptors
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stdio(command: str = "npx", **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command, "args": [], **extra}


@pytest.fixture()
def cache_globals():
    """Snapshot/restore ``deerflow.mcp.cache`` globals and reset the pool."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in _CLEARED_GLOBALS:
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
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
    """Minimal ``ClientSession`` stand-in; records whether it was exited."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def initialize(self) -> None:
        return None


class _FakeSessionCm:
    """``create_session`` replacement that never spawns a subprocess."""

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
    """A stopped-but-open loop that owns the pooled sessions under test."""
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
    """Fake discovery that seeds real pool bindings and labels tools by config."""

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
    """Publish a cache revision for *servers* through the real init entry point."""
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


def _lock_is_held(lock) -> bool:
    """Thread-agnostic "is this reentrant lock held right now?" probe."""
    if lock._is_owned():  # Same thread holds it (RLock re-entrancy).
        return True
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


def _assert_teardown_outside_locks(pool) -> None:
    assert not _lock_is_held(cache_module._init_lock), "teardown ran under cache._init_condition"
    assert not pool._lock.locked(), "teardown ran under pool._lock"


async def _wait_for_pending_teardowns() -> None:
    while cache_module._pending_teardowns:
        await asyncio.gather(*tuple(cache_module._pending_teardowns), return_exceptions=True)


def _allow_router_admin(monkeypatch) -> None:
    async def _noop_admin(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)


def _server_model(server: dict) -> McpServerConfigResponse:
    return McpServerConfigResponse.model_validate(server)


def _record_reconcile_calls(monkeypatch) -> list[set[str] | None]:
    calls: list[set[str] | None] = []
    real_reconcile = mcp_router.reconcile_mcp_servers

    def _record(changed):
        calls.append(changed)
        return real_reconcile(changed)

    monkeypatch.setattr(mcp_router, "reconcile_mcp_servers", _record)
    return calls


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_metadata_only_edit_rebuilds_without_retiring(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    assert _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")}) == ["A:npx", "B:uvx"]
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")

    _write_config(cfg, {"A": _stdio("npx", description="described"), "B": _stdio("uvx")})

    assert cache_module._classify_cache_transition() == _McpCacheTransition(frozenset({"A"}), frozenset())
    assert cache_module.refresh_mcp_cache_if_active() is True

    # Nothing retired: the binding epoch and both live sessions survive.
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "A", owner_loop)[0] is session_a
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert session_a.closed is False and session_b.closed is False

    # ...while A's tools are rebuilt from the new revision.
    assert cache_module.get_cached_mcp_tools() == ["A:described", "B:uvx"]


def test_connection_change_retires_only_that_server(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    old_binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")

    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})

    assert cache_module._classify_cache_transition() == _McpCacheTransition(frozenset({"A"}), frozenset({"A"}))
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert pool.active_binding("A") != old_binding_a
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "A", owner_loop) is None
    assert session_a.closed is True  # A's old owner ran __aexit__
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert session_b.closed is False  # B's session object is untouched

    # A's old wrapper can never obtain a session again.
    with pytest.raises(StaleMCPBindingError):
        owner_loop.run_until_complete(
            pool.get_session("A", "thread-1", _connection("npx"), binding=old_binding_a),
        )


def test_added_server_is_rebuilt_not_retired(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")

    _write_config(cfg, {"A": _stdio("npx"), "B": _stdio("uvx"), "C": _stdio("node")})

    transition = cache_module._classify_cache_transition()
    assert transition == _McpCacheTransition(frozenset({"C"}), frozenset())
    assert cache_module.refresh_mcp_cache_if_active() is True

    # A/B keep their epochs and sessions; C is seeded for its first discovery.
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "A", owner_loop)[0] is session_a
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert pool.active_binding("C") is not None


@pytest.mark.parametrize("removed", [None, {"enabled": False}])
def test_removed_or_disabled_server_is_retired_others_survive(cache_globals, monkeypatch, tmp_path, owner_loop, removed):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_b = pool.active_binding("B")

    servers = {"B": _stdio("uvx")}
    if removed is not None:
        servers = {"A": {**_stdio("npx"), **removed}, **servers}
    _write_config(cfg, servers)

    transition = cache_module._classify_cache_transition()
    assert transition is not None
    assert transition.rebuild_servers == frozenset({"A"})
    assert transition.retire_servers == frozenset({"A"})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert session_a.closed is True
    assert _entry(pool, "A", owner_loop) is None
    assert pool.active_binding("A") is not None
    assert pool.active_binding("A").fingerprint is None  # removal tombstone
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert session_b.closed is False


def test_declaration_order_change_rebuilds_all_without_retiring(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")

    _write_config(cfg, {"B": _stdio("uvx"), "A": _stdio("npx")})

    transition = cache_module._classify_cache_transition()
    assert transition == _McpCacheTransition(frozenset({"A", "B"}), frozenset())
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "A", owner_loop)[0] is session_a
    assert _entry(pool, "B", owner_loop)[0] is session_b
    # ordered tools are rebuilt from the new declaration order
    assert cache_module.get_cached_mcp_tools() == ["B:uvx", "A:npx"]


def test_interceptor_change_is_a_full_reset(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")}, interceptors=["pkg.a:build"])
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")

    _write_config(cfg, {"A": _stdio("npx")}, interceptors=["pkg.b:build"])

    transition = cache_module._classify_cache_transition()
    assert transition is not None and transition.retire_servers is None
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert get_session_pool() is not pool
    assert session_a.closed is True
    assert cache_module._cache_initialized is False


def test_equivalent_path_switch_during_in_flight_rediscovery_keeps_sessions(cache_globals, monkeypatch, tmp_path, owner_loop):
    """A path switch must compare against the applied baseline, not the published snapshot.

    A selective reconcile clears the published tool snapshot while retaining the
    applied baseline, so an equivalent path switch landing before rediscovery
    finishes must not fall back to a whole-pool reset.
    """
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_b = _open_session(owner_loop, pool, "B")

    # A's connection changes: only A retires, and the published snapshot clears.
    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert cache_module._mcp_config_snapshot is None
    assert cache_module._mcp_applied_servers is not None

    # Before rediscovery completes, switch to a file with the same effective slice.
    other = tmp_path / "other_extensions_config.json"
    _write_config(other, {"A": _stdio("npx-next"), "B": _stdio("uvx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(other))

    assert cache_module._classify_cache_transition() is None
    assert get_session_pool() is pool
    assert session_b.closed is False
    assert cache_module._mcp_applied_path == other


def test_whole_pool_reset_signals_owner_before_background_teardown(cache_globals, monkeypatch, tmp_path):
    """A whole-pool reset must detach and signal owners before any worker runs."""
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")}, interceptors=["pkg.a:build"])
    pool = get_session_pool()

    async def _run() -> None:
        exited = asyncio.Event()

        class _ObservedSessionCm(_FakeSessionCm):
            async def __aexit__(self, *exc):
                result = await super().__aexit__(*exc)
                exited.set()
                return result

        monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", _ObservedSessionCm)

        binding = pool.active_binding("A")
        assert binding is not None
        session = await pool.get_session("A", "thread-1", _connection("npx"), binding=binding)
        assert _entry(pool, "A", asyncio.get_running_loop())[0] is session

        _write_config(cfg, {"A": _stdio("npx")}, interceptors=["pkg.b:build"])

        async def _never_run_teardown(work):
            await asyncio.Event().wait()

        monkeypatch.setattr(cache_module.asyncio, "to_thread", _never_run_teardown)
        assert cache_module.reconcile_mcp_servers(None) is True

        assert pool._entries == {}
        assert pool._inflight == {}
        await asyncio.wait_for(exited.wait(), timeout=1)
        assert session.closed is True

    asyncio.run(_run())


def test_skills_only_edit_is_not_a_transition(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")}, skills={"skill-a": {"enabled": True}})
    pool = get_session_pool()

    _write_config(cfg, {"A": _stdio("npx")}, skills={"skill-a": {"enabled": False}})

    assert cache_module._classify_cache_transition() is None
    assert cache_module._is_cache_stale() is False
    assert cache_module.refresh_mcp_cache_if_active() is False
    assert cache_module._cache_initialized is True
    assert get_session_pool() is pool


def test_unreadable_config_is_a_full_reset(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")})

    cfg.write_text("{not json", encoding="utf-8")

    transition = cache_module._classify_cache_transition()
    assert transition is not None and transition.retire_servers is None
    assert cache_module._is_cache_stale() is True


def test_unstable_config_is_a_full_reset(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")})
    _write_config(cfg, {"A": _stdio("npx-next")})

    counter = iter(range(1000))
    monkeypatch.setattr(cache_module, "_get_config_signature", lambda path: (next(counter), 0, "unstable"))

    transition = cache_module._classify_cache_transition()
    assert transition is not None and transition.retire_servers is None


def test_equivalent_config_path_switch_keeps_sessions(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")})

    other = tmp_path / "other_extensions_config.json"
    _write_config(other, {"A": _stdio("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(other))

    assert cache_module._classify_cache_transition() is None
    assert cache_module._mcp_applied_path == other
    assert cache_module._mcp_applied_signature == cache_module._get_config_signature(other)


# ---------------------------------------------------------------------------
# Applied baseline retention (I8)
# ---------------------------------------------------------------------------


def test_applied_baseline_survives_tool_cache_clearing(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})

    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert cache_module._cache_initialized is False
    assert cache_module._mcp_config_snapshot is None
    assert cache_module._mcp_applied_servers is not None
    assert cache_module._mcp_applied_order == ("A", "B")
    assert set(cache_module._mcp_applied_connections) == {"A", "B"}


def test_back_to_back_change_diffs_against_the_applied_snapshot(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_b = _open_session(owner_loop, pool, "B")
    binding_b = pool.active_binding("B")

    # First revision: A -> npx-2. Rediscovery starts but is gated below.
    _write_config(cfg, {"A": _stdio("npx-2"), "B": _stdio("uvx")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert cache_module._mcp_applied_servers is not None

    started = threading.Event()
    release = threading.Event()

    async def _gated_get_mcp_tools(*, extensions_config):
        started.set()
        await asyncio.to_thread(release.wait)
        return ["stale-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _gated_get_mcp_tools)
    worker = threading.Thread(target=lambda: asyncio.run(cache_module.initialize_mcp_tools()))
    worker.start()
    try:
        assert started.wait(timeout=2)

        # Second revision lands while rediscovery for the first is pending.
        _write_config(cfg, {"A": _stdio("npx-3"), "B": _stdio("uvx")})

        # Diffs against the applied baseline (npx-2), not a cleared one.
        transition = cache_module._classify_cache_transition()
        assert transition == _McpCacheTransition(frozenset({"A"}), frozenset({"A"}))

        assert cache_module.refresh_mcp_cache_if_active() is True
        assert pool.active_binding("B") == binding_b
        assert _entry(pool, "B", owner_loop)[0] is session_b
        assert session_b.closed is False
    finally:
        release.set()
        worker.join(timeout=5)

    # The gated discovery loaded the superseded revision and must not publish.
    assert cache_module._cache_initialized is False
    # The next lazy init reads the latest revision only.
    _install_discovery(monkeypatch)
    assert cache_module.get_cached_mcp_tools() == ["A:npx-3", "B:uvx"]


@pytest.mark.parametrize("changed", [{"A"}, None], ids=["explicit", "full-diff"])
def test_reconcile_during_first_initialization_fences_stale_publish(cache_globals, monkeypatch, tmp_path, changed):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    pool_before = get_session_pool()
    generation_before = cache_module._cache_generation

    started = threading.Event()
    release = threading.Event()

    async def _gated_get_mcp_tools(*, extensions_config):
        started.set()
        await asyncio.to_thread(release.wait)
        return ["stale-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _gated_get_mcp_tools)

    async def _run() -> list:
        owner = asyncio.create_task(cache_module.initialize_mcp_tools())
        assert await asyncio.to_thread(started.wait, 2)

        _write_config(cfg, {"A": _stdio("npx-next")})
        try:
            reconciled = cache_module.reconcile_mcp_servers(changed)
            generation_after = cache_module._cache_generation
        finally:
            release.set()
        result = await asyncio.wait_for(owner, timeout=2)
        assert reconciled is True
        assert generation_after > generation_before
        return result

    assert asyncio.run(_run()) == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None
    assert cache_module._mcp_applied_servers is None
    assert get_session_pool() is not pool_before
    assert pool_before._retired is True
    assert get_session_pool().active_binding("A") is None


# ---------------------------------------------------------------------------
# Apply paths
# ---------------------------------------------------------------------------


def test_refresh_with_last_server_disabled_is_a_selective_removal(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"srv1": _stdio("npx")})
    pool = get_session_pool()
    session = _open_session(owner_loop, pool, "srv1")

    _write_config(cfg, {})

    assert cache_module.refresh_mcp_cache_if_active() is True
    assert get_session_pool() is pool  # selective: the pool is not replaced
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None
    assert cache_module._mcp_config_snapshot is None
    assert session.closed is True
    assert _entry(pool, "srv1", owner_loop) is None
    assert pool.active_binding("srv1").fingerprint is None


def test_manual_reset_fences_the_retired_pool(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    old_binding = pool.active_binding("A")

    cache_module.reset_mcp_tools_cache()

    assert get_session_pool() is not pool
    assert session_a.closed is True
    assert cache_module._mcp_applied_servers is None
    with pytest.raises(StaleMCPBindingError):
        owner_loop.run_until_complete(
            pool.get_session("A", "thread-1", _connection("npx"), binding=old_binding),
        )
    with pytest.raises(StaleMCPBindingError):
        owner_loop.run_until_complete(pool.get_session("A", "thread-2", _connection("npx")))


def test_reconcile_mcp_servers_unknown_or_empty_is_a_noop(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    binding_a = pool.active_binding("A")

    assert cache_module.reconcile_mcp_servers(set()) is False
    assert cache_module.reconcile_mcp_servers(["nope"]) is False

    assert cache_module._cache_initialized is True
    assert pool.active_binding("A") == binding_a
    assert _entry(pool, "A", owner_loop)[0] is session_a


def test_reconcile_mcp_servers_applies_only_the_named_change(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_b = pool.active_binding("B")

    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})

    assert cache_module.reconcile_mcp_servers(["A"]) is True
    assert session_a.closed is True
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "B", owner_loop)[0] is session_b


def test_reconcile_mcp_servers_none_uses_the_file(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_b = _open_session(owner_loop, pool, "B")

    _write_config(cfg, {"A": _stdio("npx"), "B": _stdio("uvx-next")})

    assert cache_module.reconcile_mcp_servers(None) is True
    assert session_b.closed is True
    assert pool.active_binding("A") is not None


def test_frozen_task_config_change_raises_before_any_retirement(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    task_server = _stdio(
        "npx",
        task_toolsets=[
            {"name": "reports", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"},
        ],
    )
    _publish(monkeypatch, cfg, {"reports": task_server})
    pool = get_session_pool()
    session = _open_session(owner_loop, pool, "reports")
    binding = pool.active_binding("reports")

    from deerflow.config.extensions_config import ExtensionsConfig

    set_mcp_task_config_snapshot(ExtensionsConfig.from_file())

    _write_config(cfg, {"reports": {**task_server, "env": {"TOKEN": "rotated"}}})

    with pytest.raises(McpTaskConfigurationError):
        cache_module.reconcile_mcp_servers(None)

    # The rejection happens before any retirement: nothing was torn down.
    assert get_session_pool() is pool
    assert pool.active_binding("reports") == binding
    assert _entry(pool, "reports", owner_loop)[0] is session
    assert session.closed is False
    assert cache_module._cache_initialized is True


def test_teardown_never_runs_under_a_lock_from_a_sync_caller(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    _open_session(owner_loop, pool, "A")
    _open_session(owner_loop, pool, "B")

    real_close = pool.close_prepared_owners_sync
    seen: list[str] = []

    def _probe(prepared):
        _assert_teardown_outside_locks(pool)
        seen.append(threading.current_thread().name)
        real_close(prepared)

    monkeypatch.setattr(pool, "close_prepared_owners_sync", _probe)

    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert seen == [threading.current_thread().name]


def test_teardown_from_an_async_caller_runs_off_the_loop_thread(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    _open_session(owner_loop, pool, "A")

    real_close = pool.close_prepared_owners_sync
    done = threading.Event()
    threads: list[str] = []

    def _probe(prepared):
        _assert_teardown_outside_locks(pool)
        threads.append(threading.current_thread().name)
        real_close(prepared)
        done.set()

    monkeypatch.setattr(pool, "close_prepared_owners_sync", _probe)

    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})

    async def _run() -> bool:
        reconciled = cache_module.reconcile_mcp_servers(None)
        assert await asyncio.to_thread(done.wait, 5)
        return reconciled

    assert asyncio.run(_run()) is True
    assert threads and threads[0] != threading.main_thread().name


def test_full_reset_teardown_never_runs_under_a_lock(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx")}, interceptors=["pkg.a:build"])
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")

    real_close = pool.close_prepared_owners_sync
    seen: list[str] = []

    def _probe(prepared):
        _assert_teardown_outside_locks(pool)
        seen.append(threading.current_thread().name)
        real_close(prepared)

    monkeypatch.setattr(pool, "close_prepared_owners_sync", _probe)

    _write_config(cfg, {"A": _stdio("npx")}, interceptors=["pkg.b:build"])
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert seen == [threading.current_thread().name]
    assert session_a.closed is True


# ---------------------------------------------------------------------------
# Gateway endpoint integration
# ---------------------------------------------------------------------------


def test_put_server_endpoint_retires_only_changed_server(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    old_binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")
    _allow_router_admin(monkeypatch)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda *_args, **_kwargs: None)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run() -> None:
        await update_mcp_server(
            None,
            McpServerConfigUpdateRequest(server_name="A", server=_server_model(_stdio("npx-next"))),
        )
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert get_session_pool() is pool
    assert pool.active_binding("A") != old_binding_a
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is True
    assert session_b.closed is False
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert reconcile_calls == [{"A"}]
    assert cache_module.get_cached_mcp_tools() == ["A:npx-next", "B:uvx"]


def test_put_server_endpoint_identical_config_is_a_noop(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")
    _allow_router_admin(monkeypatch)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda *_args, **_kwargs: None)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run() -> None:
        await update_mcp_server(
            None,
            McpServerConfigUpdateRequest(server_name="A", server=_server_model(_stdio("npx"))),
        )
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert get_session_pool() is pool
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is False
    assert session_b.closed is False
    assert cache_module._cache_initialized is True
    assert reconcile_calls == [set()]
    assert cache_module.get_cached_mcp_tools() == ["A:npx", "B:uvx"]


def test_put_server_endpoint_transport_alias_only_is_a_noop(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")
    cached_tools = cache_module._mcp_tools_cache
    generation_before = cache_module._cache_generation
    _allow_router_admin(monkeypatch)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda *_args, **_kwargs: None)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run() -> None:
        await update_mcp_server(
            None,
            McpServerConfigUpdateRequest(
                server_name="A",
                server=_server_model({"enabled": True, "transport": "stdio", "command": "npx"}),
            ),
        )
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert reconcile_calls == [set()]
    assert get_session_pool() is pool
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is False
    assert session_b.closed is False
    assert cache_module._cache_generation == generation_before
    assert cache_module._mcp_tools_cache is cached_tools
    assert cache_module._cache_initialized is True


def test_delete_endpoint_retires_only_the_deleted_server(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_b = pool.active_binding("B")
    _allow_router_admin(monkeypatch)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run() -> None:
        await delete_mcp_server(None, "A")
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert get_session_pool() is pool
    assert pool.active_binding("A").fingerprint is None
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is True
    assert session_b.closed is False
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert reconcile_calls == [{"A"}]


def test_patch_endpoint_retires_only_when_enabled_flips(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")
    _allow_router_admin(monkeypatch)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda *_args, **_kwargs: None)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run_noop() -> None:
        await update_mcp_server_state(None, McpServerStateUpdateRequest(server_name="A", enabled=True))
        await _wait_for_pending_teardowns()

    asyncio.run(_run_noop())

    assert get_session_pool() is pool
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is False
    assert session_b.closed is False

    async def _run_flip() -> None:
        await update_mcp_server_state(None, McpServerStateUpdateRequest(server_name="A", enabled=False))
        await _wait_for_pending_teardowns()

    asyncio.run(_run_flip())

    assert pool.active_binding("A").fingerprint is None
    assert pool.active_binding("B") == binding_b
    assert session_a.closed is True
    assert session_b.closed is False
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert reconcile_calls == [set(), {"A"}]


def test_create_endpoint_seeds_added_server_without_retiring_existing(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")
    _allow_router_admin(monkeypatch)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda *_args, **_kwargs: None)
    reconcile_calls = _record_reconcile_calls(monkeypatch)

    async def _run() -> None:
        await create_mcp_servers(
            None,
            McpConfigUpdateRequest(mcp_servers={"C": _server_model(_stdio("uvx", args=["c"]))}),
        )
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert get_session_pool() is pool
    assert pool.active_binding("A") == binding_a
    assert pool.active_binding("B") == binding_b
    assert pool.active_binding("C") is not None
    assert session_a.closed is False
    assert session_b.closed is False
    assert reconcile_calls == [{"C"}]
    assert cache_module.get_cached_mcp_tools() == ["A:npx", "B:uvx", "C:uvx"]


def test_manual_reset_endpoint_retires_the_whole_pool(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    _allow_router_admin(monkeypatch)

    async def _run() -> None:
        await reset_mcp_tools_cache_endpoint(None)
        await _wait_for_pending_teardowns()

    asyncio.run(_run())

    assert get_session_pool() is not pool
    assert pool._retired is True
    assert session_a.closed is True
    assert session_b.closed is True


def test_explicit_reconciliation_unions_the_full_diff(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")})
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    old_binding_b = pool.active_binding("B")

    # The caller reports only A, but B was also removed from disk.
    _write_config(cfg, {"A": _stdio("npx-next")})

    assert cache_module.reconcile_mcp_servers(["A"]) is True

    assert session_a.closed is True
    assert session_b.closed is True
    assert pool.active_binding("B").fingerprint is None
    assert "B" not in (cache_module._mcp_applied_servers or {})

    # Re-adding B with the same connection must mint a fresh epoch, not revive
    # the stale session the incomplete explicit set would have stranded.
    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")})
    assert cache_module.reconcile_mcp_servers(["B"]) is True
    assert pool.active_binding("B") != old_binding_b
