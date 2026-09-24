"""Real agent graphs must journal short-circuited results before recovery."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langsmith import tracing_context

from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.secret_context import write_slash_skill_source_path
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory
from deerflow.tools.builtins.clarification_tool import ask_clarification_tool


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _call(name, call_id, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "id": call_id, "args": args}])


def _run(agent, *, asynchronous, context=None):
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=2)
    inputs = {"messages": [HumanMessage(content="Complete the task.")]}
    config = {"callbacks": [journal], "tags": ["lead_agent"], "recursion_limit": 20}

    async def invoke_and_flush():
        try:
            return await agent.ainvoke(inputs, config, context=context)
        finally:
            await journal.close()

    with tracing_context(enabled=False):
        if asynchronous:
            result = asyncio.run(invoke_and_flush())
        else:
            try:
                result = agent.invoke(inputs, config, context=context)
            finally:
                asyncio.run(journal.close())
    return result["messages"], asyncio.run(store.list_messages("t1"))


def _assert_recovery_order(state_messages, events, *, blocked_id, recovery_id, error_text):
    results = [message for message in state_messages if isinstance(message, ToolMessage)]
    blocked = next(message for message in results if message.tool_call_id == blocked_id)
    assert blocked.status == "error"
    assert error_text in blocked.content
    assert state_messages[-1].content == "done"
    tool_events = [event for event in events if event["event_type"] == "llm.tool.result"]
    assert len(tool_events) == len(results)
    blocked_events = [event for event in tool_events if event["content"]["tool_call_id"] == blocked_id]
    assert len(blocked_events) == 1
    assert blocked_events[0]["content"]["content"] == blocked.content
    recovery = next(event for event in events if any(call["id"] == recovery_id for call in event["content"].get("tool_calls", [])))
    final = next(event for event in events if event["content"]["content"] == "done")
    assert blocked_events[0]["seq"] < recovery["seq"] < final["seq"]
    assert events[-1] == final


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_read_before_write_recovery_keeps_error_before_reread(tmp_path, asynchronous):
    path = tmp_path / "report.txt"
    path.write_text("v1", encoding="utf-8")
    writes = []

    @tool
    def read_file(path: str) -> str:
        """Read a test file."""
        return Path(path).read_text(encoding="utf-8")

    @tool
    def str_replace(path: str, old_str: str, new_str: str) -> str:
        """Replace text in a test file."""
        target = Path(path)
        content = target.read_text(encoding="utf-8")
        assert old_str in content
        target.write_text(content.replace(old_str, new_str), encoding="utf-8")
        writes.append(new_str)
        return "updated"

    model = ScriptedModel(
        responses=[
            _call("read_file", "read", path=str(path)),
            _call("str_replace", "write", path=str(path), old_str="v1", new_str="v2"),
            _call("str_replace", "blocked", path=str(path), old_str="v2", new_str="v3"),
            _call("read_file", "reread", path=str(path)),
            _call("str_replace", "retry", path=str(path), old_str="v2", new_str="v3"),
            AIMessage(content="done"),
        ]
    )
    middleware = ReadBeforeWriteMiddleware(content_reader=lambda runtime, path: Path(path).read_text(encoding="utf-8"))
    agent = create_agent(model, tools=[read_file, str_replace], middleware=[middleware])

    messages, events = _run(agent, asynchronous=asynchronous)

    assert path.read_text(encoding="utf-8") == "v3"
    assert writes == ["v2", "v3"]
    _assert_recovery_order(messages, events, blocked_id="blocked", recovery_id="reread", error_text="have not read its current version")


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_skill_policy_recovery_keeps_error_before_allowed_call(tmp_path, monkeypatch, asynchronous):
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("---\nname: test-policy\ndescription: Test policy\nallowed-tools: allowed\n---\nUse the allowed tool.\n", encoding="utf-8")
    skill = parse_skill_file(skill_file, SkillCategory.PUBLIC)
    assert skill is not None
    storage = SimpleNamespace(load_skills=lambda **kwargs: [skill], get_container_root=lambda: "/mnt/skills")
    middleware = SkillToolPolicyMiddleware(slash_source_owner_token="test-owner")
    monkeypatch.setattr(middleware, "_storage", lambda: storage)
    context = {}
    write_slash_skill_source_path(context, skill.get_container_file_path(), owner_token="test-owner")
    calls = []

    @tool
    def forbidden() -> str:
        """Tool denied by the test skill."""
        calls.append("forbidden")
        return "unexpected"

    @tool
    def allowed() -> str:
        """Tool allowed by the test skill."""
        calls.append("allowed")
        return "completed"

    model = ScriptedModel(responses=[_call("forbidden", "blocked"), _call("allowed", "retry"), AIMessage(content="done")])
    agent = create_agent(model, tools=[forbidden, allowed], middleware=[middleware])

    messages, events = _run(agent, asynchronous=asynchronous, context=context)

    assert calls == ["allowed"]
    _assert_recovery_order(messages, events, blocked_id="blocked", recovery_id="retry", error_text="not allowed by the active skill policy")


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_clarification_command_is_persisted_once_at_termination(asynchronous):
    model = ScriptedModel(responses=[_call("ask_clarification", "clarify", question="Which format?", clarification_type="missing_info")])
    agent = create_agent(model, tools=[ask_clarification_tool], middleware=[ClarificationMiddleware()])

    messages, events = _run(agent, asynchronous=asynchronous)

    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert len(results) == 1
    assert [event["event_type"] for event in events] == ["llm.human.input", "llm.ai.response", "llm.tool.result"]
    assert events[-1]["content"]["tool_call_id"] == "clarify"
    assert events[-1]["content"]["artifact"] == results[0].artifact
