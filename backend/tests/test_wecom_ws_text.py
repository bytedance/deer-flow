"""Regression tests for WeComChannel._on_ws_text quote parsing.

A quoted non-text message (or any payload where ``quote``/``quote.text``/
``quote.text.content`` is JSON ``null``) must not crash the text handler.
``dict.get(key, default)`` returns the stored ``None`` when the key is present
with a null value, so chaining ``.get``/``.strip`` on it raised
``AttributeError`` before the fix.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from app.channels.message_bus import MessageBus
from app.channels.wecom import WeComChannel


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _channel() -> WeComChannel:
    ch = WeComChannel(bus=MessageBus(), config={})
    # Bypass the real websocket publish path so the test exercises only the
    # frame-parsing logic in _on_ws_text.
    ch._publish_ws_inbound = AsyncMock()  # type: ignore[method-assign]
    return ch


class TestOnWsTextQuoteParsing:
    def test_quote_is_null_does_not_crash(self):
        ch = _channel()
        frame: dict[str, Any] = {"body": {"quote": None}}
        _run(ch._on_ws_text(frame))
        # Empty text and empty quote -> handler returns early, no publish.
        ch._publish_ws_inbound.assert_not_called()

    def test_quote_text_is_null_does_not_crash(self):
        ch = _channel()
        frame: dict[str, Any] = {"body": {"quote": {"text": None}}}
        _run(ch._on_ws_text(frame))
        ch._publish_ws_inbound.assert_not_called()

    def test_quote_content_is_null_does_not_crash(self):
        ch = _channel()
        frame: dict[str, Any] = {"body": {"quote": {"text": {"content": None}}}}
        _run(ch._on_ws_text(frame))
        ch._publish_ws_inbound.assert_not_called()

    def test_text_with_null_quote_still_publishes(self):
        # This is the crash the fix targets: a real text message that also
        # carries a null ``quote`` (e.g. quoting a non-text message) used to
        # raise AttributeError before reaching _publish_ws_inbound.
        ch = _channel()
        frame: dict[str, Any] = {"body": {"text": {"content": "hello"}, "quote": None}}
        _run(ch._on_ws_text(frame))
        ch._publish_ws_inbound.assert_called_once_with(frame, "hello")

    def test_text_and_valid_quote_are_combined(self):
        ch = _channel()
        frame: dict[str, Any] = {
            "body": {"text": {"content": "T"}, "quote": {"text": {"content": "Q"}}},
        }
        _run(ch._on_ws_text(frame))
        ch._publish_ws_inbound.assert_called_once_with(frame, "T\nQuote message: Q")
