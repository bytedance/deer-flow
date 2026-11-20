from __future__ import annotations

import copy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from deerflow_extension_api import canonical_hash
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.summarization_middleware import (
    DeerFlowSummarizationMiddleware,
    SummaryGenerationError,
    create_summarization_middleware,
)
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig

_BRACE_TEMPLATE = 'Summarize as JSON: {"summary": "..."} {messages}'
_INVALID_TEMPLATES = [
    pytest.param(_BRACE_TEMPLATE, id="literal-braces"),
    pytest.param("{messages} {nope}", id="unknown-name"),
    pytest.param("{}", id="positional-field"),
    pytest.param("{messages:unknown}", id="format-specifier"),
    pytest.param("{messages.foo}", id="attribute-field"),
    pytest.param("{messages[missing]}", id="string-index"),
]


class _StaticChatModel(BaseChatModel):
    text: str = "ok"
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "static-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _middleware(model, summary_prompt: str, **kwargs):
    options = {
        "trigger": ("messages", 4),
        "keep": ("messages", 2),
        "summary_prompt": summary_prompt,
        "token_counter": lambda ms: sum(len(str(m.content)) for m in ms),
        "trim_tokens_to_summarize": 9999,
    }
    options.update(kwargs)
    return DeerFlowSummarizationMiddleware(model=model, **options)


def _state() -> dict:
    return {
        "messages": [
            HumanMessage(content="a" * 50, id="h1"),
            AIMessage(content="b" * 50, id="a1"),
            HumanMessage(content="c" * 50, id="h2"),
            AIMessage(content="d" * 50, id="a2"),
        ],
        "summary_text": "previous summary",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_prompt", _INVALID_TEMPLATES)
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("raise_on_failure", [False, True], ids=["automatic", "manual"])
async def test_invalid_template_preserves_compaction_state(summary_prompt, asynchronous, raise_on_failure):
    model = _StaticChatModel(text="must not replace history")
    events = []
    middleware = _middleware(model, summary_prompt, before_summarization=[events.append])
    state = _state()
    original = copy.deepcopy(state)
    runtime = SimpleNamespace(context={})

    with pytest.raises(SummaryGenerationError) if raise_on_failure else nullcontext():
        if asynchronous:
            result = await middleware.acompact_state(
                state,
                runtime,
                force=raise_on_failure,
                raise_on_failure=raise_on_failure,
            )
        else:
            result = middleware.compact_state(
                state,
                runtime,
                force=raise_on_failure,
                raise_on_failure=raise_on_failure,
            )
        assert result is None

    assert state == original
    assert model.calls == 0
    assert events == []
    assert middleware.summary_call_count == 0


@pytest.mark.parametrize("summary_prompt", _INVALID_TEMPLATES)
def test_unrenderable_template_never_reaches_the_model(summary_prompt):
    model = _StaticChatModel()
    middleware = _middleware(model, summary_prompt)

    assert middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")]) is None
    assert model.calls == 0


def test_doubled_literal_braces_still_render():
    middleware = _middleware(_StaticChatModel(), 'JSON: {{"a": 1}} {messages}')

    prompt = middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")])

    assert prompt is not None
    assert 'JSON: {"a": 1}' in prompt
    assert "hi" in prompt


def test_valid_template_still_compacts():
    model = _StaticChatModel(text="SUMMARY")
    middleware = _middleware(model, "{messages}")

    result = middleware.compact_state(_state(), SimpleNamespace(context={}), force=True)

    assert result is not None
    assert result.summary_text == "SUMMARY"
    assert model.calls == 1


def test_unexpected_formatter_failure_is_not_swallowed():
    class BrokenTemplate(str):
        def format(self, *args, **kwargs):
            raise RuntimeError("unexpected formatter failure")

    middleware = _middleware(_StaticChatModel(), BrokenTemplate("{messages}"))

    with pytest.raises(RuntimeError, match="unexpected formatter failure"):
        middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")])


def test_render_warning_identifies_template_without_logging_content(caplog):
    template = "private configuration {messages.foo}"
    middleware = _middleware(_StaticChatModel(), template)

    assert middleware._build_summary_prompt([HumanMessage(content="private history", id="h1")]) is None

    assert middleware.release_policy_parameters()["summary_prompt_hash"] == canonical_hash(template)
    assert canonical_hash(template) in caplog.text
    assert template not in caplog.text
    assert "private history" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("summary_prompt", ["{messages.foo}", "{messages[missing]}"])
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_configured_agent_keeps_history_and_recovers_after_template_repair(monkeypatch, caplog, summary_prompt, asynchronous):
    summary_model = _StaticChatModel(text="SUMMARY")
    chat_model = _StaticChatModel(text="ordinary reply")
    monkeypatch.setattr(
        "deerflow.agents.middlewares.summarization_middleware.create_chat_model",
        lambda **kwargs: summary_model,
    )
    app_config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {
                    "name": "run-model",
                    "use": "langchain_openai:ChatOpenAI",
                    "model": "test-model",
                }
            ],
            "memory": {"enabled": False},
            "summarization": {
                "enabled": True,
                "summary_prompt": summary_prompt,
                "trigger": {"type": "messages", "value": 4},
                "keep": {"type": "messages", "value": 2},
                "trim_tokens_to_summarize": 9999,
            },
        }
    )
    middleware = create_summarization_middleware(app_config=app_config, run_model_name="run-model", skip_memory_flush=True)
    assert middleware is not None
    graph = create_agent(
        model=chat_model,
        tools=[],
        middleware=[middleware],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "template-render"}}
    original = _state()
    if asynchronous:
        first = await graph.ainvoke(original, config=config)
        second = await graph.ainvoke({"messages": [HumanMessage(content="continue", id="h3")]}, config=config)
        checkpoint = await graph.aget_state(config)
    else:
        first = graph.invoke(original, config=config)
        second = graph.invoke({"messages": [HumanMessage(content="continue", id="h3")]}, config=config)
        checkpoint = graph.get_state(config)

    assert first["messages"][:-1] == original["messages"]
    assert second["messages"][:-2] == first["messages"]
    assert second["messages"][-1].content == "ordinary reply"
    assert checkpoint.values["messages"] == second["messages"]
    assert checkpoint.values["summary_text"] == original["summary_text"]
    assert summary_model.calls == 0
    assert chat_model.calls == 2
    warnings = [r for r in caplog.records if "Summarization template failed to render" in r.getMessage()]
    assert len(warnings) == 2

    middleware.summary_prompt = "{messages}"
    next_turn = {"messages": [HumanMessage(content="continue after repair", id="h4")]}
    repaired = await graph.ainvoke(next_turn, config=config) if asynchronous else graph.invoke(next_turn, config=config)
    assert repaired["summary_text"] == "SUMMARY"
    assert summary_model.calls == 1
    assert chat_model.calls == 3
    assert "h1" not in {message.id for message in repaired["messages"]}
