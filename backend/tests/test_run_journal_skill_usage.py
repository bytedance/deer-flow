"""Skill snapshots survive callback ordering, pagination, and checkpoint removal."""

import hashlib
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


def snapshot(name="report", *, content="# Original instructions", activation="automatic"):
    return {
        "name": name,
        "description": "Create reports",
        "category": "custom",
        "path": f"/mnt/skills/custom/{name}/SKILL.md",
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "activation": activation,
        "partial": False,
    }


def respond(journal, message, *, run_id=None, tags=None):
    journal.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id or uuid4(), tags=tags)


@pytest.mark.anyio
async def test_terminal_history_contains_loads_recorded_after_tool_callback_and_before_slash_response():
    store = MemoryRunEventStore()
    journal = RunJournal("run", "thread", store)
    slash = snapshot("slash", activation="slash")
    journal.record_skill_usage(slash)
    respond(journal, AIMessage(content="", tool_calls=[{"id": "read", "name": "read_file", "args": {}}]))
    # Tool callbacks happen inside the handler, before the wrapper knows the
    # read succeeded. The raw tool event therefore cannot contain this metadata.
    journal.on_tool_end(ToolMessage(content="# Original instructions", tool_call_id="read"), run_id=uuid4())
    automatic = snapshot()
    journal.record_skill_usage(automatic)
    # Repeat loads retain the first snapshot and its original position.
    journal.record_skill_usage(snapshot(content="# Edited later"))
    automatic["content"] = "mutated by producer"
    terminal = AIMessage(id="final", content="Done")
    respond(journal, terminal)
    await journal.close()

    # This uses only the durable feed, without any retained checkpoint, and
    # requests a page too small to include the original load events.
    page = await store.list_messages("thread", limit=1)
    assert len(page) == 1
    assert page[0]["content"]["id"] == "final"
    assert page[0]["content"]["additional_kwargs"]["skill_usages"] == [slash, snapshot()]
    assert "skill_usages" not in terminal.additional_kwargs
    all_rows = await store.list_messages("thread")
    assert "skill_usages" not in all_rows[0]["content"]["additional_kwargs"]
    assert "skill_usage" not in all_rows[1]["content"]["additional_kwargs"]


@pytest.mark.anyio
async def test_only_canonical_lead_terminal_responses_receive_display_snapshots():
    store = MemoryRunEventStore()
    journal = RunJournal("run", "thread", store)
    journal.record_skill_usage(snapshot())
    respond(journal, AIMessage(id="subagent", content="Child answer"), tags=["subagent:research"])
    respond(journal, AIMessage(id="summary", content="Summary"), tags=["middleware:summarization"])
    respond(journal, AIMessage(id="tool-call", content="Reading", tool_calls=[{"id": "read", "name": "read_file", "args": {}}]))
    callback_id = uuid4()
    respond(journal, AIMessage(id="final", content="Done"), run_id=callback_id)
    journal.record_skill_usage(snapshot("later"))
    respond(journal, AIMessage(id="replay", content="Replay", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}), run_id=callback_id)
    respond(journal, AIMessage(id="next", content="Next answer"))
    await journal.close()

    rows = await store.list_events("thread", "run", event_types=["llm.ai.response"])
    by_id = {row["content"]["id"]: row["content"]["additional_kwargs"] for row in rows}
    assert by_id["subagent"] == {}
    assert by_id["summary"] == {}
    assert by_id["tool-call"] == {}
    assert by_id["final"]["skill_usages"] == [snapshot()]
    assert by_id["next"]["skill_usages"] == [snapshot(), snapshot("later")]
    assert "replay" not in by_id


@pytest.mark.anyio
async def test_skill_aggregation_is_bounded_and_close_drops_snapshots():
    store = MemoryRunEventStore()
    journal = RunJournal("run", "thread", store)
    for index in range(70):
        journal.record_skill_usage(snapshot(str(index), content="x" * 100_001))
    respond(journal, AIMessage(content="Done"))
    await journal.close()
    rows = await store.list_messages("thread", limit=1)
    usages = rows[0]["content"]["additional_kwargs"]["skill_usages"]
    assert len(usages) == 64
    assert all(len(usage["content"]) == 100_000 and usage["partial"] for usage in usages)
    assert journal._skill_usages == {}
    journal.record_skill_usage(snapshot("after-close"))
    assert journal._skill_usages == {}


@pytest.mark.anyio
async def test_empty_journal_keeps_history_unchanged():
    store = MemoryRunEventStore()
    journal = RunJournal("run", "thread", store)
    respond(journal, AIMessage(content="No skills"))
    await journal.close()
    rows = await store.list_messages("thread")
    assert "skill_usages" not in rows[0]["content"]["additional_kwargs"]
