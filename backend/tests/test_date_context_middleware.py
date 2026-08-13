"""Tests for the minimal built-in-subagent current-date middleware."""

import asyncio
from types import SimpleNamespace
from unittest import mock

from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.agents.middlewares.date_context_middleware import SubagentDateContextMiddleware
from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    _REMINDER_DATE_KEY,
)


def _fake_runtime():
    return SimpleNamespace(context={})


def _make_request(system_message, messages):
    request = mock.MagicMock()
    request.system_message = system_message
    request.messages = list(messages)

    def override(**updates):
        new = mock.MagicMock()
        new.system_message = updates.get("system_message", request.system_message)
        new.messages = updates.get("messages", request.messages)
        new.override = override
        return new

    request.override = override
    return request


def test_injects_hidden_date_reminder_before_agent():
    mw = SubagentDateContextMiddleware()
    state = {
        "messages": [
            SystemMessage(content="subagent instructions", id="system"),
            HumanMessage(content="research today's news", id="human"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.date_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-08-13, Thursday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 1
    reminder = messages[0]
    assert isinstance(reminder, SystemMessage)
    assert "<current_date>2026-08-13, Thursday</current_date>" in reminder.content
    assert reminder.additional_kwargs.get("hide_from_ui") is True
    assert reminder.additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert reminder.additional_kwargs.get(_REMINDER_DATE_KEY) == "2026-08-13, Thursday"


def test_does_not_rewrite_task_message():
    mw = SubagentDateContextMiddleware()
    state = {"messages": [HumanMessage(content="research", id="human")]}

    result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    # Only the reminder is returned; the task message keeps its original id and
    # is not replaced by an ID-swapped triplet.
    assert len(result["messages"]) == 1
    assert state["messages"][0].id == "human"


def test_skips_when_dynamic_context_reminder_already_present():
    mw = SubagentDateContextMiddleware()
    state = {
        "messages": [
            SystemMessage(content="subagent instructions", id="system"),
            SystemMessage(
                content="<system-reminder>\n<current_date>2026-08-13, Thursday</current_date>\n</system-reminder>",
                additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
            ),
            HumanMessage(content="research", id="human"),
        ]
    }

    assert mw.before_agent(state, _fake_runtime()) is None


def test_skips_without_a_human_message():
    mw = SubagentDateContextMiddleware()
    state = {"messages": [SystemMessage(content="subagent instructions", id="system")]}

    assert mw.before_agent(state, _fake_runtime()) is None


def test_async_before_agent_matches_sync():
    mw = SubagentDateContextMiddleware()
    state = {"messages": [HumanMessage(content="research", id="human")]}

    sync_result = mw.before_agent(state, _fake_runtime())
    async_result = asyncio.run(mw.abefore_agent(state, _fake_runtime()))

    assert async_result == sync_result


def test_reminder_coalesces_with_leading_system_message():
    from deerflow.agents.middlewares.system_message_coalescing_middleware import _coalesce_request

    mw = SubagentDateContextMiddleware()
    state = {
        "messages": [
            SystemMessage(content="subagent instructions", id="system"),
            HumanMessage(content="research", id="human"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.date_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-08-13, Thursday"
        result = mw.before_agent(state, _fake_runtime())

    request = _make_request(system_message=None, messages=[*state["messages"], *result["messages"]])
    coalesced = _coalesce_request(request)

    assert coalesced is not None
    assert "subagent instructions" in coalesced.system_message.content
    assert "<current_date>2026-08-13, Thursday</current_date>" in coalesced.system_message.content
    assert not any(isinstance(message, SystemMessage) for message in coalesced.messages)
