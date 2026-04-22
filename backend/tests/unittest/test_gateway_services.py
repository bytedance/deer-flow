"""Tests for the current runs service modules."""

from __future__ import annotations

import json

from app.gateway.routers.langgraph.runs import RunCreateRequest, format_sse
from app.gateway.services.runs.facade_factory import resolve_agent_factory
from app.gateway.services.runs.input.request_adapter import (
    adapt_create_run_request,
    adapt_create_stream_request,
    adapt_create_wait_request,
    adapt_join_stream_request,
    adapt_join_wait_request,
)
from app.gateway.services.runs.input.spec_builder import RunSpecBuilder


def _builder() -> RunSpecBuilder:
    return RunSpecBuilder()


def _build_runnable_config(
    thread_id: str,
    request_config: dict | None,
    metadata: dict | None,
    *,
    assistant_id: str | None = None,
    context: dict | None = None,
):
    return _builder()._build_runnable_config(  # noqa: SLF001 - intentional unit coverage
        thread_id=thread_id,
        request_config=request_config,
        metadata=metadata,
        assistant_id=assistant_id,
        context=context,
    )


def test_format_sse_basic():
    frame = format_sse("metadata", {"run_id": "abc"})
    assert frame.startswith("event: metadata\n")
    assert "data: " in frame
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["run_id"] == "abc"


def test_format_sse_with_event_id():
    frame = format_sse("metadata", {"run_id": "abc"}, event_id="123-0")
    assert "id: 123-0" in frame


def test_format_sse_end_event_null():
    frame = format_sse("end", None)
    assert "data: null" in frame


def test_format_sse_no_event_id():
    frame = format_sse("values", {"x": 1})
    assert "id:" not in frame


def test_normalize_stream_modes_none():
    assert _builder()._normalize_stream_modes(None) == ["values", "messages"]  # noqa: SLF001


def test_normalize_stream_modes_string():
    assert _builder()._normalize_stream_modes("messages-tuple") == ["messages"]  # noqa: SLF001


def test_normalize_stream_modes_list():
    assert _builder()._normalize_stream_modes(["values", "messages-tuple"]) == ["values", "messages"]  # noqa: SLF001


def test_normalize_stream_modes_empty_list():
    assert _builder()._normalize_stream_modes([]) == []  # noqa: SLF001


def test_normalize_input_none():
    assert _builder()._normalize_input(None) is None  # noqa: SLF001


def test_normalize_input_with_messages():
    result = _builder()._normalize_input({"messages": [{"role": "user", "content": "hi"}]})  # noqa: SLF001
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "hi"


def test_normalize_input_passthrough():
    result = _builder()._normalize_input({"custom_key": "value"})  # noqa: SLF001
    assert result == {"custom_key": "value"}


def test_build_runnable_config_basic():
    config = _build_runnable_config("thread-1", None, None)
    assert config["configurable"]["thread_id"] == "thread-1"
    assert config["recursion_limit"] == 100


def test_build_runnable_config_with_overrides():
    config = _build_runnable_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4"}, "tags": ["test"]},
        {"user": "alice"},
    )
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["tags"] == ["test"]
    assert config["metadata"]["user"] == "alice"


def test_build_runnable_config_custom_agent_injects_agent_name():
    config = _build_runnable_config("thread-1", None, None, assistant_id="finalis")
    assert config["configurable"]["agent_name"] == "finalis"


def test_build_runnable_config_lead_agent_no_agent_name():
    config = _build_runnable_config("thread-1", None, None, assistant_id="lead_agent")
    assert "agent_name" not in config["configurable"]


def test_build_runnable_config_none_assistant_id_no_agent_name():
    config = _build_runnable_config("thread-1", None, None, assistant_id=None)
    assert "agent_name" not in config["configurable"]


