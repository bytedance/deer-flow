"""Tests for retained server-scoped MCP discovery cache entries."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

import deerflow.mcp.cache as cache_module
from deerflow.mcp import cache as c
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import (
    ServerBinding,
    get_session_pool,
    normalized_connection_fingerprint,
    reset_session_pool,
)
from deerflow.mcp.tasks.runtime import set_mcp_task_config_snapshot
from deerflow.mcp.tools import ServerDiscoveryResult

_MISSING = object()

# Keep this fixture isolated from the similarly named fixtures in the other
# cache test modules; pytest does not expose fixtures across test files.
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
    "_server_tool_cache",
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
    "_server_tool_cache",
)


@pytest.fixture()
def cache_globals():
    """Snapshot/restore ``deerflow.mcp.cache`` globals and reset the pool."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in _CLEARED_GLOBALS:
        if hasattr(cache_module, name):
            setattr(cache_module, name, {} if name == "_server_tool_cache" else None)
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


def _write_config(path: Path, servers: dict) -> None:
    path.write_text(json.dumps({"mcpServers": servers, "skills": {}}), encoding="utf-8")


def _http(url: str) -> dict:
    return {"enabled": True, "type": "http", "url": url}


def test_tool(name: str) -> StructuredTool:
    async def _call() -> str:
        return name

    return StructuredTool.from_function(
        coroutine=_call,
        name=name,
        description=name,
    )


test_tool.__test__ = False


def _stdio(command: str = "npx") -> dict:
    return {"enabled": True, "type": "stdio", "command": command, "args": []}


def _stdio_result(config, name: str, tool: StructuredTool) -> ServerDiscoveryResult:
    server = config.get_enabled_mcp_servers()[name]
    connection = build_server_params(name, server)
    pool = get_session_pool()
    binding = pool.ensure_binding(name, normalized_connection_fingerprint(connection))
    return ServerDiscoveryResult(tools=(tool,), pool=pool, binding=binding)


def _force_reinitialize_preserving_server_entries() -> None:
    with c._init_condition:
        c._mcp_tools_cache = None
        c._cache_initialized = False


def test_selective_entry_eviction_preserves_unchanged_identity(cache_globals):
    from deerflow.mcp.cache import (
        _evict_server_tool_entries_locked,
        _ServerToolCacheEntry,
    )
    from deerflow.mcp.tools import ServerDiscoveryResult

    a = _ServerToolCacheEntry(snapshot="A-v1", result=ServerDiscoveryResult(()))
    b = _ServerToolCacheEntry(snapshot="B-v1", result=ServerDiscoveryResult(()))
    assert "A-v1" not in repr(a)
    with c._init_condition:
        c._server_tool_cache = {"A": a, "B": b}
        _evict_server_tool_entries_locked({"A": "A-v2", "B": "B-v1"})
        assert "A" not in c._server_tool_cache
        assert c._server_tool_cache["B"] is b


def test_entry_eviction_handles_removal_reorder_and_full_reset(cache_globals):
    from deerflow.mcp.cache import (
        _evict_server_tool_entries_locked,
        _ServerToolCacheEntry,
    )
    from deerflow.mcp.tools import ServerDiscoveryResult

    a = _ServerToolCacheEntry(snapshot="A-v1", result=ServerDiscoveryResult(()))
    b = _ServerToolCacheEntry(snapshot="B-v1", result=ServerDiscoveryResult(()))
    with c._init_condition:
        c._server_tool_cache = {"A": a, "B": b}
        _evict_server_tool_entries_locked({"B": "B-v1", "A": "A-v1"})
        assert c._server_tool_cache["A"] is a
        assert c._server_tool_cache["B"] is b

        _evict_server_tool_entries_locked({"B": "B-v1"})
        assert "A" not in c._server_tool_cache
        assert c._server_tool_cache["B"] is b

        c._reset_mcp_tools_cache_state()
        assert c._server_tool_cache["B"] is b

    c.reset_mcp_tools_cache()
    assert c._server_tool_cache == {}


