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


def _truncating_write_text(monkeypatch):
    """Write half the payload, then fail the way a full disk or a crash would."""
    real_write_bytes = Path.write_bytes

    def partial(self, data, *args, **kwargs):
        payload = data.encode("utf-8") if isinstance(data, str) else data
        real_write_bytes(self, payload[: len(payload) // 2])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", partial)


def _no_sidecar(target: Path) -> bool:
    prefix = f".{target.name}."
    return [p.name for p in target.parent.iterdir() if p.name.startswith(prefix)] == []


def test_discord_state_is_replaced_whole(tmp_path):
    channel = _discord(tmp_path)
    target = tmp_path / "state" / "discord-threads.json"

    channel._persist_thread_mappings()

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": {"thread_id": "t1"}}
    assert _no_sidecar(target)


def test_discord_interrupted_write_keeps_the_previous_mapping(tmp_path, monkeypatch):
    channel = _discord(tmp_path)
    target = tmp_path / "state" / "discord-threads.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"kept": true}', encoding="utf-8")
    _truncating_write_text(monkeypatch)

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


def test_wechat_interrupted_write_keeps_the_previous_cursor(tmp_path, monkeypatch):
    channel = _wechat(tmp_path)
    target = tmp_path / "state" / "wechat-cursor.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"get_updates_buf": "kept"}', encoding="utf-8")
    _truncating_write_text(monkeypatch)

    channel._save_state()

    assert json.loads(target.read_text(encoding="utf-8")) == {"get_updates_buf": "kept"}
    assert _no_sidecar(target)
