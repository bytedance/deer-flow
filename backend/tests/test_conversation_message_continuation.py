"""Reading past the per-message limit through a continuation (follow-up to #5421)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage
from test_conversation_access import _put, _setup

from deerflow.agents.middlewares.tool_output_budget_middleware import _tool_message_over_budget
from deerflow.config.tool_output_config import ToolOutputConfig


def _inline(raw: str, config: ToolOutputConfig) -> bool:
    return not _tool_message_over_budget(ToolMessage(content=raw, name="read_conversation", tool_call_id="call-1"), config)


async def _follow(reader, item, *, max_calls=50):
    """Follow continuations from a page item; return (full text, raw responses)."""
    text, raws, continuation = item["text"], [], item.get("continuation")
    for _ in range(max_calls):
        if continuation is None:
            return text, raws
        raw = await reader(thread_id="source", **continuation)
        raws.append(raw)
        [part] = json.loads(raw)["messages"]
        assert part["offset"] == continuation["offset"]
        text += part["text"]
        continuation = part.get("continuation")
    raise AssertionError("continuation did not finish")


@pytest.mark.parametrize(
    "tool_output,unit",
    [(None, "0123456789"), (None, '需求："quoted" <tag>\n'), ({"tool_overrides": {"read_conversation": 5_000}}, '需求："quoted" <tag>\n')],
    ids=["ascii", "escaped-cjk", "small-budget"],
)
def test_cut_message_is_read_to_the_end_through_continuations(tool_output, unit):
    original = (unit * 3000)[:30_000] + "END"

    async def exercise():
        prepare, events, threads, _, _ = _setup(tool_output=tool_output)
        await threads.create("source", user_id="alice")
        row = await _put(events, original)
        reader, _ = prepare(["source"])
        raw = await reader(thread_id="source")
        [item] = json.loads(raw)["messages"]
        assert item["truncated"] is True
        assert item["continuation"] == {"message_seq": row["seq"], "offset": len(item["text"])}
        text, raws = await _follow(reader, item)
        return raw, text, raws

    raw, text, raws = asyncio.run(exercise())

    config = ToolOutputConfig.model_validate(tool_output or {})
    assert text == original
    assert raws and all(_inline(response, config) for response in [raw, *raws])
    last = json.loads(raws[-1])
    assert last["truncated"] is False and "continuation" not in last["messages"][0]
    assert last["messages"][0]["text_length"] == len(original)


def test_complete_messages_carry_no_continuation():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        await _put(events, "short answer")
        reader, _ = prepare(["source"])
        return json.loads(await reader(thread_id="source"))

    [item] = asyncio.run(exercise())["messages"]
    assert item["truncated"] is False and "continuation" not in item


def test_continuation_reads_only_visible_messages_of_listed_owned_threads():
    async def exercise():
        prepare, events, threads, manager, _ = _setup()
        await threads.create("source", user_id="alice")
        await threads.create("unlisted", user_id="alice")
        visible = await _put(events, "x" * 5000)
        hidden = await _put(events, "y" * 5000, hidden=True)
        child = await _put(events, "z" * 5000, caller="subagent:researcher")
        replaced = await _put(events, "r" * 5000, run_id="replaced")
        other = await _put(events, "w" * 5000, thread="unlisted")
        manager.list_successful_regenerate_sources.return_value = {"replaced"}
        reader, _ = prepare(["source"])

        async def read(thread, seq):
            return json.loads(await reader(thread_id=thread, message_seq=seq, offset=4000))

        return {
            "visible": await read("source", visible["seq"]),
            "hidden": await read("source", hidden["seq"]),
            "subagent": await read("source", child["seq"]),
            "superseded": await read("source", replaced["seq"]),
            "missing": await read("source", 999),
            "unlisted": await read("unlisted", other["seq"]),
        }

    results = asyncio.run(exercise())

    assert results["visible"]["status"] == "ok"
    assert results["visible"]["messages"][0]["text"] == "x" * 1000
    for key in ("hidden", "subagent", "superseded", "missing", "unlisted"):
        assert results[key]["status"] == "unavailable", key


def test_continuation_rechecks_current_ownership():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        row = await _put(events, "x" * 5000)
        reader, _ = prepare(["source"])
        first = json.loads(await reader(thread_id="source", message_seq=row["seq"], offset=4000))
        await threads.delete("source", user_id="alice")
        after = json.loads(await reader(thread_id="source", message_seq=row["seq"], offset=4000))
        return first, after

    first, after = asyncio.run(exercise())
    assert first["status"] == "ok" and after["status"] == "unavailable"


@pytest.mark.parametrize(
    "arguments",
    [
        {"message_seq": 0, "offset": 0},
        {"message_seq": -1, "offset": 0},
        {"message_seq": True, "offset": 0},
        {"message_seq": "1", "offset": 0},
        {"message_seq": 1, "offset": -1},
        {"message_seq": 1, "offset": True},
        {"message_seq": 1, "offset": "4000"},
        {"message_seq": 1},
        {"offset": 4000},
        {"message_seq": 1, "offset": 0, "cursor": "5"},
    ],
)
def test_invalid_continuation_arguments_are_rejected_before_transcript_queries(arguments):
    async def exercise():
        prepare, events, threads, manager, _ = _setup()
        await threads.create("source", user_id="alice")
        events.list_messages = AsyncMock(side_effect=AssertionError("invalid continuation reached storage"))
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", **arguments))
        events.list_messages.assert_not_awaited()
        manager.list_successful_regenerate_sources.assert_not_awaited()
        return page

    assert asyncio.run(exercise())["status"] == "invalid_request"


def test_offsets_follow_the_current_text_of_a_live_source():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        row = await _put(events, "a" * 6000)
        reader, _ = prepare(["source"])

        async def read(offset):
            return json.loads(await reader(thread_id="source", message_seq=row["seq"], offset=offset))

        at_end, beyond = await read(6000), await read(6001)
        row["content"]["content"] = "b" * 5000  # the source is edited between reads
        return at_end, beyond, await read(4000), await read(5500)

    at_end, beyond, edited, shrunk = asyncio.run(exercise())

    [end_part] = at_end["messages"]
    assert at_end["status"] == "ok" and end_part["text"] == "" and end_part["truncated"] is False and "continuation" not in end_part
    assert beyond["status"] == "invalid_request" and "may have changed" in beyond["notice"]
    assert edited["messages"][0]["text"] == "b" * 1000 and edited["messages"][0]["text_length"] == 5000
    assert shrunk["status"] == "invalid_request"


def test_continuation_reads_one_row_instead_of_scanning_history():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        for index in range(300):
            await _put(events, f"older {index}")
        target = await _put(events, "x" * 5000)
        for index in range(300):
            await _put(events, f"newer {index}")
        calls = []
        original = events.list_messages

        async def spy(*args, **kwargs):
            calls.append(kwargs)
            return await original(*args, **kwargs)

        events.list_messages = spy
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", message_seq=target["seq"], offset=4000))
        return page, calls, target["seq"]

    page, calls, seq = asyncio.run(exercise())

    assert page["messages"][0]["text"] == "x" * 1000
    assert len(calls) == 1 and calls[0]["after_seq"] == seq - 1 and calls[0]["limit"] <= 2
