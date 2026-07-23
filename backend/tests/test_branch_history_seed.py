"""Unit tests for branch-history run-event seeding (#4380 problem 2).

``build_branch_history_seed_events`` must mirror RunJournal's message-event
contract exactly: same event types, ``category="message"``,
``content=message.model_dump()``, the same hidden-message rules, and the same
original-user-text restoration — so the thread feed cannot tell a seeded row
from a journaled one.
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import build_branch_history_seed_events


def _seed(messages):
    return build_branch_history_seed_events(
        messages,
        thread_id="branch-thread",
        run_id="branch-seed-branch-thread",
        parent_thread_id="parent-thread",
    )


def test_seed_serializes_visible_history_in_order() -> None:
    events = _seed(
        [
            HumanMessage(id="h1", content="question"),
            AIMessage(id="a1", content="answer"),
            ToolMessage(id="t1", content="tool output", tool_call_id="call-1"),
        ]
    )

    assert [event["event_type"] for event in events] == ["llm.human.input", "llm.ai.response", "llm.tool.result"]
    assert all(event["category"] == "message" for event in events)
    assert all(event["thread_id"] == "branch-thread" for event in events)
    assert all(event["run_id"] == "branch-seed-branch-thread" for event in events)
    assert [event["content"]["id"] for event in events] == ["h1", "a1", "t1"]
    # Human/AI rows carry the journal's caller tag; every row carries the
    # seed provenance marker.
    assert events[0]["metadata"]["caller"] == "lead_agent"
    assert events[1]["metadata"]["caller"] == "lead_agent"
    assert "caller" not in events[2]["metadata"]
    assert all(event["metadata"]["branch_seed"] is True for event in events)
    assert all(event["metadata"]["branch_parent_thread_id"] == "parent-thread" for event in events)


def test_seed_skips_system_summary_and_nonmessage() -> None:
    """System prompts, summary-named/hidden human turns, and non-messages never
    enter the thread feed — same as RunJournal's message path."""
    events = _seed(
        [
            SystemMessage(id="s1", content="system prompt"),
            HumanMessage(id="h-hidden", content="internal", additional_kwargs={"hide_from_ui": True}),
            HumanMessage(id="h-summary", content="compacted", name="summary"),
            HumanMessage(id="h1", content="question"),
            AIMessage(id="a1", content="answer"),
            "not-a-message",
        ]
    )

    assert [event["content"]["id"] for event in events] == ["h1", "a1"]


def test_seed_persists_hidden_ai_and_tool_rows_like_runjournal() -> None:
    """RunJournal's on_llm_end / _persist_tool_result_message write hide_from_ui
    AI and tool rows unconditionally (the frontend hides them client-side), so
    the seed must too — otherwise seeded rows diverge from journaled ones and a
    hidden turn disappears from a forked feed."""
    events = _seed(
        [
            HumanMessage(id="h1", content="question"),
            AIMessage(id="a-hidden", content="internal", additional_kwargs={"hide_from_ui": True}),
            AIMessage(id="a1", content="answer"),
            ToolMessage(id="t-hidden", content="internal", tool_call_id="call-h", additional_kwargs={"hide_from_ui": True}),
        ]
    )

    assert [event["content"]["id"] for event in events] == ["h1", "a-hidden", "a1", "t-hidden"]
    assert [event["event_type"] for event in events] == [
        "llm.human.input",
        "llm.ai.response",
        "llm.ai.response",
        "llm.tool.result",
    ]
    # The hidden marker is preserved in content so the frontend still hides them.
    assert events[1]["content"]["additional_kwargs"]["hide_from_ui"] is True
    assert events[3]["content"]["additional_kwargs"]["hide_from_ui"] is True


def test_seed_deserializes_dict_shaped_checkpoint_messages() -> None:
    """Checkpoint messages can arrive as model_dump()-shaped dicts (the
    branch-matching helpers in threads.py already handle both); the seed must
    deserialize them instead of silently producing an empty batch."""
    dict_messages = [
        HumanMessage(id="h1", content="question").model_dump(),
        AIMessage(
            id="a1",
            content="answer",
            tool_calls=[{"name": "search", "args": {"q": "x"}, "id": "call-1", "type": "tool_call"}],
        ).model_dump(),
        ToolMessage(id="t1", content="tool output", tool_call_id="call-1").model_dump(),
    ]

    events = _seed(dict_messages)

    assert [event["event_type"] for event in events] == ["llm.human.input", "llm.ai.response", "llm.tool.result"]
    assert [event["content"]["id"] for event in events] == ["h1", "a1", "t1"]
    # Faithful reconstruction: AI tool_calls and the tool's tool_call_id survive.
    assert events[1]["content"]["tool_calls"][0]["id"] == "call-1"
    assert events[2]["content"]["tool_call_id"] == "call-1"


def test_seed_drops_unparseable_dict_message() -> None:
    """A dict with no usable ``type`` can't be reconstructed; it is dropped
    rather than crashing the seed (best-effort — the branch stays usable)."""
    events = _seed([{"content": "orphan", "no_type": True}, HumanMessage(id="h1", content="q")])

    assert [event["content"]["id"] for event in events] == ["h1"]


def test_seed_persists_allowlisted_hidden_human_input_response() -> None:
    """Mirrors RunJournal: answered clarification replies stay recoverable."""
    response = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "req-1",
        "value": "yes",
        "response_kind": "text",
    }
    events = _seed(
        [
            HumanMessage(
                id="h-response",
                content="yes",
                additional_kwargs={"hide_from_ui": True, "human_input_response": response},
            )
        ]
    )

    assert [event["content"]["id"] for event in events] == ["h-response"]
    assert events[0]["event_type"] == "llm.human.input"


def test_seed_restores_original_user_content() -> None:
    """The model-facing wrapper must not leak into the seeded feed."""
    message = HumanMessage(
        id="h1",
        content="<wrapped>question with injected context</wrapped>",
        additional_kwargs={"original_user_content": "question"},
    )

    events = _seed([message])

    assert events[0]["content"]["content"] == "question"
    assert "original_user_content" not in events[0]["content"]["additional_kwargs"]


def test_seed_roundtrips_through_memory_store_feed() -> None:
    """put_batch preserves order and list_messages returns the seeded feed."""
    store = MemoryRunEventStore()
    events = _seed(
        [
            HumanMessage(id="h1", content="question"),
            AIMessage(id="a1", content="answer"),
        ]
    )

    async def roundtrip():
        await store.put_batch(events)
        return await store.list_messages("branch-thread", user_id=None)

    rows = asyncio.run(roundtrip())

    assert [row["content"]["id"] for row in rows] == ["h1", "a1"]
    seqs = [row["seq"] for row in rows]
    assert seqs == sorted(seqs)
    assert all(row["category"] == "message" for row in rows)
