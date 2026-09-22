"""Todo context survives compaction through state, not stale reminder snapshots."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.middlewares.todo_middleware import TODO_REMINDER_MESSAGE_NAME, TodoMiddleware
from deerflow.agents.thread_state import ThreadState


def _reminder(msg_id: str) -> HumanMessage:
    return HumanMessage(
        id=msg_id,
        name=TODO_REMINDER_MESSAGE_NAME,
        content="STALE TODO: [pending] Inspect the Gateway routes",
        additional_kwargs={"hide_from_ui": True},
    )


def _todos() -> list[dict[str, str]]:
    return [
        {"content": "Inspect the Gateway routes", "status": "completed"},
        {"content": "Document the authentication endpoints", "status": "completed"},
    ]


def _messages(*, visible_write_todos: bool = False) -> list:
    name = "write_todos" if visible_write_todos else "read_file"
    args = {"todos": _todos()} if visible_write_todos else {"path": "backend/app/gateway/routers/auth.py"}
    return [
        SystemMessage(content="Document the project accurately.", id="system"),
        HumanMessage(content="Document the Gateway routes.", id="old-user"),
        _reminder("old-todo"),
        AIMessage(content="I inspected the route definitions.", id="old-ai"),
        HumanMessage(content="Include the authentication endpoints.", id="current-user"),
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "recent-call"}], id="recent-ai"),
        ToolMessage(content="Current endpoint documentation is ready.", tool_call_id="recent-call", name=name, id="recent-tool"),
        _reminder("recent-todo"),
    ]


def _middleware(*, trigger: int = 4, text: str = "Gateway route documentation is ready.", hooks=None):
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text=text)
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text=text))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(model=model, trigger=("messages", trigger), keep=("messages", 3), token_counter=len, before_summarization=hooks)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("force", [False, True], ids=["automatic", "manual"])
async def test_compaction_excludes_todo_reminders_from_summary_and_retained_context(asynchronous, force):
    events = []
    middleware = _middleware(trigger=1000 if force else 4, hooks=[events.append])
    messages = _messages()
    memory = HumanMessage(content="User prefers detailed API examples.", id="memory", additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True})
    # An unrelated hidden message must not be removed with the todo reminders.
    messages.insert(1, memory)
    state = {"messages": messages, "todos": _todos()}
    original = deepcopy(state)
    runtime = SimpleNamespace(context={"thread_id": "docs", "run_id": "docs-run"})

    result = await middleware.acompact_state(state, runtime, force=force) if asynchronous else middleware.compact_state(state, runtime, force=force)

    assert result is not None
    assert [m.id for m in result.messages_to_summarize] == ["old-user", "old-ai"]
    assert [m.id for m in result.preserved_messages] == ["system", "memory", "current-user", "recent-ai", "recent-tool"]
    call = middleware.model.ainvoke.call_args if asynchronous else middleware.model.invoke.call_args
    assert "STALE TODO" not in str(call)
    assert "Gateway routes" in str(call)
    assert events[0].messages_to_summarize == result.messages_to_summarize
    assert events[0].preserved_messages == result.preserved_messages
    assert state == original


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("reason", ["below-trigger", "summary-failed", "no-history"])
async def test_unsuccessful_compaction_leaves_todo_reminders_and_state_untouched(asynchronous, reason):
    events = []
    middleware = _middleware(trigger=1000 if reason == "below-trigger" else 4, text=" " if reason == "summary-failed" else "summary", hooks=[events.append])
    messages = _messages()
    if reason == "no-history":
        messages = [SystemMessage(content="Document the project.", id="system"), HumanMessage(content="Document auth.", id="user"), _reminder("todo-1"), _reminder("todo-2")]
    state = {"messages": messages, "todos": _todos(), "summary_text": "previous summary"}
    original = deepcopy(state)
    runtime = SimpleNamespace(context={"thread_id": "docs", "run_id": "docs-run"})

    result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)

    assert result is None
    assert state == original
    assert events == []


class _CapturingModel(BaseChatModel):
    _seen: list[list] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self):
        return "todo-compaction-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="The Gateway documentation is complete."))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("context", ["rebuild", "empty-todos", "visible-write-todos"])
async def test_next_model_gets_current_todos_after_compaction(asynchronous, context):
    model = _CapturingModel()
    summary = _middleware()
    graph = create_agent(model=model, middleware=[summary, TodoMiddleware()], state_schema=ThreadState)
    todos = [] if context == "empty-todos" else _todos()
    state = {"messages": _messages(visible_write_todos=context == "visible-write-todos"), "todos": todos}
    runtime_context = {"thread_id": "docs", "run_id": "docs-run"}

    result = await graph.ainvoke(state, context=runtime_context) if asynchronous else graph.invoke(state, context=runtime_context)

    assert result["todos"] == todos
    assert result["summary_text"] == "Gateway route documentation is ready."
    assert len(model._seen) == 1
    request = model._seen[0]
    assert all("STALE TODO" not in str(m.content) for m in request)
    reminders = [m for m in request if isinstance(m, HumanMessage) and m.name == TODO_REMINDER_MESSAGE_NAME]
    persisted = [m for m in result["messages"] if isinstance(m, HumanMessage) and m.name == TODO_REMINDER_MESSAGE_NAME]
    assert len(reminders) == len(persisted) == (1 if context == "rebuild" else 0)
    if reminders:
        assert "[completed] Inspect the Gateway routes" in reminders[0].content
        assert "[completed] Document the authentication endpoints" in reminders[0].content
        assert reminders[0].additional_kwargs["hide_from_ui"] is True
    assert {"recent-ai", "recent-tool"}.issubset({m.id for m in request})