def test_build_runnable_config_explicit_agent_name_not_overwritten():
    config = _build_runnable_config(
        "thread-1",
        {"configurable": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )
    assert config["configurable"]["agent_name"] == "explicit-agent"


def test_resolve_agent_factory_returns_make_lead_agent():
    from deerflow.agents.lead_agent.agent import make_lead_agent

    assert resolve_agent_factory(None) is make_lead_agent
    assert resolve_agent_factory("lead_agent") is make_lead_agent
    assert resolve_agent_factory("finalis") is make_lead_agent
    assert resolve_agent_factory("custom-agent-123") is make_lead_agent


def test_run_create_request_accepts_context():
    body = RunCreateRequest(
        input={"messages": [{"role": "user", "content": "hi"}]},
        context={
            "model_name": "deepseek-v3",
            "thinking_enabled": True,
            "is_plan_mode": True,
            "subagent_enabled": True,
            "thread_id": "some-thread-id",
        },
    )
    assert body.context is not None
    assert body.context["model_name"] == "deepseek-v3"
    assert body.context["is_plan_mode"] is True
    assert body.context["subagent_enabled"] is True


def test_run_create_request_context_defaults_to_none():
    body = RunCreateRequest(input=None)
    assert body.context is None


def test_context_merges_into_configurable():
    config = _build_runnable_config(
        "thread-1",
        None,
        None,
        context={
            "model_name": "deepseek-v3",
            "mode": "ultra",
            "reasoning_effort": "high",
            "thinking_enabled": True,
            "is_plan_mode": True,
            "subagent_enabled": True,
            "max_concurrent_subagents": 5,
            "thread_id": "should-be-ignored",
        },
    )
    assert config["configurable"]["model_name"] == "deepseek-v3"
    assert config["configurable"]["thinking_enabled"] is True
    assert config["configurable"]["is_plan_mode"] is True
    assert config["configurable"]["subagent_enabled"] is True
    assert config["configurable"]["max_concurrent_subagents"] == 5
    assert config["configurable"]["reasoning_effort"] == "high"
    assert config["configurable"]["mode"] == "ultra"
    assert config["configurable"]["thread_id"] == "thread-1"


def test_context_does_not_override_existing_configurable():
    config = _build_runnable_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4", "is_plan_mode": False}},
        None,
        context={
            "model_name": "deepseek-v3",
            "is_plan_mode": True,
            "subagent_enabled": True,
        },
    )
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["configurable"]["is_plan_mode"] is False
    assert config["configurable"]["subagent_enabled"] is True


def test_build_runnable_config_with_context_wrapper_in_request_config():
    config = _build_runnable_config(
        "thread-1",
        {"context": {"user_id": "u-42", "thread_id": "thread-1"}},
        None,
    )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    assert "configurable" not in config
    assert config["recursion_limit"] == 100


def test_build_runnable_config_context_plus_configurable_prefers_context():
    config = _build_runnable_config(
        "thread-1",
        {
            "context": {"user_id": "u-42"},
            "configurable": {"model_name": "gpt-4"},
        },
        None,
    )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    assert "configurable" not in config


def test_build_runnable_config_context_passthrough_other_keys():
    config = _build_runnable_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "tags": ["prod"]},
        None,
    )
    assert config["context"]["thread_id"] == "thread-1"
    assert "configurable" not in config
    assert config["tags"] == ["prod"]


def test_build_runnable_config_no_request_config():
    config = _build_runnable_config("thread-abc", None, None)
    assert config["configurable"] == {"thread_id": "thread-abc"}
    assert "context" not in config


def test_request_adapter_create_background():
    adapted = adapt_create_run_request(thread_id="thread-1", body={"input": {"x": 1}})
    assert adapted.intent == "create_background"
    assert adapted.thread_id == "thread-1"
    assert adapted.run_id is None


def test_request_adapter_create_stream():
    adapted = adapt_create_stream_request(thread_id=None, body={"input": {"x": 1}})
    assert adapted.intent == "create_and_stream"
    assert adapted.thread_id is None
    assert adapted.is_stateless is True


def test_request_adapter_create_wait():
    adapted = adapt_create_wait_request(thread_id="thread-1", body={})
    assert adapted.intent == "create_and_wait"
    assert adapted.thread_id == "thread-1"


def test_request_adapter_join_stream():
    adapted = adapt_join_stream_request(thread_id="thread-1", run_id="run-1", headers={"Last-Event-ID": "123"})
    assert adapted.intent == "join_stream"
    assert adapted.last_event_id == "123"


def test_request_adapter_join_wait():
    adapted = adapt_join_wait_request(thread_id="thread-1", run_id="run-1")
    assert adapted.intent == "join_wait"
    assert adapted.run_id == "run-1"
