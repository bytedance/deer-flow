"""Regression anchor: WeChat channel filesystem IO must not block the event loop.

Two production paths touch the filesystem, and both must stay off the asyncio
loop:

1. **Construction** — ``ChannelService._start_channel()`` instantiates the
   channel directly on the async path (``channel_cls(...)`` with no thread
   offload), so ``WechatChannel.__init__`` must be IO-free; persisted state is
   loaded later in ``start()`` via ``asyncio.to_thread``. Constructing the
   channel in an async context used to raise ``BlockingError: Blocking call to
   os.stat`` because ``__init__`` called ``_load_state`` synchronously.

2. **Runtime** — ``_handle_update`` stages downloaded inbound files
   (``mkdir`` + ``write_bytes``) and ``_ensure_authenticated`` reads persisted
   auth state (``read_text``); both offload via ``asyncio.to_thread``.

If any of this regresses back onto the event loop, the strict Blockbuster gate
raises ``BlockingError`` and these tests fail.

The constructors below are invoked *directly* on the event loop (no
``asyncio.to_thread`` wrapper) on purpose: that mirrors the production
``_start_channel`` path the gate is meant to protect. Test-only file setup
(writing the auth fixture) is still wrapped in ``asyncio.to_thread`` because
that scaffolding IO would otherwise trip the gate even though it is not the
code under test.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel, _encrypt_aes_128_ecb

pytestmark = pytest.mark.asyncio


async def test_wechat_constructor_is_io_free_on_async_path(tmp_path: Path) -> None:
    """``__init__`` must not touch the filesystem — ``_start_channel`` constructs inline."""
    bus = MessageBus()
    # Seed an auth file that WOULD restore a different token if __init__ read it.
    auth_path = tmp_path / "wechat-auth.json"
    await asyncio.to_thread(auth_path.write_text, json.dumps({"status": "confirmed", "bot_token": "from-disk"}))

    # Direct construction on the event loop, no asyncio.to_thread wrapper —
    # this is exactly the production _start_channel path. If __init__ regresses
    # to doing os.stat / read_text (e.g. re-adding _load_state here), the gate
    # raises BlockingError right at this line.
    channel = WechatChannel(bus=bus, config={"bot_token": "from-config", "state_dir": str(tmp_path)})
    # Token came from config, not the disk file — proving __init__ did not read it.
    assert channel._bot_token == "from-config"


async def test_wechat_inbound_file_staging_does_not_block_event_loop(tmp_path: Path) -> None:
    """Staging a downloaded inbound image writes through ``asyncio.to_thread``."""
    bus = MessageBus()
    published = []

    async def capture(msg):
        published.append(msg)

    bus.publish_inbound = capture  # type: ignore[method-assign]

    channel = WechatChannel(bus=bus, config={"bot_token": "test-token", "state_dir": str(tmp_path)})

    plaintext = b"fake-image-bytes"
    aes_key = b"1234567890abcdef"
    encrypted = _encrypt_aes_128_ecb(plaintext, aes_key)

    async def _fake_download(_url: str, *, timeout: float | None = None):
        return encrypted

    channel._download_cdn_bytes = _fake_download  # type: ignore[method-assign]

    await channel._handle_update(
        {
            "message_type": 1,
            "message_id": 101,
            "from_user_id": "wx-1",
            "context_token": "ctx-img",
            "item_list": [
                {
                    "type": 2,
                    "image_item": {"aeskey": aes_key.hex(), "media": {"full_url": "https://cdn.example/image.bin"}},
                }
            ],
        }
    )

    assert len(published) == 1
    assert len(published[0].files) == 1
    staged = Path(published[0].files[0]["path"])
    staged_exists = await asyncio.to_thread(staged.exists)
    assert staged_exists, "inbound image should be staged under the tmp state dir"


async def test_wechat_auth_state_load_does_not_block_event_loop(tmp_path: Path) -> None:
    """``_ensure_authenticated`` reads persisted auth state through ``asyncio.to_thread``."""
    bus = MessageBus()
    # bot_token="" forces _ensure_authenticated to fall through to the
    # _load_auth_state branch (offloaded) instead of returning early.
    channel = WechatChannel(bus=bus, config={"bot_token": "", "state_dir": str(tmp_path)})

    auth_path = tmp_path / "wechat-auth.json"
    await asyncio.to_thread(auth_path.write_text, json.dumps({"status": "confirmed", "bot_token": "loaded-token"}))

    result = await channel._ensure_authenticated()

    assert result is True
    assert channel._bot_token == "loaded-token"
