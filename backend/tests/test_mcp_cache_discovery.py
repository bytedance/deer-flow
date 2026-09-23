"""Tests for retained server-scoped MCP discovery cache entries."""

from __future__ import annotations

import threading

import pytest

import deerflow.mcp.cache as cache_module
from deerflow.mcp import cache as c
from deerflow.mcp.session_pool import reset_session_pool
from deerflow.mcp.tasks.runtime import set_mcp_task_config_snapshot

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
