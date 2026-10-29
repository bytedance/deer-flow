"""Restart cleanup only owns stale, explicitly named credential staging files."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.channels.message_bus import MessageBus
from app.channels.runtime_config_store import ChannelRuntimeConfigStore, SqlChannelRuntimeConfigStore
from app.channels.wechat import WechatChannel


def _age(path: Path) -> None:
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(path, (old, old), follow_symlinks=False)


def _load(kind: str, target: Path):
    if kind == "runtime":
        return ChannelRuntimeConfigStore(target).get_provider_config("slack")
    channel = WechatChannel(bus=MessageBus(), config={"state_dir": str(target.parent)})
    channel._load_state()
    return channel._auth_state


@pytest.mark.parametrize("kind", ["runtime", "wechat"])
@pytest.mark.parametrize("destination_exists", [True, False])
def test_restart_sweeps_crash_orphans_without_touching_other_state(tmp_path, monkeypatch, kind, destination_exists):
    target = tmp_path / ("runtime-config.json" if kind == "runtime" else "wechat-auth.json")
    if kind == "runtime":
        store = ChannelRuntimeConfigStore(target)

        def save(token):
            store._save({"slack": {"bot_token": token}})
    else:
        channel = WechatChannel(bus=MessageBus(), config={"state_dir": str(tmp_path)})

        def save(token):
            channel._save_auth_state(status="confirmed", bot_token=token)

    save("current-token")
    current_bytes = target.read_bytes()
    real_replace = Path.replace
    real_unlink = Path.unlink

    def fail_publish(path, destination):
        if destination == target:
            raise OSError("publication interrupted")
        return real_replace(path, destination)

    def fail_cleanup(path, *args, **kwargs):
        if path.suffix == ".tmp":
            raise PermissionError("cleanup interrupted")
        return real_unlink(path, *args, **kwargs)

    # Leave the same files a hard crash would leave, using the actual writers.
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publish)
        patch.setattr(Path, "unlink", fail_cleanup)
        for token in ("orphan-token", "inflight-token"):
            if kind == "runtime":
                with pytest.raises(OSError, match="publication interrupted"):
                    save(token)
            else:
                save(token)
    staged = list(tmp_path.glob("*.tmp"))
    assert len(staged) == 2
    orphan, fresh = staged
    assert all(path.name.startswith(f".{target.name}.deerflow-") for path in staged)
    if os.name != "nt":
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in staged)
    _age(orphan)
    recent = time.time() - 23 * 60 * 60
    os.utime(fresh, (recent, recent))

    # Even old generic tempfile names cannot be attributed to this store.
    retained = [tmp_path / name for name in ("backup.tmp", "tmpabcdefgh.tmp", ".other.json.deerflow-old.tmp")]
    for path in retained:
        path.write_text("unrelated", encoding="utf-8")
        _age(path)
    directory = tmp_path / f".{target.name}.deerflow-directory.tmp"
    directory.mkdir()
    _age(directory)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    nested = downloads / orphan.name
    nested.write_text("attachment", encoding="utf-8")
    _age(nested)
    if os.name != "nt":
        link = tmp_path / f".{target.name}.deerflow-symlink.tmp"
        link.symlink_to(retained[0])
        _age(link)
        retained.append(link)
    if not destination_exists:
        target.unlink()

    loaded = _load(kind, target)

    assert not orphan.exists()
    assert fresh.exists(), "a peer may still be writing a fresh staging file"
    assert all(path.exists() for path in retained)
    assert directory.is_dir()
    assert nested.read_text(encoding="utf-8") == "attachment"
    if destination_exists:
        assert target.read_bytes() == current_bytes
        config = loaded if kind == "wechat" else loaded or {}
        assert config["bot_token"] == "current-token"
    else:
        assert not target.exists()
        assert not loaded


@pytest.mark.parametrize("kind", ["runtime", "wechat"])
@pytest.mark.parametrize("broken_handler", [False, True])
def test_orphan_cleanup_failure_does_not_skip_other_files_or_loading(tmp_path, monkeypatch, caplog, kind, broken_handler):
    target = tmp_path / ("runtime-config.json" if kind == "runtime" else "wechat-auth.json")
    config = {"bot_token": "current-token"}
    target.write_text(json.dumps({"slack": config} if kind == "runtime" else config), encoding="utf-8")
    failed = tmp_path / f".{target.name}.deerflow-failed.tmp"
    other = tmp_path / f".{target.name}.deerflow-other.tmp"
    for path in (failed, other):
        path.write_text("stale-credential", encoding="utf-8")
        _age(path)
    real_unlink = Path.unlink
    failure = PermissionError("stale copy is locked")

    def fail_one_unlink(path, *args, **kwargs):
        if path == failed:
            raise failure
        return real_unlink(path, *args, **kwargs)

    logger = logging.getLogger("app.channels.credential_staging")
    handler = logging.FileHandler(tmp_path / "missing-log-directory" / "output.log", delay=True) if broken_handler else None
    if handler is not None:
        logger.addHandler(handler)
    try:
        with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
            patch.setattr(Path, "unlink", fail_one_unlink)
            assert _load(kind, target)["bot_token"] == "current-token"
    finally:
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()

    assert failed.exists()
    assert not other.exists()
    if not broken_handler:
        records = [record for record in caplog.records if str(failed) in record.getMessage()]
        assert len(records) == 1
        assert records[0].exc_info[1] is failure


@pytest.mark.parametrize("kind", ["runtime", "wechat"])
def test_unreadable_staging_directory_does_not_prevent_loading_current_credentials(tmp_path, monkeypatch, kind):
    target = tmp_path / ("runtime-config.json" if kind == "runtime" else "wechat-auth.json")
    config = {"bot_token": "current-token"}
    target.write_text(json.dumps({"slack": config} if kind == "runtime" else config), encoding="utf-8")
    real_scandir = os.scandir

    def unreadable(path):
        if Path(path) == tmp_path:
            raise PermissionError("directory listing denied")
        return real_scandir(path)

    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", unreadable)
        assert _load(kind, target)["bot_token"] == "current-token"


def test_database_startup_sweeps_staging_even_after_the_legacy_file_was_removed(tmp_path):
    target = tmp_path / "runtime-config.json"
    orphan = tmp_path / f".{target.name}.deerflow-orphan.tmp"
    orphan.write_text("plaintext-credential", encoding="utf-8")
    _age(orphan)
    repo = Mock()
    store = SqlChannelRuntimeConfigStore(repo, cipher=None, legacy_path=target)

    assert store.import_legacy_json() == 0

    assert not orphan.exists()
    repo.insert_missing.assert_not_called()
