"""Regression tests for the WeCom outbound content byte limit (#5140).

Both outbound paths in ``WeComChannel._send_ws`` previously sent unbounded
text while the bot protocol caps content at 20480 UTF-8 bytes. The stream
reply path now clips on a character boundary with a truncation marker, and
the proactive push path splits into sequential markdown messages.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.wecom import (
    _WECOM_MAX_CONTENT_BYTES,
    WeComChannel,
    _clip_to_byte_limit,
    _split_for_byte_limit,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


class TestClipToByteLimit:
    def test_short_text_passes_through(self):
        assert _clip_to_byte_limit("hello", 100) == "hello"

    def test_exact_limit_passes_through(self):
        text = "a" * _WECOM_MAX_CONTENT_BYTES
        assert _clip_to_byte_limit(text, _WECOM_MAX_CONTENT_BYTES) == text

    def test_multibyte_cut_never_splits_a_character(self):
        # One 3-byte character straddling the budget cut.
        text = "a" * 100 + "汉" * 100
        clipped = _clip_to_byte_limit(text, 105)
        assert clipped.endswith("(truncated)")
        assert _byte_len(clipped) <= 105
        assert "汉" not in clipped

    def test_full_width_report_stays_within_protocol_cap(self):
        text = "深度报告" * 10000
        clipped = _clip_to_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert _byte_len(clipped) <= _WECOM_MAX_CONTENT_BYTES
        assert clipped.endswith("(truncated)")


class TestSplitForByteLimit:
    def test_short_text_is_single_chunk(self):
        assert _split_for_byte_limit("hello", 100) == ["hello"]

    def test_each_chunk_within_limit_and_content_preserved(self):
        text = "\n".join(f"line {i} " + "字" * 50 for i in range(200))
        chunks = _split_for_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert len(chunks) > 1
        for chunk in chunks:
            assert _byte_len(chunk) <= _WECOM_MAX_CONTENT_BYTES
        # Exact round trip: the sequential messages must rebuild the original
        # text byte for byte, delimiters included.
        assert "".join(chunks) == text

    def test_boundary_newline_lands_on_chunk_tail(self):
        # Regression for the review on #5148: a boundary delimiter used to be
        # stripped by lstrip, so one newline per split silently vanished.
        text = "ab\ncd\n" + "x" * (_WECOM_MAX_CONTENT_BYTES * 2)
        chunks = _split_for_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert "".join(chunks) == text

    def test_leading_blank_lines_are_content_not_dropped(self):
        text = "第一段\n\n\n" + "字" * (_WECOM_MAX_CONTENT_BYTES * 2)
        chunks = _split_for_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert "".join(chunks) == text

    def test_no_newline_falls_back_to_hard_cut(self):
        text = "x" * (_WECOM_MAX_CONTENT_BYTES * 2 + 500)
        chunks = _split_for_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert len(chunks) == 3
        for chunk in chunks:
            assert _byte_len(chunk) <= _WECOM_MAX_CONTENT_BYTES
        assert "".join(chunks) == text


class TestSendWsContentLimit:
    def _channel(self) -> WeComChannel:
        ch = WeComChannel(bus=MessageBus(), config={})
        ch._ws_client = AsyncMock()
        return ch

    def test_stream_reply_clips_overlong_snapshot(self):
        ch = self._channel()
        ch._ws_frames["t1"] = {"frame": 1}
        ch._ws_stream_ids["t1"] = "stream-1"
        msg = OutboundMessage(
            channel_name="wecom",
            chat_id="c1",
            thread_id="th1",
            text="报告" * 20000,
            is_final=True,
            thread_ts="t1",
        )
        _run(ch._send_ws(msg))
        ch._ws_client.reply_stream.assert_called_once()
        sent = ch._ws_client.reply_stream.call_args[0][2]
        assert _byte_len(sent) <= _WECOM_MAX_CONTENT_BYTES
        assert sent.endswith("(truncated)")

    def test_stream_reply_short_text_untouched(self):
        ch = self._channel()
        ch._ws_frames["t1"] = {"frame": 1}
        ch._ws_stream_ids["t1"] = "stream-1"
        msg = OutboundMessage(
            channel_name="wecom",
            chat_id="c1",
            thread_id="th1",
            text="short reply",
            is_final=False,
            thread_ts="t1",
        )
        _run(ch._send_ws(msg))
        assert ch._ws_client.reply_stream.call_args[0][2] == "short reply"

    def test_proactive_push_splits_into_sequential_markdown_messages(self):
        ch = self._channel()
        msg: OutboundMessage = OutboundMessage(
            channel_name="wecom",
            chat_id="c1",
            thread_id="th1",
            text="推送内容\n" * 5000,
            thread_ts=None,
        )
        _run(ch._send_ws(msg))
        calls = ch._ws_client.send_message.call_args_list
        assert len(calls) > 1
        for call in calls:
            body: dict[str, Any] = call[0][1]
            assert body["msgtype"] == "markdown"
            assert _byte_len(body["markdown"]["content"]) <= _WECOM_MAX_CONTENT_BYTES

    def test_proactive_push_short_text_single_message(self):
        ch = self._channel()
        msg = OutboundMessage(
            channel_name="wecom",
            chat_id="c1",
            thread_id="th1",
            text="short push",
            thread_ts=None,
        )
        _run(ch._send_ws(msg))
        ch._ws_client.send_message.assert_called_once()


class TestSendWsChatSerialization:
    """Review on #5148: manager workers run concurrently, and each chunk send
    awaits, so two long pushes to the same chat used to interleave (A1, B1,
    A2, B2). The per-chat lock must keep each batch contiguous.
    """

    @staticmethod
    def _recording_channel():
        ch = WeComChannel(bus=MessageBus(), config={})
        sent: list[tuple[str, str]] = []

        class RecordingClient:
            async def send_message(self, chat_id, body):
                sent.append((chat_id, body["markdown"]["content"]))
                # Yield so a lockless batch would interleave with the other
                # coroutine after every single chunk.
                await asyncio.sleep(0)

        ch._ws_client = RecordingClient()
        return ch, sent

    @staticmethod
    def _push(chat_id: str, text: str) -> OutboundMessage:
        return OutboundMessage(
            channel_name="wecom",
            chat_id=chat_id,
            thread_id="th1",
            text=text,
            thread_ts=None,
        )

    def test_concurrent_batches_to_same_chat_stay_contiguous(self):
        ch, sent = self._recording_channel()
        text_a = "\n".join(f"报告甲 第{i}段 " + "字" * 50 for i in range(400))
        text_b = "\n".join(f"推送乙 第{i}段 " + "文" * 50 for i in range(400))
        chunks_a = _split_for_byte_limit(text_a, _WECOM_MAX_CONTENT_BYTES)
        chunks_b = _split_for_byte_limit(text_b, _WECOM_MAX_CONTENT_BYTES)
        assert len(chunks_a) > 1 and len(chunks_b) > 1

        async def both():
            await asyncio.gather(
                ch._send_ws(self._push("c1", text_a)),
                ch._send_ws(self._push("c1", text_b)),
            )

        _run(both())
        contents = [content for _, content in sent]
        # Either batch order is fine; what matters is no interleaving.
        assert contents in (chunks_a + chunks_b, chunks_b + chunks_a)

    def test_different_chats_keep_their_own_order(self):
        ch, sent = self._recording_channel()
        text_a = "\n".join(f"给甲群 第{i}段 " + "字" * 50 for i in range(300))
        text_b = "\n".join(f"给乙群 第{i}段 " + "文" * 50 for i in range(300))

        async def both():
            await asyncio.gather(
                ch._send_ws(self._push("chat-a", text_a)),
                ch._send_ws(self._push("chat-b", text_b)),
            )

        _run(both())
        # Different chats may interleave freely, but each chat's own chunks
        # must arrive in order and complete.
        assert [c for chat, c in sent if chat == "chat-a"] == _split_for_byte_limit(text_a, _WECOM_MAX_CONTENT_BYTES)
        assert [c for chat, c in sent if chat == "chat-b"] == _split_for_byte_limit(text_b, _WECOM_MAX_CONTENT_BYTES)


class TestEmojiBoundaries:
    def test_split_all_emoji_input_terminates_and_preserves(self):
        # 4-byte emoji only: a byte cut lands mid-character, and the split must
        # carry that character into the next chunk rather than dropping it.
        text = "😀" * 10000
        chunks = _split_for_byte_limit(text, _WECOM_MAX_CONTENT_BYTES)
        assert len(chunks) == 2
        assert "".join(chunks) == text
        assert all(_byte_len(c) <= _WECOM_MAX_CONTENT_BYTES for c in chunks)

    def test_split_tiny_limit_with_emoji_never_loops_or_loses(self):
        chunks = _split_for_byte_limit("😀" * 10, 9)
        assert "".join(chunks) == "😀" * 10
        assert all(_byte_len(c) <= 9 for c in chunks)

    def test_clip_at_emoji_boundary_stays_within_budget(self):
        out = _clip_to_byte_limit("😀" * 10000, 105)
        assert _byte_len(out) <= 105
        assert out.endswith("(truncated)")
