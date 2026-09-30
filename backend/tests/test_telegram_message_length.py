"""Telegram caps messages at 4096 UTF-16 code units, not at 4096 Python code points."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.channels import telegram
from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.telegram import TELEGRAM_MAX_MESSAGE_LENGTH, TelegramChannel

# U+1F600 GRINNING FACE: one code point for Python, two UTF-16 code units for Telegram.
EMOJI = "\U0001f600"

# A reserved code point outside the BMP; only its width matters here.
ASTRAL = "\U00100000"


def utf16_units(text: str) -> int:
    """A codec-backed oracle, so a wrong production formula cannot ratify itself."""
    return len(text.encode("utf-16-le")) // 2


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _channel_with_bot():
    ch = TelegramChannel(bus=MessageBus(), config={"bot_token": "test-token"})
    bot = SimpleNamespace(sent=[], next_message_id=100)

    async def send_message(**kwargs):
        bot.sent.append(kwargs)
        result = MagicMock()
        result.message_id = bot.next_message_id
        bot.next_message_id += 1
        return result

    bot.send_message = send_message
    application = MagicMock()
    application.bot = bot
    ch._application = application
    return ch, bot


@pytest.mark.parametrize("char", ["a", "é", "中", chr(0x200D), EMOJI, ASTRAL])
def test_utf16_width_agrees_with_the_codec(char):
    assert telegram._utf16_width(char) == utf16_units(char)


def test_split_message_keeps_every_chunk_within_the_utf16_limit():
    text = EMOJI * 3000  # 3000 code points, 6000 UTF-16 code units

    chunks = TelegramChannel._split_message(text)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(utf16_units(chunk) <= TELEGRAM_MAX_MESSAGE_LENGTH for chunk in chunks)


def test_split_message_does_not_split_a_non_bmp_character_across_chunks():
    assert TelegramChannel._split_message("x" * 4095 + EMOJI) == ["x" * 4095, EMOJI]


def test_split_message_still_slices_bmp_text_at_the_limit():
    assert TelegramChannel._split_message("a" * 4096 + "b" * 100) == ["a" * 4096, "b" * 100]
    assert TelegramChannel._split_message("") == [""]


def test_first_utf16_chunk_returns_text_that_fits():
    text = "x" * TELEGRAM_MAX_MESSAGE_LENGTH

    assert telegram._first_utf16_chunk(text, TELEGRAM_MAX_MESSAGE_LENGTH) == (text, False)


def test_first_utf16_chunk_leaves_out_the_character_that_crosses_the_limit():
    text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH - 1)

    assert telegram._first_utf16_chunk(text + EMOJI, TELEGRAM_MAX_MESSAGE_LENGTH) == (text, True)


def test_send_splits_an_emoji_heavy_final_reply_into_sendable_chunks():
    async def go():
        ch, bot = _channel_with_bot()
        text = EMOJI * 3000

        await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=text))

        sent = [entry["text"] for entry in bot.sent]
        assert len(sent) > 1
        assert "".join(sent) == text
        assert all(utf16_units(chunk) <= TELEGRAM_MAX_MESSAGE_LENGTH for chunk in sent)

    _run(go())


def test_stream_update_clips_emoji_heavy_text_to_the_utf16_limit():
    async def go():
        ch, bot = _channel_with_bot()

        await ch._send_stream_update(12345, "12345:42", EMOJI * 3000)

        display = bot.sent[0]["text"]
        assert utf16_units(display) <= TELEGRAM_MAX_MESSAGE_LENGTH
        assert display.endswith("…")
        assert ch._stream_messages["12345:42"]["last_text"] == display

    _run(go())


def test_stream_update_clips_without_measuring_the_whole_reply(monkeypatch):
    """Each update republishes the growing cumulative reply, so clipping must cost the limit, not the reply."""
    measured = 0
    real_width = telegram._utf16_width

    def counting_width(char: str) -> int:
        nonlocal measured
        measured += 1
        return real_width(char)

    monkeypatch.setattr(telegram, "_utf16_width", counting_width)

    async def go():
        ch, bot = _channel_with_bot()

        await ch._send_stream_update(12345, "12345:42", "x" * 200_000)

        return bot.sent[0]["text"]

    display = _run(go())

    assert utf16_units(display) <= TELEGRAM_MAX_MESSAGE_LENGTH
    assert display.endswith("…")
    # Bounded by the limit twice (measure against it, then clip one unit shorter), not by 200,000 characters.
    assert measured <= 2 * (TELEGRAM_MAX_MESSAGE_LENGTH + 1)
