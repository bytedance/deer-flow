"""Shared ``mcpLifecycle`` generation classification.

The persisted lifecycle counters are a *second* invalidation signal beside the
effective-content comparison. A delete + identical re-add, a disable +
re-enable or a connection A1 -> A2 -> A1 round trip can leave the final
effective content byte-identical while the MCP resource lifecycle advanced, so
"equal content" must not be treated as "same identity" once a baseline was
adopted.

These tests pin the classification table:

1. invalid lifecycle (incoming or applied) -> whole-pool reset
2. both absent -> legacy, no lifecycle signal
3. applied absent, incoming valid -> migration grace, adopt, retire nothing
4. applied valid, incoming absent -> whole-pool reset
5. both valid -> global advance resets the pool, a per-server advance retires
   exactly that server (and forces its rebind), a regression resets the pool,
   and ``configRevision`` alone is not a signal.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

import deerflow.mcp.cache as cache_module
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import (
    get_session_pool,
    normalized_connection_fingerprint,
    reset_session_pool,
)
from deerflow.mcp.tasks.runtime import set_mcp_task_config_snapshot

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


def _stdio(command: str = "npx", **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command, "args": [], **extra}


def _lifecycle(
    config_revision: int,
    global_generation: int,
    server_generations: dict[str, int],
    *,
    lifecycle_id: str = "lineage-1",
) -> dict:
    return {
        "schemaVersion": 2,
        "lifecycleId": lifecycle_id,
        "configRevision": config_revision,
        "globalGeneration": global_generation,
        "serverGenerations": server_generations,
    }


def _write_config(
    path: Path,
    servers: dict,
    *,
    lifecycle: dict | None = None,
    lifecycle_present: bool = False,
) -> None:
    payload: dict = {"mcpServers": servers, "skills": {}}
    if lifecycle_present:
        payload["mcpLifecycle"] = lifecycle
    elif lifecycle is not None:
        payload["mcpLifecycle"] = lifecycle
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def cache_globals():
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
    """Fake discovery that seeds real pool bindings for every stdio server."""

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


def _publish(monkeypatch, cfg: Path, servers: dict, *, lifecycle: dict | None = None) -> None:
    _write_config(cfg, servers, lifecycle=lifecycle)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    _install_discovery(monkeypatch)
    asyncio.run(cache_module.initialize_mcp_tools())
    assert cache_module._cache_initialized is True


def _plan() -> cache_module._McpReconciliationPlan:
    plan = cache_module._plan_cache_transition()
    assert plan is not None, "expected a reconciliation plan"
    return plan


def _open_session(loop, pool, name: str, *, scope: str = "thread-1"):
    binding = pool.active_binding(name)
    assert binding is not None, f"{name} has no active binding"
    return loop.run_until_complete(pool.get_session(name, scope, {"transport": "stdio", "command": name, "args": []}, binding=binding))


def _entry(pool, name, loop, *, scope: str = "thread-1"):
    return pool._entries.get((name, scope, loop))


# ---------------------------------------------------------------------------
# Classification table
# ---------------------------------------------------------------------------


def test_advanced_server_generation_retires_and_forces_that_rebind(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers, lifecycle=_lifecycle(2, 0, {"A": 1, "B": 0}))

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset({"A"}), frozenset({"A"}))
    plan = _plan()
    assert plan.force_rebind == frozenset({"A"})
    assert set(plan.active) == {"A"}
    assert plan.removed == frozenset()


def test_equal_content_advanced_generation_rebinds_the_live_pool_session(cache_globals, monkeypatch, tmp_path, owner_loop):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))
    pool = get_session_pool()
    session_a = _open_session(owner_loop, pool, "A")
    session_b = _open_session(owner_loop, pool, "B")
    binding_a = pool.active_binding("A")
    binding_b = pool.active_binding("B")

    _write_config(cfg, servers, lifecycle=_lifecycle(2, 0, {"A": 1, "B": 0}))

    assert cache_module.refresh_mcp_cache_if_active() is True
    assert get_session_pool() is pool
    assert pool.active_binding("A") != binding_a
    assert pool.active_binding("B") == binding_b
    assert _entry(pool, "A", owner_loop) is None
    assert session_a.closed is True
    assert _entry(pool, "B", owner_loop)[0] is session_b
    assert session_b.closed is False


def test_advanced_global_generation_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers, lifecycle=_lifecycle(2, 1, {"A": 0, "B": 0}))

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


def test_only_config_revision_changed_is_a_noop(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers, lifecycle=_lifecycle(2, 0, {"A": 0, "B": 0}))

    assert cache_module._classify_cache_transition() is None


def test_regressed_server_generation_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(3, 0, {"A": 2, "B": 0}))

    _write_config(cfg, servers, lifecycle=_lifecycle(4, 0, {"A": 1, "B": 0}))

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


def test_missing_generation_history_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(3, 0, {"A": 2, "B": 0}))

    # The block lost A's history entirely: it must never be pruned.
    _write_config(cfg, servers, lifecycle=_lifecycle(4, 0, {"B": 0}))

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


def test_applied_valid_and_incoming_block_absent_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers)

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


@pytest.mark.parametrize(
    "invalid_block",
    [
        None,
        "not-an-object",
        {"schemaVersion": 2},
        {"schemaVersion": 3, "lifecycleId": "x", "configRevision": 0, "globalGeneration": 0, "serverGenerations": {}},
        {"serverGenerations": {"A": -1}},
    ],
)
def test_applied_valid_and_incoming_block_invalid_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path, invalid_block):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers, lifecycle=invalid_block, lifecycle_present=True)

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


def test_first_adoption_of_a_valid_block_retires_nothing(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers)
    assert cache_module._mcp_applied_lifecycle is None

    _write_config(cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    # Migration grace: the first valid block is adopted, not retired from.
    assert cache_module._classify_cache_transition() is None
    assert cache_module._mcp_applied_lifecycle is not None
    assert cache_module._mcp_applied_lifecycle.server_generations == {"A": 0, "B": 0}


def test_content_change_and_generation_advance_are_union_ed(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _publish(monkeypatch, cfg, {"A": _stdio("npx"), "B": _stdio("uvx")}, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    # A's base connection changed (content signal) while B's generation advanced
    # with byte-identical content (lifecycle signal).
    _write_config(cfg, {"A": _stdio("npx-next"), "B": _stdio("uvx")}, lifecycle=_lifecycle(2, 0, {"A": 0, "B": 1}))

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset({"A", "B"}), frozenset({"A", "B"}))
    plan = _plan()
    assert plan.force_rebind == frozenset({"B"})
    assert set(plan.active) == {"A", "B"}
    assert plan.removed == frozenset()


def test_both_blocks_absent_is_legacy_and_stays_a_noop(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers)

    _write_config(cfg, servers, lifecycle=None)

    assert cache_module._classify_cache_transition() is None


def test_rebased_lineage_with_identical_counters_resets_the_whole_pool(cache_globals, monkeypatch, tmp_path):
    """A regenerated ``lifecycleId`` must win over byte-identical counters.

    A repaired or re-initialized block restarts the counters, so a worker that
    missed the intervening history would otherwise read the block as unchanged.
    """
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 1, {"A": 1, "B": 1}, lifecycle_id="lineage-1"))

    _write_config(
        cfg,
        servers,
        lifecycle=_lifecycle(1, 1, {"A": 1, "B": 1}, lifecycle_id="lineage-2"),
        lifecycle_present=True,
    )

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


@pytest.mark.parametrize(
    "partial",
    [
        {},
        {"schemaVersion": 2},
        {"configRevision": 3},
        {"schemaVersion": 2, "lifecycleId": "lineage-1", "configRevision": 3},
        {"schemaVersion": 2, "lifecycleId": "lineage-1", "globalGeneration": 0, "serverGenerations": {}},
    ],
)
def test_partial_persisted_block_is_unverifiable(cache_globals, monkeypatch, tmp_path, partial):
    """A truncated block must not be completed with defaults into a version."""
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    _write_config(cfg, servers, lifecycle=partial, lifecycle_present=True)

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)


def test_block_missing_an_enabled_server_is_unverifiable(cache_globals, monkeypatch, tmp_path):
    """The block and the effective configuration must describe the same revision."""
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    _publish(monkeypatch, cfg, servers, lifecycle=_lifecycle(1, 0, {"A": 0, "B": 0}))

    # B is enabled but has no recorded generation.
    _write_config(cfg, servers, lifecycle=_lifecycle(2, 0, {"A": 0}), lifecycle_present=True)

    assert cache_module._classify_cache_transition() == cache_module._McpCacheTransition(frozenset(), None)
