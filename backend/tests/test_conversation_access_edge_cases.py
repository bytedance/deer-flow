"""Transcript fidelity, link compatibility, and bounded read edge cases."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from test_conversation_access import _put, _setup

from app.gateway.conversation_access import _visible_text


def test_multipart_text_preserves_rendered_block_boundaries():
    row = {"content": {"type": "ai", "content": [{"type": "text", "text": "12"}, {"type": "text", "text": "34"}]}}

    assert _visible_text(row) == ("assistant", "12\n34")


def test_only_visible_text_blocks_cross_the_reader():
    row = {
        "content": {
            "type": "ai",
            "content": [
                {"type": "reasoning", "text": "private reasoning"},
                {"type": "thinking", "text": "private thinking"},
                {"text": "untyped content"},
                {"type": "input_text", "text": "not a rendered text block"},
                {"type": "output_text", "text": "not a rendered output block"},
                {"type": "text", "text": "visible answer"},
            ],
        }
    }

    assert _visible_text(row) == ("assistant", "visible answer")


@pytest.mark.parametrize("path", ["/workspace/chats/source", "/workspace/agents/researcher/chats/source"])
def test_reference_accepts_both_frontend_conversation_routes(path):
    prepare, _, _, _, _ = _setup()

    reader, ids = prepare([f"https://deerflow.example{path}"])

    assert callable(reader)
    assert ids == ("source",)


@pytest.mark.parametrize(
    "url",
    [
        "https://deerflow.example/workspace/agents/researcher/chats/source/extra",
        "https://deerflow.example/workspace/agents/researcher/not-chats/source",
        "https://other.example/workspace/agents/researcher/chats/source",
    ],
)
def test_custom_agent_link_does_not_widen_the_path_or_origin_contract(url):
    prepare, _, _, _, _ = _setup()

    with pytest.raises(HTTPException) as exc:
        prepare([url])

    assert exc.value.status_code == 422


def test_page_text_budget_continues_without_skipping_earlier_messages():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        expected = {}
        for index in range(12):
            text = f"message-{index}:".ljust(4000, "x")
            row = await _put(events, text)
            expected[row["seq"]] = text
        reader, _ = prepare(["source"])
        pages = []
        cursor = None
        for _ in range(4):
            page = json.loads(await reader(thread_id="source", cursor=cursor, limit=50))
            pages.append(page)
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        return pages, expected

    pages, expected = asyncio.run(exercise())

    assert [[message["seq"] for message in page["messages"]] for page in pages] == [[8, 9, 10, 11, 12], [3, 4, 5, 6, 7], [1, 2]]
    assert [page["next_cursor"] for page in pages] == ["8", "3", None]
    for page in pages:
        assert page["status"] == "ok"
        assert sum(len(message["text"]) for message in page["messages"]) <= 20000
        assert page["truncated"] is False
        for message in page["messages"]:
            assert message["text"] == expected[message["seq"]]


def test_single_long_message_is_an_explicitly_truncated_excerpt():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        await _put(events, "x" * 4000 + " omitted suffix")
        reader, _ = prepare(["source"])
        return json.loads(await reader(thread_id="source"))

    page = asyncio.run(exercise())

    assert page["messages"][0]["text"] == "x" * 4000
    assert page["messages"][0]["truncated"] is True
    assert page["truncated"] is True
    # The v1 cursor pages between messages; it does not promise suffix recovery.
    assert page["has_more"] is False
    assert page["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["", "0", "-1", "1.0", " 1", "1 ", "١", "１", "9" * 20, 1, True])
def test_invalid_cursor_is_rejected_before_transcript_queries(cursor):
    async def exercise():
        prepare, events, threads, manager, _ = _setup()
        await threads.create("source", user_id="alice")
        events.list_messages = AsyncMock(side_effect=AssertionError("invalid cursor reached storage"))
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", cursor=cursor))
        events.list_messages.assert_not_awaited()
        manager.list_successful_regenerate_sources.assert_not_awaited()
        return page

    assert asyncio.run(exercise())["status"] == "invalid_request"
