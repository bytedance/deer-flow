"""Offline graph checks for original document recall after context compaction."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.task_continuity import archive
from deerflow.agents.task_continuity.tools import history_read, history_search
from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import Paths
from deerflow.config.task_continuity_config import TaskContinuityConfig

BODY = "Project Wisteria uses the exact retention code WX-948."


class SummaryModel(BaseChatModel):
    prompts: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "offline-context-document-probe"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(get_buffer_string(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="The prior document was reviewed; the exact code is omitted."))])


class RecallModel(SummaryModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, ToolMessage) and last.name == "history_search":
            rows = json.loads(last.content)["results"]
            if not rows:
                answer = AIMessage(content="SOURCE_NOT_FOUND")
            else:
                answer = AIMessage(content="", tool_calls=[{"name": "history_read", "args": {"source_id": rows[0]["id"]}, "id": "read-source"}])
        elif isinstance(last, ToolMessage) and last.name == "history_read":
            answer = AIMessage(content=json.loads(last.content).get("text", "SOURCE_NOT_FOUND"))
        else:
            answer = AIMessage(content="", tool_calls=[{"name": "history_search", "args": {"query": "Wisteria", "role": "user"}, "id": "search-source"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


def content(shape):
    if shape == "string":
        return BODY
    if shape == "text-block":
        return [{"type": "text", "text": BODY}]
    source = {
        "document-text": {"type": "text", "media_type": "text/plain", "data": BODY},
        "document-content-string": {"type": "content", "content": BODY},
        "document-content-blocks": {"type": "content", "content": [{"type": "text", "text": BODY}]},
    }[shape]
    return [{"type": "document", "title": "Retention contract", "source": source}]


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "get_paths", lambda: Paths(base_dir=tmp_path))
    return SimpleNamespace(context={"user_id": "alice", "thread_id": "thread-a"}, state={}, tool_call_id="recall")


@pytest.mark.parametrize("shape", ["document-text", "document-content-string", "document-content-blocks"])
@pytest.mark.parametrize("message_type", [HumanMessage, AIMessage, ToolMessage])
def test_documents_retain_order_and_source_identity_in_active_and_archived_tools(scoped, shape, message_type):
    document = content(shape)[0]
    document["context"] = "Keep the original retention code"
    message = message_type(content=["Before", document, {"type": "text", "text": "After"}], id="source", **({"tool_call_id": "tool"} if message_type is ToolMessage else {}))
    original = deepcopy(message.content)
    expected = "Before\nDocument:\ntitle: Retention contract\ncontext: Keep the original retention code\n" + BODY + "\nAfter"
    scoped.state = {"messages": [message]}
    role = {"human": "user", "ai": "assistant", "tool": "tool"}[message.type]
    active = json.loads(history_search.func(scoped, "Wisteria", role=role))["results"]
    assert len(active) == 1
    source_id = active[0]["id"]
    assert json.loads(history_read.func(scoped, source_id))["text"] == expected
    assert not json.loads(history_search.func(scoped, "Wisteria", role="tool" if message.type != "tool" else "user"))["results"]
    scoped.state = {"messages": [], "task_history": archive.capture(scoped.state, scoped, [message], TaskContinuityConfig(enabled=True))}
    archived = json.loads(history_search.func(scoped, "Wisteria", role=role))["results"]
    assert [row["id"] for row in archived] == [source_id]
    assert not json.loads(history_search.func(scoped, "Wisteria", role="tool" if role != "tool" else "user"))["results"]
    assert json.loads(history_read.func(scoped, source_id))["text"] == expected
    assert message.content == original


@pytest.mark.parametrize(
    "source",
    [
        None,
        "malformed",
        {},
        {"type": "text", "data": 123},
        {"type": "text", "data": ""},
        {"type": "url", "url": "https://invalid.example/secret", "data": "secret"},
        {"type": "base64", "data": "secret"},
        {"type": "file", "file_id": "secret"},
        {"type": "content", "content": {"text": "secret"}},
        {"type": "content", "content": [123, {"type": "reasoning", "text": "secret"}, {"type": "document", "title": "secret", "source": {"type": "text", "data": "secret"}}]},
    ],
)
def test_opaque_malformed_and_nested_sources_do_not_enter_history(scoped, source):
    message = HumanMessage(content=[{"type": "document", "title": "secret-title", "context": "secret-context", "text": "secret", "source": source}], id="opaque")
    scoped.state = {"messages": [message]}
    assert not json.loads(history_search.func(scoped, "secret"))["results"]
    history = archive.capture(scoped.state, scoped, [message], TaskContinuityConfig(enabled=True))
    scoped.state = {"messages": [], "task_history": history}
    assert not json.loads(history_search.func(scoped, "secret"))["results"]


def test_document_body_only_admits_immediate_plaintext(scoped):
    parts = ["first", {"type": "text", "text": "second"}, {"type": "text", "text": 123}, {"type": "image", "text": "secret"}, {"type": "document", "source": {"type": "text", "data": "secret"}}]
    message = HumanMessage(content=[{"type": "document", "title": {"text": "secret"}, "context": ["secret"], "source": {"type": "content", "content": parts}}], id="mixed")
    history = archive.capture({}, scoped, [message], TaskContinuityConfig(enabled=True))
    scoped.state = {"messages": [], "task_history": history}
    source_id = json.loads(history_search.func(scoped, "second"))["results"][0]["id"]
    assert json.loads(history_read.func(scoped, source_id))["text"] == "Document:\nfirst\nsecond"
    assert not json.loads(history_search.func(scoped, "secret"))["results"]


@pytest.mark.parametrize("metadata", [{"hide_from_ui": True}, {"deerflow_content_kind": "internal"}])
def test_framework_document_sources_remain_excluded(scoped, metadata):
    message = HumanMessage(content=content("document-text"), additional_kwargs=metadata, id="internal")
    history = archive.capture({}, scoped, [message], TaskContinuityConfig(enabled=True))
    scoped.state = {"messages": [message], "task_history": history}
    assert not json.loads(history_search.func(scoped, "Wisteria"))["results"]


def test_document_extension_preserves_old_citations_and_text_only_ids(scoped):
    legacy = HumanMessage(content="Existing visible reference", id="same-message")
    # Freeze the old text-only source ID rather than recomputing it through the
    # candidate's digest implementation, so a hashing change cannot pass unnoticed.
    old_id = "r999441079d2ff7aa479535226450faaf"
    assert archive.records([legacy])[0]["id"] == old_id
    history = archive.capture({}, scoped, [legacy], TaskContinuityConfig(enabled=True))
    expanded = legacy.model_copy(update={"content": [legacy.content, *content("document-text")]})
    scoped.state = {"messages": [expanded], "task_history": history}
    assert json.loads(history_read.func(scoped, old_id))["text"] == legacy.content
    new_id = json.loads(history_search.func(scoped, "Wisteria"))["results"][0]["id"]
    assert new_id != old_id
    assert BODY in json.loads(history_read.func(scoped, new_id))["text"]


def test_document_sources_follow_checkpoint_reachability_and_user_scope(scoped):
    config = TaskContinuityConfig(enabled=True)
    old_history = archive.capture({}, scoped, [HumanMessage(content="Earlier plain message", id="old")], config)
    new_history = archive.capture({"task_history": old_history}, scoped, [HumanMessage(content=content("document-text"), id="new")], config)
    scoped.state = {"messages": [], "task_history": old_history}
    assert not json.loads(history_search.func(scoped, "Wisteria"))["results"]
    scoped.state["task_history"] = new_history
    source_id = json.loads(history_search.func(scoped, "Wisteria"))["results"][0]["id"]
    for context in ({"user_id": "bob", "thread_id": "thread-a"}, {"user_id": "alice", "thread_id": "thread-b"}):
        foreign = SimpleNamespace(context=context, state=scoped.state, tool_call_id="foreign")
        assert not json.loads(history_search.func(foreign, "Wisteria"))["results"]
        assert json.loads(history_read.func(foreign, source_id)) == {"error": "source_unavailable", "status": "scope_unavailable"}


def test_document_caps_and_read_offsets_share_the_visible_source(scoped):
    body = "Wisteria " + "ü中" * 3500 + " OMITTEDTAIL"
    message = HumanMessage(content=[{"type": "document", "source": {"type": "text", "data": body}}], id="long")
    history = archive.capture({}, scoped, [message], TaskContinuityConfig(enabled=True, max_record_chars=5000))
    scoped.state = {"messages": [], "task_history": history}
    hit = json.loads(history_search.func(scoped, "Wisteria"))["results"][0]
    first = json.loads(history_read.func(scoped, hit["id"]))
    second = json.loads(history_read.func(scoped, hit["id"], first["next_offset"]))
    readable = first["text"] + second["text"]
    assert readable == ("Document:\n" + body)[:5000]
    assert first["truncated"] and second["truncated"]
    assert readable[hit["excerpt_start"] : hit["excerpt_end"]] == hit["excerpt"]
    assert second["next_offset"] is None
    assert not json.loads(history_search.func(scoped, "OMITTEDTAIL"))["results"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("shape", ["string", "text-block", "document-text", "document-content-string", "document-content-blocks"])
async def test_plaintext_document_can_be_recalled_after_compaction(tmp_path, monkeypatch, shape, async_mode):
    monkeypatch.setattr(archive, "get_paths", lambda: Paths(base_dir=tmp_path))
    context = {"user_id": "synthetic-user", "thread_id": "synthetic-thread"}
    config = {"configurable": {"thread_id": "synthetic-thread"}}
    saver = InMemorySaver()
    summarizer = SummaryModel()
    middleware = DeerFlowSummarizationMiddleware(model=summarizer, trigger=("messages", 4), keep=("messages", 2), task_continuity_config=TaskContinuityConfig(enabled=True))
    initial_graph = create_agent(SummaryModel(), tools=[], middleware=[DurableContextMiddleware(task_continuity_enabled=True), middleware], state_schema=ThreadState, checkpointer=saver)
    initial = {"messages": [HumanMessage(content=content(shape), id="document-message"), AIMessage(content="Reviewed", id="ack"), HumanMessage(content="Continue", id="current"), AIMessage(content="Working", id="working")]}
    first = await initial_graph.ainvoke(initial, config=config, context=context) if async_mode else initial_graph.invoke(initial, config=config, context=context)
    assert first["task_history"]["status"] == "available"
    assert any(BODY in prompt for prompt in summarizer.prompts), "the real summarizer received the document body"
    assert all("WX-948" not in str(message.content) for message in first["messages"])
    assert "WX-948" not in first["summary_text"]

    # A fresh graph reads the same in-memory checkpoint and calls production
    # history tools. Only model replies are scripted; archive SQLite IO is real.
    resumed_graph = create_agent(RecallModel(), tools=[history_search, history_read], middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState, checkpointer=saver)
    request = {"messages": [HumanMessage(content="Recover the exact retention code from the earlier document", id="recall")]}
    final = await resumed_graph.ainvoke(request, config=config, context=context) if async_mode else resumed_graph.invoke(request, config=config, context=context)
    assert "WX-948" in final["messages"][-1].content
