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
import os
from pathlib import Path

import pytest

import deerflow.mcp.cache as cache_module
from deerflow.config.extensions_config import ExtensionsConfig

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
    "_initialization_lock",
)


def _write_extensions_config(path: Path, servers: dict) -> None:
    path.write_text(json.dumps({"mcpServers": servers, "skills": {}}), encoding="utf-8")


def _server(command: str = "npx") -> dict:
    return {"enabled": True, "type": "stdio", "command": command}


@pytest.fixture()
def cache_globals():
    """Snapshot/restore ``deerflow.mcp.cache`` module globals and reset the lock."""
    saved = {name: getattr(cache_module, name, _MISSING) for name in _TRACKED_GLOBALS}

    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    for name in ("_config_path", "_config_signature", "_config_mtime"):
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
    # asyncio.Lock binds to the first event loop it is awaited on, so each test
    # (which drives initialize_mcp_tools via a fresh asyncio.run) needs its own.
    cache_module._initialization_lock = asyncio.Lock()

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

    async def _fake_get_mcp_tools():
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
    ``ExtensionsConfig.resolve_config_path``'s separate not-found contract for
    explicit path/env-var configuration (that function raises
    ``FileNotFoundError`` in that mode instead of returning ``None`` — a
    distinct, pre-existing latent issue outside this module's scope).
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
