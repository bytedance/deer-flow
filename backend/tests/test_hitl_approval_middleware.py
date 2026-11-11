"""Unit tests for HitlApprovalMiddleware (after_model pattern)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from deerflow.agents.middlewares.hitl_approval_middleware import (
    MAX_PAYLOAD_BYTES,
    MAX_REASON_CHARS,
    HitlApprovalMiddleware,
    summarize_args,
)
from deerflow.config.hitl_approval_config import HitlApprovalConfig


@tool
def write_file(path: str, content: str) -> str:
    """Write a file."""
    return "OK"


class _StateAwareToolModel(FakeMessagesListChatModel):
    calls: list[dict[str, Any]]

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if any(isinstance(message, ToolMessage) for message in messages):
            message = AIMessage(content="final answer")
        else:
            message = AIMessage(content="", tool_calls=self.calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_agent(middleware, *, tool_calls=None, tool_args=None, checkpointer=None):
    if tool_calls is not None:
        model = _StateAwareToolModel(responses=[], calls=tool_calls)
    else:
        model = build_single_tool_call_model(
            tool_name="write_file",
            tool_args=tool_args or {"path": "/tmp/a.txt", "content": "hello"},
            tool_call_id="call_0",
        )
    return create_agent(model, tools=[write_file], middleware=[middleware], checkpointer=checkpointer or InMemorySaver())


def messages_of(out):
    return out["messages"]


def run_pause(middleware, *, metadata=None, context=None, thread="t", tool_calls=None, tool_args=None, checkpointer=None):
    agent = build_agent(middleware, tool_calls=tool_calls, tool_args=tool_args, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread}}
    if metadata is not None:
        config["metadata"] = metadata
    out = agent.invoke({"messages": [{"role": "user", "content": "write"}]}, config, context=context)
    return agent, config, out


def approval_response(out, option_id, tool_call_id="call_0", **extra):
    payload = out["__interrupt__"][0].value
    action = next(action for action in payload["actions"] if action["tool_call_id"] == tool_call_id)
    return {"option_id": option_id, "tool_call_id": tool_call_id, "request_id": action["request_id"], **extra}


def test_outside_tool_list_passes_through():
    middleware = HitlApprovalMiddleware(tool_names={"bash"})
    _, _, out = run_pause(middleware)
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_approve_executes_tool():
    agent, config, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    interrupts = out["__interrupt__"]
    payload = interrupts[0].value
    assert payload["kind"] == "hitl_approval"
    assert payload["pending_tool_call_ids"] == ["call_0"]
    out = agent.invoke(Command(resume={"responses": [approval_response(out, "approve")]}), config)
    assert any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_stale_request_id_denies_all_and_never_executes():
    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_0"},
        {"name": "write_file", "args": {"path": "/tmp/b.txt", "content": "b"}, "id": "call_1"},
    ]
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)
    stale = approval_response(paused, "approve", tool_call_id="call_1")
    stale["request_id"] = "hitl_approval:stale-message:call_1"

    out = agent.invoke(Command(resume={"responses": [approval_response(paused, "approve"), stale]}), config)

    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 2
    assert {message.tool_call_id for message in tool_messages} == {"call_0", "call_1"}
    assert all(message.status == "error" for message in tool_messages)
    assert not any(message.content == "OK" for message in tool_messages)


def test_reject_produces_named_error_tool_message_and_no_execution():
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(
        Command(resume={"responses": [approval_response(paused, "reject", value="too risky")]}),
        config,
    )
    tool_messages = [m for m in messages_of(out) if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    message = tool_messages[0]
    assert message.name == "write_file"
    assert message.status == "error"
    assert "too risky" in message.content
    assert "The tool was not executed" in message.content
    assert not any(m.content == "OK" for m in tool_messages)


def test_approve_after_tool_removal_denies_resumed_call():
    middleware = HitlApprovalMiddleware(tool_names={"write_file"})
    agent, config, paused = run_pause(middleware)
    middleware.tool_names.clear()

    out = agent.invoke(
        Command(resume={"responses": [approval_response(paused, "approve")]}),
        config,
        context={"_hitl_resume_tool_names": {"write_file"}},
    )

    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "approval configuration changed" in tool_messages[0].content
    assert not any(message.content == "OK" for message in tool_messages)


@pytest.mark.asyncio
async def test_removed_tool_approval_recovers_gate_after_head_moving_write():
    from deerflow.runtime.runs.worker import _pending_hitl_resume_tool_names

    middleware = HitlApprovalMiddleware(tool_names={"write_file"})
    agent, config, paused = run_pause(middleware)
    agent.update_state(config, {"messages": [AIMessage(content="head move", id="head-move")]}, as_node="model")
    command = Command(resume={"responses": [approval_response(paused, "approve")]})

    names = await _pending_hitl_resume_tool_names(agent.checkpointer, config, command)

    middleware.tool_names.clear()
    assert names == {"write_file"}


@pytest.mark.asyncio
async def test_disabled_reject_escape_recovers_gate_after_head_moving_write():
    from deerflow.runtime.runs.worker import _is_all_reject_hitl_resume, _pending_hitl_resume_tool_names

    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    agent.update_state(config, {"messages": [AIMessage(content="head move", id="head-move")]}, as_node="model")
    command = Command(resume={"responses": [approval_response(paused, "reject")]})

    names = await _pending_hitl_resume_tool_names(agent.checkpointer, config, command)

    assert _is_all_reject_hitl_resume(command)
    assert names == {"write_file"}


@pytest.mark.asyncio
async def test_pending_resume_names_fall_back_to_sync_saver_history():
    from deerflow.runtime.runs.worker import _pending_hitl_resume_tool_names

    class SyncOnlySaver(InMemorySaver):
        async def alist(self, *args, **kwargs):
            raise NotImplementedError
            yield  # pragma: no cover

        async def aget_tuple(self, *args, **kwargs):
            raise NotImplementedError

    saver = SyncOnlySaver()
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), checkpointer=saver)
    agent.update_state(config, {"messages": [AIMessage(content="head move", id="head-move")]}, as_node="model")
    command = Command(resume={"responses": [approval_response(paused, "approve")]})

    assert await _pending_hitl_resume_tool_names(saver, config, command) == {"write_file"}


@pytest.mark.asyncio
async def test_pending_resume_names_tuple_only_saver_handles_empty_and_paused_heads():
    from deerflow.runtime.runs.worker import _pending_hitl_resume_tool_names

    class TupleOnlySaver(InMemorySaver):
        async def alist(self, *args, **kwargs):
            raise NotImplementedError
            yield  # pragma: no cover

        def list(self, *args, **kwargs):
            raise NotImplementedError

        async def aget_tuple(self, *args, **kwargs):
            raise NotImplementedError

    saver = TupleOnlySaver()
    command = Command(resume={"responses": [{"option_id": "approve", "tool_call_id": "call_0"}]})
    config = {"configurable": {"thread_id": "t"}}

    assert await _pending_hitl_resume_tool_names(saver, config, command) == set()

    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), checkpointer=saver)
    command = Command(resume={"responses": [approval_response(paused, "approve")]})

    assert await _pending_hitl_resume_tool_names(saver, config, command) == {"write_file"}


@pytest.mark.asyncio
async def test_pending_resume_names_newer_resume_wins_over_old_interrupt():
    from deerflow.runtime.runs.worker import _pending_hitl_resume_tool_names

    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    command = Command(resume={"responses": [approval_response(paused, "reject")]})
    agent.invoke(command, config)

    assert await _pending_hitl_resume_tool_names(agent.checkpointer, config, command) == set()


def test_request_id_stable_across_replay_and_contains_message_id():
    agent, config, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    first = out["__interrupt__"][0].value["request_id"]
    agent.invoke(Command(resume={"responses": [approval_response(out, "approve")]}), config)
    # The payload is rebuilt identically on replay; id contains the AI message id.
    ai_id = next(m.id for m in messages_of(out) if isinstance(m, AIMessage))
    assert first == f"hitl_approval:{ai_id}:call_0"


def test_non_interactive_denies_without_interrupt():
    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), context={"non_interactive": True})
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))
    assert not any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_im_origin_allow_executes_without_pause():
    _, _, out = run_pause(
        HitlApprovalMiddleware(tool_names={"write_file"}, non_interactive="allow"),
        metadata={"deerflow_origin": {"kind": "im_channel"}},
    )
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_im_origin_deny_rejects_without_pause():
    _, _, out = run_pause(
        HitlApprovalMiddleware(tool_names={"write_file"}),
        metadata={"deerflow_origin": {"kind": "im_channel"}},
    )
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))


def test_subagent_fails_closed_even_with_allow():
    _, _, out = run_pause(
        HitlApprovalMiddleware(tool_names={"write_file"}, non_interactive="allow"),
        context={"is_subagent": True},
    )
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))


def test_supports_resume_false_fails_closed():
    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}, supports_resume=False))
    assert "__interrupt__" not in out
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))


def test_response_count_mismatch_denies_all_and_can_resume_again():
    agent, config, _ = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(Command(resume={"responses": []}), config)
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))
    assert not any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_unknown_tool_call_id_denies_all():
    agent, config, _ = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(Command(resume={"responses": [{"option_id": "approve", "tool_call_id": "nope", "request_id": "hitl_approval:unknown:nope"}]}), config)
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))
    assert not any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_unknown_option_rejects_item():
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(Command(resume={"responses": [approval_response(paused, "edit")]}), config)
    assert any(isinstance(m, ToolMessage) and m.status == "error" for m in messages_of(out))
    assert not any(isinstance(m, ToolMessage) and m.content == "OK" for m in messages_of(out))


def test_duplicate_resume_ids_deny_all_targets():
    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_0"},
        {"name": "write_file", "args": {"path": "/tmp/b.txt", "content": "b"}, "id": "call_1"},
    ]
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)
    out = agent.invoke(
        Command(
            resume={
                "responses": [
                    approval_response(paused, "approve"),
                    approval_response(paused, "reject"),
                ]
            }
        ),
        config,
    )
    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 2
    assert {message.tool_call_id for message in tool_messages} == {"call_0", "call_1"}
    assert all(message.status == "error" for message in tool_messages)
    assert not any(message.content == "OK" for message in tool_messages)


def test_mixed_approve_and_reject_requires_and_covers_each_target_once():
    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_0"},
        {"name": "write_file", "args": {"path": "/tmp/b.txt", "content": "b"}, "id": "call_1"},
    ]
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)
    out = agent.invoke(
        Command(
            resume={
                "responses": [
                    approval_response(paused, "approve"),
                    approval_response(paused, "reject", tool_call_id="call_1", value="not this one"),
                ]
            }
        ),
        config,
    )
    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 2
    by_id = {message.tool_call_id: message for message in tool_messages}
    assert by_id["call_0"].content == "OK"
    assert by_id["call_1"].status == "error"
    assert "not this one" in by_id["call_1"].content


def test_non_string_rejection_reason_is_rendered_as_bounded_text():
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(
        Command(resume={"responses": [approval_response(paused, "reject", value={"why": "unsafe"})]}),
        config,
    )
    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "unsafe" in tool_messages[0].content


def test_rejection_reason_is_truncated():
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(
        Command(resume={"responses": [approval_response(paused, "reject", value="r" * (MAX_REASON_CHARS + 100))]}),
        config,
    )
    message = next(message for message in messages_of(out) if isinstance(message, ToolMessage))
    assert message.content.endswith("r" * MAX_REASON_CHARS)
    assert "r" * (MAX_REASON_CHARS + 1) not in message.content


def test_unknown_option_reason_is_bounded():
    agent, config, paused = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}))
    out = agent.invoke(
        Command(resume={"responses": [approval_response(paused, "x" * (MAX_REASON_CHARS * 2))]}),
        config,
    )
    message = next(message for message in messages_of(out) if isinstance(message, ToolMessage))
    prefix = "The tool was not executed. Do not retry unless the user explicitly asks. User reason: "
    assert message.status == "error"
    assert len(message.content) <= len(prefix) + MAX_REASON_CHARS


def _approval_calls(count: int) -> list[dict[str, Any]]:
    return [{"name": "write_file", "args": {"path": f"/tmp/{index}.txt", "content": "x"}, "id": f"call_{index}"} for index in range(count)]


def test_more_than_configured_max_actions_denies_every_call_without_pausing():
    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}, max_actions=2), tool_calls=_approval_calls(3))
    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert "__interrupt__" not in out
    assert len(tool_messages) == 3
    assert all(message.status == "error" for message in tool_messages)
    assert all("3 > 2" in message.content for message in tool_messages)


def test_max_actions_boundary_still_pauses_for_approval():
    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}, max_actions=2), tool_calls=_approval_calls(2))
    assert len(out["__interrupt__"][0].value["actions"]) == 2


def test_zero_max_actions_disables_count_limit():
    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}, max_actions=0), tool_calls=_approval_calls(33))
    assert len(out["__interrupt__"][0].value["actions"]) == 33


def test_max_actions_config_rejects_negative_values():
    assert HitlApprovalConfig(max_actions=0).max_actions == 0
    with pytest.raises(ValueError, match="max_actions"):
        HitlApprovalConfig(max_actions=-1)


def test_oversized_approval_payload_denies_without_pausing():
    _, _, out = run_pause(
        HitlApprovalMiddleware(tool_names={"write_file"}),
        tool_args={"path": "/tmp/" + "x" * MAX_PAYLOAD_BYTES, "content": "hello"},
    )
    tool_messages = [message for message in messages_of(out) if isinstance(message, ToolMessage)]
    assert "__interrupt__" not in out
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"


def test_summarize_args_preserves_high_semantic_fields():
    long_content = "x" * 5000
    summary = summarize_args({"path": "/tmp/a.txt", "content": long_content, "old_str": "a", "new_str": "b"})
    assert summary["path"] == "/tmp/a.txt"
    assert summary["old_str"] == "a"
    assert summary["new_str"] == "b"
    assert "chars omitted" in summary["content"]
    assert summary["content"].startswith("xxxx")
    assert summary["content"].endswith("xxxx")


def _visible_text(content):
    if isinstance(content, str):
        return content
    return chr(10).join(block.get("text", "") for block in content if isinstance(block, dict))


def _assert_stripped_without_pausing(out):
    assert "__interrupt__" not in out
    messages = messages_of(out)
    # No result can be paired with an unaddressable call, so the call is removed
    # instead of answered: nothing may execute and nothing may pause.
    assert not any(isinstance(message, ToolMessage) for message in messages)
    assert not any("OK" in _visible_text(message.content) for message in messages)
    answers = [message for message in messages if isinstance(message, AIMessage)]
    assert all(not message.tool_calls for message in answers)
    assert any("no usable id" in _visible_text(message.content) for message in answers)


def test_null_tool_call_id_is_denied_instead_of_pausing():
    """A provider can emit a tool call without an id; pausing would wedge the thread.

    The Gateway resume validator rejects a payload whose ``pending_tool_call_ids``
    contains a non-string with 422, while a pending pause blocks new runs with
    409, so an interrupt created here could never be cleared.
    """
    calls = [{"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": None}]

    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)

    _assert_stripped_without_pausing(out)


def test_duplicate_tool_call_ids_are_denied_instead_of_pausing():
    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_dup"},
        {"name": "write_file", "args": {"path": "/tmp/b.txt", "content": "b"}, "id": "call_dup"},
    ]

    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)

    _assert_stripped_without_pausing(out)


def test_empty_tool_call_id_is_denied_instead_of_pausing():
    calls = [{"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": ""}]

    _, _, out = run_pause(HitlApprovalMiddleware(tool_names={"write_file"}), tool_calls=calls)

    _assert_stripped_without_pausing(out)


class _RawPayloadApprovalModel(FakeMessagesListChatModel):
    """Emit structured tool calls plus the raw OpenAI-style provider payload."""

    calls: list[dict[str, Any]]

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="final answer"))])
        raw = [{"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call.get("args", {}))}} for call in self.calls]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=self.calls, additional_kwargs={"tool_calls": raw}))])


def test_stripping_a_shared_id_clears_the_raw_provider_payload_too():
    """A non-target call sharing the removed id must not keep the removed call serialized.

    ``clone_ai_message_with_tool_calls`` filters ``additional_kwargs["tool_calls"]``
    and content blocks by id, so a surviving ordinary call with the same id would
    keep the denied approval calls in the raw provider payload; the next request
    would advertise calls that have no result.
    """
    executed: list[str] = []

    @tool
    def echo(text: str = "") -> str:
        """Echo text."""
        executed.append("echo")
        return "echoed"

    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_shared"},
        {"name": "write_file", "args": {"path": "/tmp/b.txt", "content": "b"}, "id": "call_shared"},
        {"name": "echo", "args": {"text": "hi"}, "id": "call_shared"},
    ]
    model = _RawPayloadApprovalModel(responses=[], calls=calls)
    agent = create_agent(
        model,
        tools=[write_file, echo],
        middleware=[HitlApprovalMiddleware(tool_names={"write_file"})],
        checkpointer=InMemorySaver(),
    )

    out = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "shared-raw"}})

    assert "__interrupt__" not in out
    messages = messages_of(out)
    assert not any(isinstance(message, ToolMessage) for message in messages)
    assert executed == []
    answer = messages[-1]
    assert answer.tool_calls == []
    assert "tool_calls" not in answer.additional_kwargs
    assert "no usable id" in _visible_text(answer.content)


def test_shared_id_with_an_ordinary_call_is_denied_instead_of_pausing():
    """An id shared with a non-target call makes the approval ambiguous.

    Approving or rejecting the targeted call would also answer the ordinary one
    by id, so the colliding group is rejected before any pause is created.
    """
    executed: list[str] = []

    @tool
    def echo(text: str = "") -> str:
        """Echo text."""
        executed.append("echo")
        return "echoed"

    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_shared"},
        {"name": "echo", "args": {"text": "hi"}, "id": "call_shared"},
    ]
    model = _RawPayloadApprovalModel(responses=[], calls=calls)
    agent = create_agent(
        model,
        tools=[write_file, echo],
        middleware=[HitlApprovalMiddleware(tool_names={"write_file"})],
        checkpointer=InMemorySaver(),
    )

    out = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "shared-mixed"}})

    assert "__interrupt__" not in out
    messages = messages_of(out)
    assert not any(isinstance(message, ToolMessage) for message in messages)
    assert executed == []
    answer = messages[-1]
    assert answer.tool_calls == []
    assert "tool_calls" not in answer.additional_kwargs
    assert "no usable id" in _visible_text(answer.content)


def test_deny_path_strips_a_target_sharing_an_id_with_an_ordinary_call():
    """Denying by result answers a call by id, so a shared id must be stripped.

    ``_deny_all`` routed on ``_addressable`` (uniqueness within the targets), so
    a target whose id an ordinary call also carried got a deny ``ToolMessage``
    while the ordinary call stayed serialized. The next request then advertised
    the id twice with two results, which strict providers reject.
    """
    executed: list[str] = []

    @tool
    def echo(text: str = "") -> str:
        """Echo text."""
        executed.append("echo")
        return "echoed"

    calls = [
        {"name": "write_file", "args": {"path": "/tmp/a.txt", "content": "a"}, "id": "call_shared"},
        {"name": "echo", "args": {"text": "hi"}, "id": "call_shared"},
    ]
    model = _RawPayloadApprovalModel(responses=[], calls=calls)
    agent = create_agent(
        model,
        tools=[write_file, echo],
        middleware=[HitlApprovalMiddleware(tool_names={"write_file"}, supports_resume=False)],
        checkpointer=InMemorySaver(),
    )

    out = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, {"configurable": {"thread_id": "shared-deny"}})

    assert "__interrupt__" not in out
    messages = messages_of(out)
    assert not any(isinstance(message, ToolMessage) for message in messages)
    assert executed == []
    answer = messages[-1]
    assert answer.tool_calls == []
    assert "tool_calls" not in answer.additional_kwargs
    assert "cannot collect approval" in _visible_text(answer.content)
