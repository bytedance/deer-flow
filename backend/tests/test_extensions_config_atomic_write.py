"""Regression tests for crash-safe extensions config writes."""

from __future__ import annotations

import errno
import json
import logging
import multiprocessing
import os
import queue
import stat
from pathlib import Path

import pytest

from deerflow.config import extensions_config as extensions_config_module
from deerflow.config.extensions_config import atomic_write_extensions_config, extensions_config_file_lock


def _temporary_files_for(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def _locked_rmw_worker(
    config_path: str,
    key: str,
    entered: multiprocessing.Queue,
    release_first: multiprocessing.Event,
) -> None:
    path = Path(config_path)
    with extensions_config_file_lock(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        entered.put(key)
        if key == "first":
            if not release_first.wait(timeout=5):
                raise TimeoutError("parent did not release first writer")
        data[key] = True
        path.write_text(json.dumps(data), encoding="utf-8")


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


def test_atomic_write_falls_back_in_place_when_destination_is_a_mount_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Docker mounts extensions_config.json as its own mount point, and the kernel
    answers rename-over-a-mount-point with EBUSY. The write must still land."""
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    original_inode = config_path.stat().st_ino

    def refuse_replace(_source, _destination) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(extensions_config_module.os, "replace", refuse_replace)

    atomic_write_extensions_config(
        config_path,
        {"mcpServers": {"github": {"enabled": True}}, "skills": {}},
    )

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "mcpServers": {"github": {"enabled": True}},
        "skills": {},
    }
    # The destination inode must survive: replacing it is exactly what the
    # kernel refused, and a mount point that got unlinked would break the mount.
    assert config_path.stat().st_ino == original_inode
    assert _temporary_files_for(config_path) == []


def test_atomic_write_fallback_warns_once_per_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    def refuse_replace(_source, _destination) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(extensions_config_module.os, "replace", refuse_replace)
    caplog.set_level(logging.DEBUG, logger=extensions_config_module.__name__)

    atomic_write_extensions_config(config_path, {"mcpServers": {"one": {}}, "skills": {}})
    atomic_write_extensions_config(config_path, {"mcpServers": {"two": {}}, "skills": {}})

    fallback_records = [record for record in caplog.records if "Cannot atomically replace" in record.message]
    assert [record.levelno for record in fallback_records] == [logging.WARNING, logging.DEBUG]


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires POSIX fork and advisory file locks")
def test_extensions_config_file_lock_serializes_cross_process_read_modify_write(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text("{}", encoding="utf-8")
    context = multiprocessing.get_context("fork")
    entered = context.Queue()
    release_first = context.Event()

    first = context.Process(target=_locked_rmw_worker, args=(str(config_path), "first", entered, release_first))
    second = context.Process(target=_locked_rmw_worker, args=(str(config_path), "second", entered, release_first))
    first.start()
    assert entered.get(timeout=5) == "first"
    second.start()
    with pytest.raises(queue.Empty):
        entered.get(timeout=0.2)

    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert first.exitcode == 0
    assert second.exitcode == 0
    assert entered.get(timeout=5) == "second"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"first": True, "second": True}


def test_atomic_write_propagates_non_ebusy_replace_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only EBUSY means "rename is impossible here"; other errors are real failures."""
    config_path = tmp_path / "extensions_config.json"
    original = '{"mcpServers": {}, "skills": {}}'
    config_path.write_text(original, encoding="utf-8")

    def fail_replace(_source, _destination) -> None:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(extensions_config_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="Permission denied"):
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
