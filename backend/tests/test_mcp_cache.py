"""Tests for MCP tools cache staleness detection (``deerflow.mcp.cache``).

Regression coverage for the content-signature invalidation fix. The cache used
to invalidate on a strict extensions-config *mtime* ``>`` comparison and tracked
no resolved path, so it missed three real edit patterns that leave stale MCP
tools serving in the LangGraph-embedded runtime and every non-writer worker:

1. content change with an unchanged mtime (same-second edit; object-store /
   network mounts that do not bump mtime),
2. content change with a backward mtime (``git checkout``, ``cp -p`` / backup
   restore, ``tar`` / ``rsync`` preserving timestamps),
3. a resolved-path switch to a different config file whose mtime is <= the one
   recorded at initialization.

The fix mirrors ``deerflow.config.app_config``'s ``(path, (mtime, size,
sha256))`` detection so both runtime-editable config files share one staleness
signal. These tests fail on the pre-fix code (cases 1-3 return ``False``) and
pass afterwards.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

import pytest

import deerflow.mcp.cache as cache_module
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.file_signature import get_config_signature

_MISSING = object()

# Module globals that hold cache state. Snapshotted and restored around every
# test so an initialized cache — or an asyncio lock bound to a closed loop —
# cannot leak between tests. ``_config_mtime`` is the pre-fix global name and is
# tracked too so the same fixture works when the source fix is reverted.
_TRACKED_GLOBALS = (
    "_mcp_tools_cache",
    "_cache_initialized",
    "_config_path",
    "_config_signature",
    "_config_mtime",
    "_init_lock",
    "_init_condition",
    "_initializing_generation",
    "_cache_generation",
    "_mcp_config_snapshot",
    "_initialized_without_config",
)


def _write_extensions_config(
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


def _server(command: str = "npx") -> dict:
    return {"enabled": True, "type": "stdio", "command": command}


@pytest.fixture()
def cache_globals():
    """Snapshot/restore ``deerflow.mcp.cache`` module globals and reset the lock."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in ("_config_path", "_config_signature", "_config_mtime", "_mcp_config_snapshot", "_initialized_without_config"):
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
    # threading.Lock is safe across threads and does not bind to event loops,
    # so each test gets fresh coordination state for isolation.
    cache_module._init_lock = threading.RLock()
    cache_module._init_condition = threading.Condition(cache_module._init_lock)
    cache_module._initializing_generation = None
    cache_module._cache_generation = 0

    try:
        yield
    finally:
        for name, value in saved.items():
            if value is _MISSING:
                if hasattr(cache_module, name):
                    delattr(cache_module, name)
            else:
                setattr(cache_module, name, value)


def _initialize_against(monkeypatch, config_path: Path) -> None:
    """Populate the cache against ``config_path`` via the real init entry point.

    ``initialize_mcp_tools()`` records the resolved config path + content
    signature after loading tools; the tool load itself is stubbed so this stays
    a cache-state unit test with no real MCP servers.
    """
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _fake_get_mcp_tools(**_kwargs):
        return []

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    asyncio.run(cache_module.initialize_mcp_tools())
    assert cache_module._cache_initialized is True


def test_not_stale_before_initialization(cache_globals):
    """An uninitialized cache is never stale (preserved behavior)."""
    assert cache_module._cache_initialized is False
    assert cache_module._is_cache_stale() is False


def test_initialize_records_path_and_signature(cache_globals, monkeypatch, tmp_path):
    """initialize_mcp_tools records the resolved path and a full content signature."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})

    _initialize_against(monkeypatch, cfg)

    assert cache_module._config_path == cfg
    assert cache_module._config_signature is not None
    mtime, size, digest = cache_module._config_signature
    assert mtime == cfg.stat().st_mtime
    assert size == cfg.stat().st_size
    assert isinstance(digest, str) and len(digest) == 64  # sha256 hexdigest


def test_same_mtime_content_change_is_stale(cache_globals, monkeypatch, tmp_path):
    """Failure mode 1: content rewritten, mtime forced to stay identical."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)
    recorded_mtime = cfg.stat().st_mtime

    _write_extensions_config(cfg, {"srv1": _server(), "srv2": _server("uvx")})
    os.utime(cfg, (recorded_mtime, recorded_mtime))
    assert cfg.stat().st_mtime == recorded_mtime  # guard: mtime truly unchanged

    assert cache_module._is_cache_stale() is True


