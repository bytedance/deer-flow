"""Regression tests for crash-safe extensions config writes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from deerflow.config import extensions_config as extensions_config_module
from deerflow.config.extensions_config import atomic_write_extensions_config


def _temporary_files_for(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_atomic_write_replaces_config_without_leaving_temp_files(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"old": true}', encoding="utf-8")

    atomic_write_extensions_config(
        config_path,
        {
            "mcpServers": {"github": {"enabled": False}},
            "skills": {"research": {"enabled": True}},
        },
    )

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "mcpServers": {"github": {"enabled": False}},
        "skills": {"research": {"enabled": True}},
    }
    assert _temporary_files_for(config_path) == []


def test_atomic_write_preserves_original_when_json_dump_fails_mid_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "extensions_config.json"
    original = '{"mcpServers": {"github": {"enabled": true}}, "skills": {}}'
    config_path.write_text(original, encoding="utf-8")

    def fail_after_partial_write(_data, file_handle, **_kwargs) -> None:
        file_handle.write('{"mcpServers":')
        file_handle.flush()
        raise OSError("disk full")

    monkeypatch.setattr(extensions_config_module.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="disk full"):
        atomic_write_extensions_config(
            config_path,
            {"mcpServers": {"github": {"enabled": False}}, "skills": {}},
        )

    assert config_path.read_text(encoding="utf-8") == original
    assert _temporary_files_for(config_path) == []


def test_atomic_write_preserves_original_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "extensions_config.json"
    original = '{"mcpServers": {}, "skills": {}}'
    config_path.write_text(original, encoding="utf-8")

    def fail_replace(_source, _destination) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(extensions_config_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_extensions_config(
            config_path,
            {"mcpServers": {"github": {"enabled": True}}, "skills": {}},
        )

    assert config_path.read_text(encoding="utf-8") == original
    assert _temporary_files_for(config_path) == []


def test_atomic_write_preserves_original_when_file_fsync_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "extensions_config.json"
    original = '{"mcpServers": {}, "skills": {}}'
    config_path.write_text(original, encoding="utf-8")

    def fail_fsync(_file_descriptor) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(extensions_config_module.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        atomic_write_extensions_config(
            config_path,
            {"mcpServers": {"github": {"enabled": True}}, "skills": {}},
        )

    assert config_path.read_text(encoding="utf-8") == original
    assert _temporary_files_for(config_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits unavailable")
def test_atomic_write_preserves_existing_file_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    config_path.chmod(0o640)

    atomic_write_extensions_config(
        config_path,
        {"mcpServers": {}, "skills": {"research": {"enabled": False}}},
    )

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o640


def test_atomic_write_updates_symlink_target_without_replacing_symlink(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "actual-extensions-config.json"
    target_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    config_path = tmp_path / "extensions_config.json"
    try:
        config_path.symlink_to(target_path)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")

    atomic_write_extensions_config(
        config_path,
        {"mcpServers": {"github": {"enabled": False}}, "skills": {}},
    )

    assert config_path.is_symlink()
    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "mcpServers": {"github": {"enabled": False}},
        "skills": {},
    }
