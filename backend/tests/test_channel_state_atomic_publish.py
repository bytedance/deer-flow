"""Channel JSON state must be published whole, never truncated in place.

``DiscordChannel._persist_thread_mappings`` and ``WechatChannel._save_state``
write state a crash could otherwise truncate: the Discord mapping would fail to
load and the WeChat cursor buffer would be lost, re-reading from the start. Both
now stage a sibling and replace it, and a stage that cannot be discarded is
reported instead of replacing the outcome.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.channels.discord import DiscordChannel
from app.channels.wechat import WechatChannel


def _discord(tmp_path):
    channel = DiscordChannel.__new__(DiscordChannel)
    channel._thread_store_lock = threading.Lock()
    channel._active_threads = {"a": {"thread_id": "t1"}}
    channel._thread_store_path = tmp_path / "state" / "discord-threads.json"
    return channel


def _wechat(tmp_path):
    channel = WechatChannel.__new__(WechatChannel)
    channel._cursor_path = tmp_path / "state" / "wechat-cursor.json"
    channel._get_updates_buf = "cursor-1"
    return channel


def _fail_staged_write(monkeypatch):
    """Fail the staged write the way a full disk would, before any rename.

    With the shared helper this is the earliest injectable point: the bytes are
    written to a sibling, fsync fails, and the rename never happens. The point of
    the test is that the live file is untouched by that failure.
    """

    def failing_fsync(_fd):
        raise OSError("disk full")

    monkeypatch.setattr("deerflow.utils.atomic_write.os.fsync", failing_fsync)


def _no_sidecar(target: Path) -> bool:
    prefix = f".{target.name}."
    return [p.name for p in target.parent.iterdir() if p.name.startswith(prefix)] == []


def test_discord_state_is_replaced_whole(tmp_path):
    channel = _discord(tmp_path)
    target = tmp_path / "state" / "discord-threads.json"

    channel._persist_thread_mappings()

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": {"thread_id": "t1"}}
    assert _no_sidecar(target)


def test_discord_failed_staged_write_keeps_the_previous_mapping(tmp_path, monkeypatch):
    channel = _discord(tmp_path)
    target = tmp_path / "state" / "discord-threads.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"kept": true}', encoding="utf-8")
    _fail_staged_write(monkeypatch)

    channel._persist_thread_mappings()

    assert target.read_text(encoding="utf-8") == '{"kept": true}'
    assert json.loads(target.read_text(encoding="utf-8")) == {"kept": True}
    assert _no_sidecar(target)


def test_wechat_state_is_replaced_whole(tmp_path):
    channel = _wechat(tmp_path)
    target = tmp_path / "state" / "wechat-cursor.json"

    channel._save_state()

    assert json.loads(target.read_text(encoding="utf-8")) == {"get_updates_buf": "cursor-1"}
    assert _no_sidecar(target)


def test_wechat_failed_staged_write_keeps_the_previous_cursor(tmp_path, monkeypatch):
    channel = _wechat(tmp_path)
    target = tmp_path / "state" / "wechat-cursor.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"get_updates_buf": "kept"}', encoding="utf-8")
    _fail_staged_write(monkeypatch)

    channel._save_state()

    assert json.loads(target.read_text(encoding="utf-8")) == {"get_updates_buf": "kept"}
    assert _no_sidecar(target)


def _fail_staged_write_and_cleanup(monkeypatch):
    """Fail the staged write, and fail discarding the staged sibling too."""

    def failing_fsync(_fd):
        raise OSError("disk full")

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name.startswith(".") and self.name.endswith(".tmp"):
            raise PermissionError("staging is still open")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr("deerflow.utils.atomic_write.os.fsync", failing_fsync)
    monkeypatch.setattr(Path, "unlink", failing_unlink)


def test_discord_failed_cleanup_still_reports_and_keeps_the_outcome(tmp_path, monkeypatch, caplog):
    """A discard that fails must not escape, and both failures stay visible."""
    channel = _discord(tmp_path)
    target = tmp_path / "state" / "discord-threads.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"kept": true}', encoding="utf-8")
    _fail_staged_write_and_cleanup(monkeypatch)
    caplog.clear()

    with caplog.at_level("WARNING"):
        channel._persist_thread_mappings()

    assert target.read_text(encoding="utf-8") == '{"kept": true}'
    assert "failed to persist thread mappings" in caplog.text
    assert "Failed to remove temporary output file" in caplog.text


def test_wechat_failed_cleanup_still_reports_and_keeps_the_outcome(tmp_path, monkeypatch, caplog):
    channel = _wechat(tmp_path)
    target = tmp_path / "state" / "wechat-cursor.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"get_updates_buf": "kept"}', encoding="utf-8")
    _fail_staged_write_and_cleanup(monkeypatch)
    caplog.clear()

    with caplog.at_level("WARNING"):
        channel._save_state()

    assert target.read_text(encoding="utf-8") == '{"get_updates_buf": "kept"}'
    assert "failed to persist cursor state" in caplog.text
    assert "Failed to remove temporary output file" in caplog.text