def test_backward_mtime_content_change_is_stale(cache_globals, monkeypatch, tmp_path):
    """Failure mode 2: content rewritten, mtime moved backward."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)
    recorded_mtime = cfg.stat().st_mtime

    _write_extensions_config(cfg, {"different": _server()})
    older = recorded_mtime - 100
    os.utime(cfg, (older, older))
    assert cfg.stat().st_mtime < recorded_mtime  # guard: mtime went backward

    assert cache_module._is_cache_stale() is True


def test_config_path_switch_is_stale(cache_globals, monkeypatch, tmp_path):
    """Failure mode 3: resolved path switches to a different file, mtime <= recorded."""
    cfg_a = tmp_path / "extensions_config.json"
    cfg_b = tmp_path / "other_extensions_config.json"
    _write_extensions_config(cfg_a, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg_a)
    recorded_mtime = cfg_a.stat().st_mtime

    _write_extensions_config(cfg_b, {"totally": _server("uvx")})
    older = recorded_mtime - 50
    os.utime(cfg_b, (older, older))  # a DIFFERENT file, mtime <= recorded

    # The resolver now points at cfg_b (e.g. DEER_FLOW_EXTENSIONS_CONFIG_PATH
    # was repointed, or default resolution now finds a different file).
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: cfg_b),
    )

    assert cache_module._is_cache_stale() is True


def test_unchanged_file_is_not_stale(cache_globals, monkeypatch, tmp_path):
    """Sanity: an untouched config file does not trigger a needless reinit."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    assert cache_module._is_cache_stale() is False


