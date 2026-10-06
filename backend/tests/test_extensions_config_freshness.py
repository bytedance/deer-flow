"""Freshness of the ``extensions_config.json`` process singleton.

Every Gateway process that shares one ``extensions_config.json`` (several
uvicorn workers, or several Pods on one shared volume) must observe the same
configuration. A writer reloads its own process after writing, but a peer
process only learns about the change if ``get_extensions_config()``
revalidates the cached singleton against the file. The local-bash absolute
path allowlist is derived from that singleton, so a stale copy is a security
drift between replicas, not merely a stale tool list.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    McpServerConfig,
    atomic_write_extensions_config,
    get_extensions_config,
    reload_extensions_config,
    reset_extensions_config,
    set_extensions_config,
)
from deerflow.sandbox.tools import _get_mcp_allowed_paths

_LOGGER_NAME = "deerflow.config.extensions_config"
_KEEPING_PREVIOUS = "keeping the previously loaded configuration"


def _filesystem_server_payload(*paths: str, enabled: bool = True) -> dict:
    return {
        "mcpServers": {
            "filesystem": {
                "enabled": enabled,
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", *paths],
            }
        },
        "skills": {},
    }


def _write_from_peer_process(path: Path, payload: dict) -> None:
    """Simulate a peer Gateway process: atomic write, no in-process reload."""
    atomic_write_extensions_config(path, payload)


def _allowed_paths_of(config: ExtensionsConfig) -> list[str]:
    return [arg for arg in config.mcp_servers["filesystem"].args if arg.startswith("/")]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _LOGGER_NAME and record.levelno >= logging.WARNING]


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "extensions_config.json"
    _write_from_peer_process(path, _filesystem_server_payload("/data/alpha"))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    reset_extensions_config()
    yield path
    reset_extensions_config()


def test_get_extensions_config_reflects_peer_atomic_write(config_path: Path) -> None:
    first = get_extensions_config()
    assert _allowed_paths_of(first) == ["/data/alpha"]

    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))

    second = get_extensions_config()
    assert _allowed_paths_of(second) == ["/data/beta"]
    assert second is not first


def test_get_extensions_config_keeps_instance_while_file_is_unchanged(config_path: Path) -> None:
    first = get_extensions_config()

    assert get_extensions_config() is first
    assert get_extensions_config() is first


def test_same_size_edit_with_unchanged_mtime_is_detected(config_path: Path) -> None:
    get_extensions_config()
    stat_before = config_path.stat()

    # Same byte length, and the mtime pinned back, so neither stat field can
    # reveal the edit: only the content digest does.
    _write_from_peer_process(config_path, _filesystem_server_payload("/data/alphb"))
    os.utime(config_path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    assert config_path.stat().st_size == stat_before.st_size
    assert config_path.stat().st_mtime_ns == stat_before.st_mtime_ns

    assert _allowed_paths_of(get_extensions_config()) == ["/data/alphb"]


def test_local_bash_allowlist_follows_peer_write(config_path: Path) -> None:
    assert _get_mcp_allowed_paths() == ["/data/alpha/"]

    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))
    assert _get_mcp_allowed_paths() == ["/data/beta/"]

    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta", enabled=False))
    assert _get_mcp_allowed_paths() == []


def test_half_written_file_keeps_last_known_good_and_warns_once(config_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    first = get_extensions_config()

    # atomic_write_extensions_config falls back to an in-place overwrite on a
    # bind-mounted file, so a peer can observe a truncated document.
    config_path.write_text('{"mcpServers": {"filesystem": {"enabled": true, "type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/serv', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert get_extensions_config() is first
        assert get_extensions_config() is first

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert _KEEPING_PREVIOUS in warnings[0].getMessage()
    assert str(config_path) in warnings[0].getMessage()

    # Once the writer finishes, the new revision is adopted.
    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))
    assert _allowed_paths_of(get_extensions_config()) == ["/data/beta"]


def test_invalid_revision_warning_does_not_leak_resolved_values(config_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    get_extensions_config()
    monkeypatch.setenv("EXT_FRESHNESS_SECRET", "hunter2-secret")
    # Valid JSON, invalid schema: ``args`` must be a list. The resolved
    # placeholder is the failing input, which pydantic embeds in its message.
    config_path.write_text(
        '{"mcpServers": {"filesystem": {"enabled": true, "type": "stdio", "command": "npx", "args": "$EXT_FRESHNESS_SECRET"}}, "skills": {}}',
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert _allowed_paths_of(get_extensions_config()) == ["/data/alpha"]

    assert len(_warnings(caplog)) == 1
    assert "hunter2-secret" not in caplog.text


def test_invalid_file_on_first_load_still_raises(config_path: Path) -> None:
    config_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        get_extensions_config()


def test_missing_explicit_file_on_first_load_still_raises(config_path: Path) -> None:
    config_path.unlink()

    with pytest.raises(FileNotFoundError):
        get_extensions_config()


def test_deleted_file_keeps_last_known_good_until_it_returns(config_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    first = get_extensions_config()

    config_path.unlink()
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert get_extensions_config() is first
        assert get_extensions_config() is first
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert _KEEPING_PREVIOUS in warnings[0].getMessage()

    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))
    assert _allowed_paths_of(get_extensions_config()) == ["/data/beta"]


def test_config_appearing_after_unconfigured_start_is_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)
    path = tmp_path / "extensions_config.json"
    resolved: list[Path | None] = [None]
    monkeypatch.setattr(ExtensionsConfig, "resolve_config_path", classmethod(lambda cls, config_path=None: resolved[0]))
    reset_extensions_config()
    try:
        unconfigured = get_extensions_config()
        assert unconfigured.mcp_servers == {}
        assert get_extensions_config() is unconfigured

        _write_from_peer_process(path, _filesystem_server_payload("/data/alpha"))
        resolved[0] = path
        loaded = get_extensions_config()
        assert _allowed_paths_of(loaded) == ["/data/alpha"]

        # Search mode losing the file keeps the last-known-good configuration.
        resolved[0] = None
        assert get_extensions_config() is loaded
    finally:
        reset_extensions_config()


def test_set_extensions_config_is_pinned_until_reload_or_reset(config_path: Path) -> None:
    injected = ExtensionsConfig(mcp_servers={"injected": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={})
    set_extensions_config(injected)
    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))

    assert get_extensions_config() is injected

    reloaded = reload_extensions_config()
    assert _allowed_paths_of(reloaded) == ["/data/beta"]
    assert get_extensions_config() is reloaded

    set_extensions_config(injected)
    assert get_extensions_config() is injected
    reset_extensions_config()
    assert _allowed_paths_of(get_extensions_config()) == ["/data/beta"]


def test_reload_after_own_write_records_the_written_revision(config_path: Path) -> None:
    get_extensions_config()
    _write_from_peer_process(config_path, _filesystem_server_payload("/data/beta"))

    reloaded = reload_extensions_config()

    assert _allowed_paths_of(reloaded) == ["/data/beta"]
    assert get_extensions_config() is reloaded
