"""Tests for the worker's partial-AI-chunk accumulation (cancelled-mid-stream persistence, #3403).

``_accumulate_partial_ai_chunk`` collects streamed ``messages``-mode AI chunks so a
user interrupt can persist the partial answer that was already shown in the UI.
"""

from langchain_core.messages import AIMessageChunk, ToolMessageChunk

from deerflow.runtime.runs.worker import _accumulate_partial_ai_chunk


def test_accumulates_chunks_by_id():
    accum: dict = {}
    # messages mode yields (message_chunk, metadata) tuples.
    _accumulate_partial_ai_chunk("messages", (AIMessageChunk(content="Hel", id="m1"), {}), accum)
    _accumulate_partial_ai_chunk("messages", (AIMessageChunk(content="lo", id="m1"), {}), accum)

    assert set(accum) == {"m1"}
    assert accum["m1"].content == "Hello"


def test_separate_ids_are_kept_apart():
    accum: dict = {}
    _accumulate_partial_ai_chunk("messages", (AIMessageChunk(content="a", id="m1"), {}), accum)
    _accumulate_partial_ai_chunk("messages", (AIMessageChunk(content="b", id="m2"), {}), accum)

    assert accum["m1"].content == "a"
    assert accum["m2"].content == "b"


def test_ignores_non_messages_mode():
    accum: dict = {}
    _accumulate_partial_ai_chunk("values", {"messages": [AIMessageChunk(content="x", id="m1")]}, accum)
    assert accum == {}


def test_ignores_non_ai_chunk():
    accum: dict = {}
    _accumulate_partial_ai_chunk("messages", (ToolMessageChunk(content="r", tool_call_id="c1", id="t1"), {}), accum)
    assert accum == {}


def test_ignores_chunk_without_id():
    accum: dict = {}
    _accumulate_partial_ai_chunk("messages", (AIMessageChunk(content="x", id=None), {}), accum)
    assert accum == {}


def test_handles_bare_chunk_without_metadata_tuple():
    accum: dict = {}
    _accumulate_partial_ai_chunk("messages", AIMessageChunk(content="x", id="m1"), accum)
    assert accum["m1"].content == "x"