def test_forward_edit_is_stale(cache_globals, monkeypatch, tmp_path):
    """Sanity: a genuine forward edit is still detected as stale."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)
    recorded_mtime = cfg.stat().st_mtime

    _write_extensions_config(cfg, {"srv1": _server(), "srv2": _server("uvx")})
    newer = recorded_mtime + 100
    os.utime(cfg, (newer, newer))

    assert cache_module._is_cache_stale() is True


def test_same_mtime_same_size_swap_is_stale(cache_globals, monkeypatch, tmp_path):
    """Precise variant of failure mode 1: mtime *and* size both stay unchanged
    (an equal-length server-name swap), so mtime/size alone are indistinguishable
    and only the sha256 content digest can catch the change. Guards the content
    digest itself: a future change that starts short-circuiting the hash
    whenever mtime/size already match a recorded value must not make this test
    pass without actually detecting the swap.
    """
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)
    recorded_mtime = cfg.stat().st_mtime
    recorded_size = cfg.stat().st_size

    _write_extensions_config(cfg, {"srv9": _server()})  # same-length key swap
    os.utime(cfg, (recorded_mtime, recorded_mtime))
    assert cfg.stat().st_mtime == recorded_mtime  # guard: mtime truly unchanged
    assert cfg.stat().st_size == recorded_size  # guard: size truly unchanged too

    assert cache_module._is_cache_stale() is True


def test_config_deleted_after_init_is_not_stale(cache_globals, monkeypatch, tmp_path):
    """Latent edge preserved by design: if the resolved config file is deleted
    entirely after a successful init, ``current_signature`` becomes ``None`` and
    the cache does NOT invalidate — it keeps serving its last-known-good MCP
    tools instead of tearing down into an unconfigured state. This matches the
    pre-fix mtime-only contract, which also returned ``False`` once the file
    could no longer be stat-ed, so it is not a regression introduced by the
    content-signature fix.

    The resolver is monkeypatched to keep pointing at the (now-missing) path,
    isolating ``_is_cache_stale``'s own stat-failure handling from
    ``ExtensionsConfig.resolve_config_path``'s own not-found contract for
    explicit path/env-var configuration, which raises ``FileNotFoundError``
    in that mode (an operator-asserted path going missing is a real
    misconfiguration and must be loud for callers that load the config for
    real use — PR #4275 review, fancyboi999 [P1]). ``_resolve_config_path``
    just above is the narrow exception: it catches that specific
    ``FileNotFoundError`` and treats it as "unconfigured" so this staleness
    check keeps degrading to "not stale" instead of raising — see
    ``test_extensions_config_env_var_missing_file_raises`` in
    ``test_runtime_paths.py`` for the resolver-level raise contract, and
    ``test_config_deleted_after_init_via_real_env_resolution_does_not_raise``
    below for the same scenario this test isolates against, exercised through
    the real resolver instead of a monkeypatch.
    """
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)
    assert cache_module._config_signature is not None  # guard: had a real signature

    cfg.unlink()  # the config file is deleted entirely, not just edited
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: cfg),
    )

    assert cache_module._is_cache_stale() is False


def test_config_deleted_after_init_via_real_env_resolution_does_not_raise(cache_globals, monkeypatch, tmp_path):
    """End-to-end regression for the explicit-vs-search distinction raised by
    fancyboi999 [P1] on PR #4275: when the extensions config path comes from
    ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` (exactly how Docker dev/prod point at
    it, per backend/AGENTS.md) and the file is deleted after a successful
    init, ``_is_cache_stale()`` must not raise — even though
    ``ExtensionsConfig.resolve_config_path()`` itself now (again) raises
    ``FileNotFoundError`` for a missing explicit/env-var path, restoring loud
    failure for callers that load the config for real use.

    Unlike ``test_config_deleted_after_init_is_not_stale`` (which monkeypatches
    ``ExtensionsConfig.resolve_config_path`` to isolate ``_is_cache_stale``'s
    own None-handling from the resolver's own contract), this test exercises
    the REAL resolver end to end. ``_resolve_config_path`` in this module is
    the only thing standing between that raise and a crash here: it catches
    ``FileNotFoundError`` locally and returns ``None``, so this hot,
    per-request staleness check keeps degrading to "not stale" (serving
    last-known-good cached tools) instead of propagating uncaught out of
    ``get_cached_mcp_tools()``. Deleting the ``_resolve_config_path`` try/except
    reproduces the original crash this test guards against.
    """
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)  # sets DEER_FLOW_EXTENSIONS_CONFIG_PATH=cfg
    assert cache_module._config_signature is not None  # guard: had a real signature

    cfg.unlink()  # config deleted; env var still points at the now-missing path

    # Must not raise, and must report "not stale" (fail-soft: keep serving the
    # last-known-good MCP tools), matching the deliberate contract in
    # test_config_deleted_after_init_is_not_stale above.
    assert cache_module._is_cache_stale() is False


class TestCrossLoopReinitialization:
    """Regression for #5060: cache initialization must be cross-loop safe."""

    def test_cross_loop_reinit_does_not_raise(self, monkeypatch, tmp_path):
        """Two successive ``asyncio.run()`` calls (each with its own loop) must not crash."""
        saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}
        try:
            cache_module._mcp_tools_cache = None
            cache_module._cache_initialized = False
            for name in ("_config_path", "_config_signature", "_config_mtime"):
                if hasattr(cache_module, name):
                    setattr(cache_module, name, None)
            cache_module._init_lock = threading.RLock()
            cache_module._init_condition = threading.Condition(cache_module._init_lock)
            cache_module._initializing_generation = None
            cache_module._cache_generation = 0

            cfg = tmp_path / "extensions_config.json"
            _write_extensions_config(cfg, {"srv1": _server()})
            monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

            async def _fake_tools(**_kwargs):
                return []

            monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

            asyncio.run(cache_module.initialize_mcp_tools())
            assert cache_module._cache_initialized is True

            cache_module.reset_mcp_tools_cache()
            assert cache_module._cache_initialized is False

            asyncio.run(cache_module.initialize_mcp_tools())
            assert cache_module._cache_initialized is True
        finally:
            for name, value in saved.items():
                if value is _MISSING:
                    if hasattr(cache_module, name):
                        delattr(cache_module, name)
                else:
                    setattr(cache_module, name, value)

    def test_contended_cross_loop_reinit_does_not_raise(self, monkeypatch, tmp_path):
        """Contended initializers in two event loops must not reuse a loop-bound lock."""
        saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}
        try:
            cache_module._mcp_tools_cache = None
            cache_module._cache_initialized = False
            for name in ("_config_path", "_config_signature", "_config_mtime"):
                if hasattr(cache_module, name):
                    setattr(cache_module, name, None)
            cache_module._init_lock = threading.RLock()
            cache_module._init_condition = threading.Condition(cache_module._init_lock)
            cache_module._initializing_generation = None
            cache_module._cache_generation = 0

            cfg = tmp_path / "extensions_config.json"
            _write_extensions_config(cfg, {"srv1": _server()})
            monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

            calls = 0

            async def _fake_tools(**_kwargs):
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.01)
                return []

            monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

            async def _contended_init():
                await asyncio.gather(cache_module.initialize_mcp_tools(), cache_module.initialize_mcp_tools())

            asyncio.run(_contended_init())
            assert cache_module._cache_initialized is True
            assert calls == 1

            cache_module.reset_mcp_tools_cache()
            assert cache_module._cache_initialized is False

            asyncio.run(_contended_init())
            assert cache_module._cache_initialized is True
            assert calls == 2
        finally:
            for name, value in saved.items():
                if value is _MISSING:
                    if hasattr(cache_module, name):
                        delattr(cache_module, name)
                else:
                    setattr(cache_module, name, value)

    def test_get_cached_mcp_tools_reinit_after_invalidation(self, monkeypatch, tmp_path):
        """Gateway path without ``cache_globals`` resetting coordination state — production scenario."""
        saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}
        try:
            cache_module._mcp_tools_cache = None
            cache_module._cache_initialized = False
            for name in ("_config_path", "_config_signature", "_config_mtime"):
                if hasattr(cache_module, name):
                    setattr(cache_module, name, None)
            cache_module._init_lock = threading.RLock()
            cache_module._init_condition = threading.Condition(cache_module._init_lock)
            cache_module._initializing_generation = None
            cache_module._cache_generation = 0

            cfg = tmp_path / "extensions_config.json"
            _write_extensions_config(cfg, {"srv1": _server()})
            monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

            async def _fake_tools(**_kwargs):
                return []

            monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

            result1 = cache_module.get_cached_mcp_tools()
            assert result1 == []
            assert cache_module._cache_initialized is True

            _write_extensions_config(cfg, {"srv1": _server(), "srv2": _server("uvx")})
            cache_module.reset_mcp_tools_cache()

            result2 = cache_module.get_cached_mcp_tools()
            assert result2 == []
            assert cache_module._cache_initialized is True
        finally:
            for name, value in saved.items():
                if value is _MISSING:
                    if hasattr(cache_module, name):
                        delattr(cache_module, name)
                else:
                    setattr(cache_module, name, value)


def test_config_change_during_initialization_discards_stale_tools(cache_globals, monkeypatch, tmp_path):
    """A config rewrite during load must not publish tools loaded from the old config."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"old": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0

    async def _fake_tools(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            _write_extensions_config(cfg, {"new": _server("uvx")})
            return ["old-tools"]
        return ["new-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    first = asyncio.run(cache_module.initialize_mcp_tools())
    assert first == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None

    second = cache_module.get_cached_mcp_tools()
    assert second == ["new-tools"]
    assert cache_module._cache_initialized is True
    assert cache_module._mcp_tools_cache == ["new-tools"]
    assert cache_module._is_cache_stale() is False
    assert calls == 2


def test_config_change_during_initialization_retires_pool_for_same_server_connection_change(cache_globals, monkeypatch, tmp_path):
    """Discarding a mid-load config change must also retire pooled sessions.

    A stale load can create a pooled session before ``initialize_mcp_tools``
    notices that the config changed and discards the loaded tools. If the server
    name and scope stay the same while the connection changes, the next load can
    otherwise reuse that old session because ``MCPSessionPool`` keys only by
    ``(server_name, scope_key)``.
    """
    from deerflow.mcp import session_pool as session_pool_module

    class FakeSession:
        def __init__(self, command: str) -> None:
            self.command = command

    class FakeSessionPool:
        def __init__(self) -> None:
            self.closed = False
            self.sessions = {}

        async def get_session(self, server_name, scope_key, connection):
            key = (server_name, scope_key)
            if key not in self.sessions:
                self.sessions[key] = FakeSession(connection["command"])
            return self.sessions[key]

        def close_all_sync(self) -> None:
            self.closed = True

    real_reset_session_pool = session_pool_module.reset_session_pool
    monkeypatch.setattr(session_pool_module, "MCPSessionPool", FakeSessionPool)
    real_reset_session_pool()
    old_pool = session_pool_module.get_session_pool()

    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"same": _server("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0
    loaded_pools = []
    loaded_sessions = []

    async def _fake_tools(**_kwargs):
        nonlocal calls
        calls += 1
        server = json.loads(cfg.read_text())["mcpServers"]["same"]
        pool = session_pool_module.get_session_pool()
        session = await pool.get_session("same", "thread-1", server)
        loaded_pools.append(pool)
        loaded_sessions.append(session)
        if calls == 1:
            _write_extensions_config(cfg, {"same": _server("uvx")})
        return [f"session-{session.command}"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    try:
        first = asyncio.run(cache_module.initialize_mcp_tools())
        assert first == []
        assert cache_module._cache_initialized is False

        second = cache_module.get_cached_mcp_tools()

        assert second == ["session-uvx"]
        assert loaded_pools[0] is old_pool
        assert loaded_pools[1] is not old_pool
        assert loaded_sessions[0] is not loaded_sessions[1]
        assert old_pool.closed is True
        assert cache_module._cache_initialized is True
    finally:
        real_reset_session_pool()


def test_reset_mcp_tools_cache_does_not_wait_for_in_flight_initialization(cache_globals, monkeypatch, tmp_path):
    """Event-loop callers can reset cache state without waiting for a slow tool load."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    started = threading.Event()
    finish = threading.Event()

    async def _fake_tools(**_kwargs):
        started.set()
        await asyncio.to_thread(finish.wait)
        return []

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    worker = threading.Thread(target=lambda: asyncio.run(cache_module.initialize_mcp_tools()))
    worker.start()
    assert started.wait(timeout=1)

    reset_done = threading.Event()

    def _reset():
        cache_module.reset_mcp_tools_cache()
        reset_done.set()

    reset_thread = threading.Thread(target=_reset)
    reset_thread.start()
    assert reset_done.wait(timeout=1)

    finish.set()
    worker.join(timeout=1)
    reset_thread.join(timeout=1)
    assert not worker.is_alive()
    assert not reset_thread.is_alive()


def test_automatic_stale_invalidation_retires_session_pool_before_reinitializing(cache_globals, monkeypatch, tmp_path):
    """Automatic config-signature invalidation must retire the old session pool.

    ``get_cached_mcp_tools()`` detects runtime edits through ``_is_cache_stale``
    without going through the explicit admin reset endpoint. That automatic path
    must still swap the session-pool singleton before rebuilding tool wrappers;
    otherwise the fresh wrappers can keep reusing sessions created from the old
    connection config.
    """
    from deerflow.mcp import session_pool as session_pool_module

    real_reset_session_pool = session_pool_module.reset_session_pool
    real_reset_session_pool()
    old_pool = session_pool_module.get_session_pool()

    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"old": _server()})
    _initialize_against(monkeypatch, cfg)
    assert cache_module._cache_initialized is True
    assert session_pool_module.get_session_pool() is old_pool

    _write_extensions_config(cfg, {"new": _server("uvx")})
    loaded_pools = []

    async def _fake_tools(**_kwargs):
        loaded_pools.append(session_pool_module.get_session_pool())
        return ["new-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    try:
        result = cache_module.get_cached_mcp_tools()

        assert result == ["new-tools"]
        assert loaded_pools == [session_pool_module.get_session_pool()]
        assert loaded_pools[0] is not old_pool
        assert cache_module._cache_initialized is True
    finally:
        real_reset_session_pool()


def test_reset_mcp_tools_cache_retires_session_pool_before_releasing_initializers(cache_globals, monkeypatch):
    """A reset must not let fresh tool wrappers publish with the retiring pool."""
    from deerflow.mcp import session_pool as session_pool_module

    real_reset_session_pool = session_pool_module.reset_session_pool
    real_reset_session_pool()
    old_pool = session_pool_module.get_session_pool()

    cache_module._mcp_tools_cache = ["cached-tools"]
    cache_module._cache_initialized = True
    race_results = []
    loaded_pools = []

    async def _fake_tools(**_kwargs):
        loaded_pools.append(session_pool_module.get_session_pool())
        return ["race-tools"]

    def _reset_with_concurrent_initializer():
        # This simulates the old interleaving: a cache waiter starts exactly
        # while reset_mcp_tools_cache() is retiring the session-pool singleton.
        race_results.append(asyncio.run(cache_module.initialize_mcp_tools()))
        return real_reset_session_pool()

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)
    monkeypatch.setattr(session_pool_module, "reset_session_pool", _reset_with_concurrent_initializer)

    try:
        cache_module.reset_mcp_tools_cache()

        # The racing initializer should see the still-valid old cache and avoid
        # rebuilding tools until the pool has been swapped. Pre-fix, cache state
        # was cleared first, so this race loaded and published wrappers against
        # ``old_pool`` just before the singleton was replaced.
        assert race_results == [["cached-tools"]]
        assert loaded_pools == []
        assert cache_module._cache_initialized is False
        assert cache_module._mcp_tools_cache is None
        assert session_pool_module.get_session_pool() is not old_pool
    finally:
        real_reset_session_pool()


def test_cancelled_initializer_releases_generation_claim(cache_globals, monkeypatch, tmp_path):
    """Cancelling the owner task must not strand waiters on its generation claim."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _fake_tools(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return []

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    async def _cancel_and_retry():
        owner = asyncio.create_task(cache_module.initialize_mcp_tools())
        await asyncio.wait_for(started.wait(), timeout=1)
        owner.cancel()

        with pytest.raises(asyncio.CancelledError):
            await owner

        assert cache_module._initializing_generation is None
        assert cache_module._cache_initialized is False

        release.set()
        result = await asyncio.wait_for(cache_module.initialize_mcp_tools(), timeout=1)
        assert result == []

    asyncio.run(_cancel_and_retry())
    assert cache_module._cache_initialized is True
    assert cache_module._initializing_generation is None
    assert calls == 2


# ---------------------------------------------------------------------------
# Effective-MCP-config invalidation
#
# ``extensions_config.json`` carries both ``mcpServers`` and ``skills``, and the
# cache signature covers the whole file. Before this fix any skill edit closed
# every pooled MCP session even though no MCP server changed. These tests pin
# the narrowed contract: only the effective MCP slice may retire MCP state.
# ---------------------------------------------------------------------------


def test_skills_only_change_keeps_tools_and_pool(cache_globals, monkeypatch, tmp_path):
    """Toggling a skill must not rebuild tools, replace the pool, or close sessions."""
    from deerflow.mcp.session_pool import get_session_pool, reset_session_pool

    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    sentinel_tool = object()

    async def _fake_get_mcp_tools(**_kwargs):
        return [sentinel_tool]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    asyncio.run(cache_module.initialize_mcp_tools())

    old_pool = get_session_pool()
    closed: list[bool] = []
    monkeypatch.setattr(old_pool, "close_all_sync", lambda: closed.append(True))

    try:
        _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": False}})

        assert cache_module.get_cached_mcp_tools() == [sentinel_tool]
        assert cache_module._mcp_tools_cache == [sentinel_tool]
        assert get_session_pool() is old_pool
        assert closed == []
        assert cache_module._config_signature == get_config_signature(cfg)
    finally:
        reset_session_pool()


def test_same_mtime_same_size_skills_only_change_is_not_stale(cache_globals, monkeypatch, tmp_path):
    """A skills-only edit that hides behind mtime+size still updates the checked signature."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    _initialize_against(monkeypatch, cfg)
    recorded_mtime = cfg.stat().st_mtime
    recorded_size = cfg.stat().st_size

    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-b": {"enabled": True}})
    os.utime(cfg, (recorded_mtime, recorded_mtime))
    assert cfg.stat().st_mtime == recorded_mtime
    assert cfg.stat().st_size == recorded_size

    assert cache_module._is_cache_stale() is False
    assert cache_module._config_signature == get_config_signature(cfg)


def test_mcp_connection_change_is_still_stale(cache_globals, monkeypatch, tmp_path):
    """A real MCP change must keep retiring the cache (no over-narrowing)."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    _write_extensions_config(cfg, {"srv1": _server("uvx")})

    assert cache_module._is_cache_stale() is True


def test_mcp_interceptors_change_is_still_stale(cache_globals, monkeypatch, tmp_path):
    """A global mcpInterceptors change must keep retiring the cache."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, interceptors=["pkg.a:build"])
    _initialize_against(monkeypatch, cfg)

    _write_extensions_config(cfg, {"srv1": _server()}, interceptors=["pkg.b:build"])

    assert cache_module._is_cache_stale() is True


def test_explicit_reset_still_clears_after_skills_only_change(cache_globals, monkeypatch, tmp_path):
    """The semantic comparison must never suppress an explicit global reset."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    _initialize_against(monkeypatch, cfg)
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": False}})
    assert cache_module.get_cached_mcp_tools() == []

    cache_module.reset_mcp_tools_cache()

    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None
    assert cache_module._mcp_config_snapshot is None


def test_malformed_config_is_still_stale(cache_globals, monkeypatch, tmp_path):
    """An unreadable config must never be mistaken for a skills-only no-op."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    cfg.write_text("{not json", encoding="utf-8")

    assert cache_module._is_cache_stale() is True


def test_refresh_is_noop_before_initialization(cache_globals, monkeypatch):
    """Deployments that never initialized MCP pay no config-hashing cost."""
    calls: list[str] = []
    monkeypatch.setattr(
        cache_module,
        "_current_config_state",
        lambda: calls.append("checked") or (None, None),
    )

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert calls == []


def test_refresh_retires_cache_when_last_server_is_disabled(cache_globals, monkeypatch, tmp_path):
    """Disabling the last server still converges an already-initialized cache."""
    from deerflow.mcp.session_pool import get_session_pool, reset_session_pool

    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    old_pool = get_session_pool()
    closed: list[bool] = []
    monkeypatch.setattr(old_pool, "close_all_sync", lambda: closed.append(True))
    _write_extensions_config(cfg, {})

    try:
        assert cache_module.refresh_mcp_cache_if_active() is True
        assert cache_module._cache_initialized is False
        assert cache_module._mcp_tools_cache is None
        assert cache_module._mcp_config_snapshot is None
        assert get_session_pool() is not old_pool
        assert closed == [True]
    finally:
        reset_session_pool()


def test_refresh_keeps_cache_when_only_skills_changed(cache_globals, monkeypatch, tmp_path):
    """The lightweight refresh path honours the effective-MCP comparison."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    _initialize_against(monkeypatch, cfg)

    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": False}})

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert cache_module._cache_initialized is True


def test_skills_only_change_during_initialization_publishes_loaded_tools(cache_globals, monkeypatch, tmp_path):
    """A skills-only edit during tool discovery must not force a needless rebuild."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    calls = 0

    async def _fake_tools(**_kwargs):
        nonlocal calls
        calls += 1
        _write_extensions_config(cfg, {"srv1": _server()}, skills={"skill-a": {"enabled": False}})
        return ["loaded-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    result = asyncio.run(cache_module.initialize_mcp_tools())

    assert result == ["loaded-tools"]
    assert cache_module._cache_initialized is True
    assert cache_module._mcp_tools_cache == ["loaded-tools"]
    assert calls == 1


def test_refresh_during_initialization_discards_stale_publish(cache_globals, monkeypatch, tmp_path):
    """Disabling the last server while discovery is in flight must void the result."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    started = threading.Event()
    release = threading.Event()

    async def _fake_tools(**_kwargs):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return ["stale-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    async def _run():
        owner = asyncio.create_task(cache_module.initialize_mcp_tools())
        while not started.is_set():
            await asyncio.sleep(0.01)
        _write_extensions_config(cfg, {})
        assert cache_module.refresh_mcp_cache_if_active() is True
        release.set()
        return await asyncio.wait_for(owner, timeout=2)

    assert asyncio.run(_run()) == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None


def test_initialization_without_a_readable_snapshot_discards_result(cache_globals, monkeypatch, tmp_path):
    """Never publish tools that cannot be tied to a parsed MCP snapshot."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    async def _fake_get_mcp_tools(**_kwargs):
        return ["loaded-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    monkeypatch.setattr(cache_module, "_read_stable_mcp_snapshot", lambda path, signature: None)

    result = asyncio.run(cache_module.initialize_mcp_tools())

    assert result == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None


def test_parse_failure_log_does_not_leak_resolved_credentials(cache_globals, monkeypatch, tmp_path, caplog):
    """A malformed config must not echo resolved $VAR secrets into the log."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    monkeypatch.setenv("MCP_SECRET", "TOPSECRET123")
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "srv1": {"enabled": True, "type": "stdio", "command": "npx", "headers": "$MCP_SECRET"},
                },
                "skills": {},
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        assert cache_module._is_cache_stale() is True

    assert "TOPSECRET123" not in caplog.text


def test_equivalent_transport_alias_spellings_are_not_stale(cache_globals, monkeypatch, tmp_path):
    """``type=stdio`` and ``transport=stdio`` describe the same connection."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": {"enabled": True, "type": "stdio", "command": "npx"}})
    _initialize_against(monkeypatch, cfg)

    _write_extensions_config(cfg, {"srv1": {"enabled": True, "transport": "stdio", "command": "npx"}})

    assert cache_module._is_cache_stale() is False


def test_initialization_hands_the_snapshotted_config_to_discovery(cache_globals, monkeypatch, tmp_path):
    """Discovery must use the exact revision the cache snapshotted, not re-read."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    seen: dict[str, str] = {}

    async def _fake_tools(*, extensions_config):
        seen["command"] = extensions_config.mcp_servers["srv1"].command
        # A transient flip to Y and back to X must not invalidate X-built tools.
        _write_extensions_config(cfg, {"srv1": _server("uvx")})
        _write_extensions_config(cfg, {"srv1": _server("npx")})
        return ["loaded-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_tools)

    result = asyncio.run(cache_module.initialize_mcp_tools())

    assert seen["command"] == "npx"
    assert result == ["loaded-tools"]
    assert cache_module._cache_initialized is True
    assert cache_module._mcp_config_snapshot is not None


def test_config_appearing_after_unconfigured_init_is_stale(cache_globals, monkeypatch, tmp_path):
    """A config that appears after an unconfigured init must be picked up."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})

    state: dict[str, object] = {"path": None}
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: state["path"]),
    )

    async def _fake_get_mcp_tools(**_kwargs):
        return []

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    asyncio.run(cache_module.initialize_mcp_tools())

    assert cache_module._cache_initialized is True
    assert cache_module._config_signature is None
    assert cache_module._initialized_without_config is True

    state["path"] = cfg

    assert cache_module._is_cache_stale() is True


def test_initialization_with_unreadable_post_signature_discards_result(cache_globals, monkeypatch, tmp_path):
    """A resolved path with an unreadable signature must not publish an unpinned cache."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    async def _fake_get_mcp_tools(**_kwargs):
        return ["loaded-tools"]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    monkeypatch.setattr(cache_module, "_current_config_state", lambda: (cfg, None))

    result = asyncio.run(cache_module.initialize_mcp_tools())

    assert result == []
    assert cache_module._cache_initialized is False
    assert cache_module._mcp_tools_cache is None


def test_lazy_init_does_not_leak_credentials_on_malformed_config(cache_globals, monkeypatch, tmp_path, caplog):
    """Lazy init must not echo resolved secrets when the config is malformed."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("MCP_SECRET", "TOPSECRET123")

    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "srv1": {"enabled": True, "type": "stdio", "command": "npx", "headers": "$MCP_SECRET"},
                },
                "skills": {},
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        assert cache_module.get_cached_mcp_tools() == []

    assert "TOPSECRET123" not in caplog.text


def _assert_cache_survives_edit(monkeypatch, cfg, sentinel, rewrite):
    """Initialize with *sentinel*, apply *rewrite*, and prove nothing was retired."""
    from deerflow.mcp.session_pool import get_session_pool, reset_session_pool

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    async def _fake_get_mcp_tools(**_kwargs):
        return [sentinel]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    asyncio.run(cache_module.initialize_mcp_tools())

    old_pool = get_session_pool()
    closed: list[bool] = []
    monkeypatch.setattr(old_pool, "close_all_sync", lambda: closed.append(True))
    try:
        rewrite()
        assert cache_module.get_cached_mcp_tools() == [sentinel]
        assert cache_module._mcp_tools_cache == [sentinel]
        assert get_session_pool() is old_pool
        assert closed == []
    finally:
        reset_session_pool()


def test_string_and_single_element_interceptor_list_are_equivalent(cache_globals, monkeypatch, tmp_path):
    """A bare string and its single-element list select the same interceptor chain."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, interceptors="pkg.interceptor:build")
    sentinel = object()
    _assert_cache_survives_edit(
        monkeypatch,
        cfg,
        sentinel,
        lambda: _write_extensions_config(cfg, {"srv1": _server()}, interceptors=["pkg.interceptor:build"]),
    )


def test_missing_and_empty_interceptors_are_equivalent(cache_globals, monkeypatch, tmp_path):
    """An absent key and an empty list both select no custom interceptors."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    sentinel = object()
    _assert_cache_survives_edit(
        monkeypatch,
        cfg,
        sentinel,
        lambda: _write_extensions_config(cfg, {"srv1": _server()}, interceptors=[]),
    )


def test_interceptor_order_change_is_still_stale(cache_globals, monkeypatch, tmp_path):
    """Order is part of the effective chain and must keep retiring the cache."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()}, interceptors=["a:build", "b:build"])
    _initialize_against(monkeypatch, cfg)

    _write_extensions_config(cfg, {"srv1": _server()}, interceptors=["b:build", "a:build"])

    assert cache_module._is_cache_stale() is True


def test_path_switch_with_equivalent_mcp_config_keeps_tools_and_pool(cache_globals, monkeypatch, tmp_path):
    """Switching to a file whose MCP slice is identical must not retire sessions."""
    from deerflow.mcp.session_pool import get_session_pool, reset_session_pool

    cfg_a = tmp_path / "a_extensions_config.json"
    cfg_b = tmp_path / "b_extensions_config.json"
    _write_extensions_config(cfg_a, {"srv1": _server()}, skills={"skill-a": {"enabled": True}})
    _write_extensions_config(cfg_b, {"srv1": _server()}, skills={"skill-a": {"enabled": False}})

    state: dict[str, object] = {"path": cfg_a}
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: state["path"]),
    )

    sentinel = object()

    async def _fake_get_mcp_tools(**_kwargs):
        return [sentinel]

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", _fake_get_mcp_tools)
    asyncio.run(cache_module.initialize_mcp_tools())

    old_pool = get_session_pool()
    closed: list[bool] = []
    monkeypatch.setattr(old_pool, "close_all_sync", lambda: closed.append(True))
    try:
        state["path"] = cfg_b

        assert cache_module.get_cached_mcp_tools() == [sentinel]
        assert get_session_pool() is old_pool
        assert closed == []
        assert cache_module._config_path == cfg_b
        assert cache_module._config_signature == get_config_signature(cfg_b)
    finally:
        reset_session_pool()


def test_path_switch_with_different_mcp_config_is_still_stale(cache_globals, monkeypatch, tmp_path):
    """A path switch to a file with a different MCP slice keeps the global reset."""
    cfg_a = tmp_path / "a_extensions_config.json"
    cfg_b = tmp_path / "b_extensions_config.json"
    _write_extensions_config(cfg_a, {"srv1": _server("npx")})
    _write_extensions_config(cfg_b, {"srv1": _server("uvx")})

    state: dict[str, object] = {"path": cfg_a}
    monkeypatch.setattr(
        ExtensionsConfig,
        "resolve_config_path",
        classmethod(lambda cls, config_path=None: state["path"]),
    )
    _initialize_against(monkeypatch, cfg_a)

    state["path"] = cfg_b

    assert cache_module._is_cache_stale() is True


def test_unverifiable_signature_is_not_treated_as_stable(cache_globals, monkeypatch, tmp_path):
    """A signature without a sha256 digest must never be published as stable."""
    cfg = tmp_path / "extensions_config.json"
    _write_extensions_config(cfg, {"srv1": _server()})
    _initialize_against(monkeypatch, cfg)

    real = cache_module._get_config_signature

    def _no_digest(path):
        signature = real(path)
        return None if signature is None else (signature[0], signature[1], None)

    monkeypatch.setattr(cache_module, "_get_config_signature", _no_digest)
    incomplete = _no_digest(cfg)
    assert incomplete is not None and incomplete[2] is None

    assert cache_module._read_stable_mcp_snapshot(cfg, incomplete) is None
    assert cache_module._is_cache_stale() is True