def test_change_A_rediscovers_only_A_and_reuses_exact_B_tool(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(
        cfg,
        {
            "A": _http("https://A.example/mcp"),
            "B": _http("https://B.example/mcp"),
        },
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls: list[frozenset[str]] = []

    async def fake_group_discovery(config, *, server_names=None):
        enabled = config.get_enabled_mcp_servers()
        requested = set(enabled) if server_names is None else set(server_names)
        calls.append(frozenset(requested))
        return {name: ServerDiscoveryResult(tools=(test_tool(f"{name}_{enabled[name].url.rsplit('/', 2)[-2]}"),)) for name in enabled if name in requested}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)

    first = asyncio.run(cache_module.initialize_mcp_tools())
    old_B_tool = first[1]
    assert calls == [frozenset({"A", "B"})]

    _write_config(
        cfg,
        {
            "A": _http("https://A.changed.example/mcp"),
            "B": _http("https://B.example/mcp"),
        },
    )
    assert cache_module.refresh_mcp_cache_if_active() is True

    second = asyncio.run(cache_module.initialize_mcp_tools())
    assert calls[-1] == frozenset({"A"})
    assert second[1] is old_B_tool
    assert second[0].name == "A_A.changed.example"


def test_reorder_preserves_identity_and_zero_discovery(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(
        cfg,
        {
            "A": _http("https://A.example/mcp"),
            "B": _http("https://B.example/mcp"),
        },
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls: list[frozenset[str]] = []

    async def fake_group_discovery(config, *, server_names=None):
        enabled = config.get_enabled_mcp_servers()
        requested = set(enabled) if server_names is None else set(server_names)
        calls.append(frozenset(requested))
        return {name: ServerDiscoveryResult(tools=(test_tool(f"{name}_{enabled[name].url.rsplit('/', 2)[-2]}"),)) for name in enabled if name in requested}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)

    first = asyncio.run(cache_module.initialize_mcp_tools())
    old_A_tool, old_B_tool = first
    _write_config(
        cfg,
        {
            "B": _http("https://B.example/mcp"),
            "A": _http("https://A.example/mcp"),
        },
    )
    assert cache_module.refresh_mcp_cache_if_active() is True

    second = asyncio.run(cache_module.initialize_mcp_tools())
    assert calls == [frozenset({"A", "B"})]
    assert (second[0], second[1]) == (old_B_tool, old_A_tool)


def test_stdio_entry_with_stale_pool_is_rediscovered(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls: list[frozenset[str]] = []

    async def fake_group_discovery(config, *, server_names=None):
        calls.append(frozenset(set(config.get_enabled_mcp_servers()) if server_names is None else server_names))
        return {"A": _stdio_result(config, "A", test_tool(f"A-{len(calls)}"))}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)

    first = asyncio.run(cache_module.initialize_mcp_tools())
    old_pool = get_session_pool()
    old_entry = c._server_tool_cache["A"]

    reset_session_pool()
    new_pool = get_session_pool()
    real_active_binding = new_pool.active_binding
    discovery_started = False

    def active_binding(name: str):
        if not discovery_started:
            return old_entry.result.binding
        return real_active_binding(name)

    monkeypatch.setattr(new_pool, "active_binding", active_binding)

    async def _discover_after_pool_swap(config, *, server_names=None):
        nonlocal discovery_started
        discovery_started = True
        return await fake_group_discovery(config, server_names=server_names)

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", _discover_after_pool_swap)
    _force_reinitialize_preserving_server_entries()
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == [frozenset({"A"}), frozenset({"A"})]
    assert second[0] is not first[0]
    assert old_entry.result.pool is old_pool
    assert c._server_tool_cache["A"].result.pool is get_session_pool()
    assert c._server_tool_cache["A"].result.pool is not old_pool


def test_stdio_entry_with_stale_active_binding_is_rediscovered(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0

    async def fake_group_discovery(config, *, server_names=None):
        nonlocal calls
        calls += 1
        return {"A": _stdio_result(config, "A", test_tool(f"A-{calls}"))}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)

    first = asyncio.run(cache_module.initialize_mcp_tools())
    pool = get_session_pool()
    binding = pool.active_binding("A")
    assert binding is not None
    stale_binding = ServerBinding("A", binding.epoch + 1, binding.fingerprint)
    real_active_binding = pool.active_binding
    active_calls = 0

    def active_binding(name: str):
        nonlocal active_calls
        active_calls += 1
        if active_calls == 1:
            return stale_binding
        return real_active_binding(name)

    monkeypatch.setattr(pool, "active_binding", active_binding)
    _force_reinitialize_preserving_server_entries()
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == 2
    assert active_calls >= 2
    assert second[0] is not first[0]


def test_stdio_entry_with_mismatched_incoming_fingerprint_is_rediscovered(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _stdio()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0
    mismatched_fingerprint = "mismatched-fingerprint"

    async def fake_group_discovery(config, *, server_names=None):
        nonlocal calls
        calls += 1
        pool = get_session_pool()
        if calls == 1:
            binding = pool.ensure_binding(
                "A",
                normalized_connection_fingerprint(build_server_params("A", config.get_enabled_mcp_servers()["A"])),
            )
        else:
            binding = pool.bind_server("A", mismatched_fingerprint)
        return {"A": ServerDiscoveryResult(tools=(test_tool(f"A-{calls}"),), pool=pool, binding=binding)}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)
    asyncio.run(cache_module.initialize_mcp_tools())

    monkeypatch.setattr(c, "_stdio_connection_fingerprint", lambda name, server: mismatched_fingerprint)
    _force_reinitialize_preserving_server_entries()
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == 2
    assert [tool.name for tool in second] == ["A-2"]


def test_http_entry_with_pool_binding_is_never_reused(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _http("https://A.example/mcp")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0

    async def fake_group_discovery(config, *, server_names=None):
        nonlocal calls
        calls += 1
        return {"A": ServerDiscoveryResult(tools=(test_tool(f"A-{calls}"),))}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)
    first = asyncio.run(cache_module.initialize_mcp_tools())

    pool = get_session_pool()
    binding = pool.ensure_binding("A", "synthetic-stdio-fingerprint")
    entry = c._server_tool_cache["A"]
    c._server_tool_cache["A"] = c._ServerToolCacheEntry(
        snapshot=entry.snapshot,
        result=ServerDiscoveryResult(
            tools=(test_tool("poison"),),
            pool=pool,
            binding=binding,
        ),
    )
    _force_reinitialize_preserving_server_entries()
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == 2
    assert first[0].name == "A-1"
    assert second[0].name == "A-2"
    assert second[0].name != "poison"


def test_absent_failed_group_stays_absent_until_a_later_discovery(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(
        cfg,
        {
            "A": _http("https://A.example/mcp"),
            "B": _http("https://B.example/mcp"),
        },
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls: list[frozenset[str]] = []

    async def fake_group_discovery(config, *, server_names=None):
        enabled = config.get_enabled_mcp_servers()
        requested = set(enabled) if server_names is None else set(server_names)
        calls.append(frozenset(requested))
        return {"A": ServerDiscoveryResult(tools=(test_tool("A"),))} if requested == {"A", "B"} else {"B": ServerDiscoveryResult(tools=(test_tool("B"),))}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)
    first = asyncio.run(cache_module.initialize_mcp_tools())

    assert [tool.name for tool in first] == ["A"]
    assert "B" not in c._server_tool_cache

    _write_config(
        cfg,
        {
            "A": _http("https://A.example/mcp"),
            "B": _http("https://B.changed.example/mcp"),
        },
    )
    assert cache_module.refresh_mcp_cache_if_active() is True
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == [frozenset({"A", "B"}), frozenset({"B"})]
    assert [tool.name for tool in second] == ["A", "B"]


def test_present_empty_group_is_cached_and_reused(cache_globals, monkeypatch, tmp_path):
    cfg = tmp_path / "extensions_config.json"
    _write_config(cfg, {"A": _http("https://A.example/mcp")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls: list[frozenset[str]] = []

    async def fake_group_discovery(config, *, server_names=None):
        enabled = config.get_enabled_mcp_servers()
        requested = set(enabled) if server_names is None else set(server_names)
        calls.append(frozenset(requested))
        return {"A": ServerDiscoveryResult(tools=())}

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", fake_group_discovery)
    first = asyncio.run(cache_module.initialize_mcp_tools())
    entry = c._server_tool_cache["A"]

    assert first == []
    assert entry.result.tools == ()

    _force_reinitialize_preserving_server_entries()
    second = asyncio.run(cache_module.initialize_mcp_tools())

    assert calls == [frozenset({"A"})]
    assert c._server_tool_cache["A"] is entry
    assert second == []
