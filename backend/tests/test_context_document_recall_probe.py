"""Offline feature-gap probe, not a claim that native documents are supported.

Current documentation excludes non-text typed blocks from task-history sources.
The native-document cases ask whether that boundary should gain plaintext-only
support. They are expected to fail on the unmodified implementation.
"""

import json

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
