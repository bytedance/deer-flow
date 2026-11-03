"""Undecodable channel state follows the corrupt-state recovery policy, not a crash.

``app/channels/store.py`` recovers from a state file whose bytes are not UTF-8
(``_read_legacy_file`` catches ``UnicodeDecodeError`` and starts fresh), and its
AGENTS.md states that rule for channel store JSON. The other state readers in the
same package read the same kind of file with an explicit ``encoding="utf-8"`` but
only catch ``json.JSONDecodeError`` and ``OSError``; ``UnicodeDecodeError`` is a
``ValueError``, not an ``OSError``, so it escapes and the channel cannot start.

Each test writes undecodable bytes into the file that reader owns and asserts the
documented outcome: a warning, the in-memory fallback, and the file left in place.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.channels import runtime_config_store
from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel

UNDECODABLE = b'{"enabled": "\xff"}'


def test_runtime_config_store_starts_fresh_on_undecodable_state(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "channels" / "runtime-config.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(UNDECODABLE)

    with caplog.at_level(logging.WARNING, logger="app.channels.runtime_config_store"):
        store = runtime_config_store.ChannelRuntimeConfigStore(path)

    assert store.get_provider_config("buzz") is None
    assert "Corrupt channel runtime config store" in caplog.text
    assert path.read_bytes() == UNDECODABLE


def test_runtime_config_store_reports_the_peer_copy_on_undecodable_state(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The reload path under ``_mutation`` must fall back to this process's copy."""
    path = tmp_path / "channels" / "runtime-config.json"
    store = runtime_config_store.ChannelRuntimeConfigStore(path)
    store.set_provider_config("buzz", {"enabled": True})
    path.write_bytes(UNDECODABLE)

    with caplog.at_level(logging.WARNING, logger="app.channels.runtime_config_store"):
        store.set_provider_config("slack", {"enabled": True})

    assert "rewriting it from this process's copy" in caplog.text
    assert store.get_provider_config("buzz") == {"enabled": True}


@pytest.mark.asyncio
async def test_wechat_starts_on_undecodable_state(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "wechat-getupdates.json").write_bytes(UNDECODABLE)
    channel = WechatChannel(MessageBus(), config={"bot_token": "test-token", "state_dir": str(tmp_path)})

    with caplog.at_level(logging.WARNING, logger="app.channels.wechat"):
        channel._load_state()

    assert channel._get_updates_buf == ""
    assert "failed to read cursor state" in caplog.text


@pytest.mark.asyncio
async def test_wechat_starts_on_undecodable_auth_state(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "wechat-auth.json").write_bytes(UNDECODABLE)
    channel = WechatChannel(MessageBus(), config={"bot_token": "", "state_dir": str(tmp_path), "qrcode_login_enabled": True})

    with caplog.at_level(logging.WARNING, logger="app.channels.wechat"):
        channel._load_auth_state()

    assert channel._bot_token == ""
    assert "failed to read auth state" in caplog.text
    assert json.dumps({}) == "{}"
