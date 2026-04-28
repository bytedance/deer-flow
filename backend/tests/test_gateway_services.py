"""Tests for app.gateway.services — run lifecycle service layer."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException


def test_format_sse_basic():
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"})
    assert frame.startswith("event: metadata\n")
    assert "data: " in frame
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["run_id"] == "abc"


def test_format_sse_with_event_id():
    from app.gateway.services import format_sse

    frame = format_sse("metadata", {"run_id": "abc"}, event_id="123-0")
    assert "id: 123-0" in frame


def test_format_sse_end_event_null():
    from app.gateway.services import format_sse

    frame = format_sse("end", None)
    assert "data: null" in frame


def test_format_sse_no_event_id():
    from app.gateway.services import format_sse

    frame = format_sse("values", {"x": 1})
    assert "id:" not in frame


def test_normalize_stream_modes_none():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(None) == ["values"]


def test_normalize_stream_modes_string():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes("messages-tuple") == ["messages-tuple"]


def test_normalize_stream_modes_list():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes(["values", "messages-tuple"]) == ["values", "messages-tuple"]


def test_normalize_stream_modes_empty_list():
    from app.gateway.services import normalize_stream_modes

    assert normalize_stream_modes([]) == ["values"]


def test_normalize_input_none():
    from app.gateway.services import normalize_input

    assert normalize_input(None) == {}


def test_normalize_input_with_messages():
    from app.gateway.services import normalize_input

    result = normalize_input({"messages": [{"role": "user", "content": "hi"}]})
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == "hi"


def test_normalize_input_passthrough():
    from app.gateway.services import normalize_input

    result = normalize_input({"custom_key": "value"})
    assert result == {"custom_key": "value"}


def test_build_run_config_basic():
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None)
    assert config["configurable"]["thread_id"] == "thread-1"
    assert config["recursion_limit"] == 100


def test_build_run_config_with_overrides():
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4"}, "tags": ["test"]},
        {"user": "alice"},
    )
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["tags"] == ["test"]
    assert config["metadata"]["user"] == "alice"


# ---------------------------------------------------------------------------
# Regression tests for issue #1644:
# assistant_id not mapped to agent_name → custom agent SOUL.md never loaded
# ---------------------------------------------------------------------------


def test_build_run_config_custom_agent_injects_agent_name():
    """Custom assistant_id must be forwarded as configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="finalis")
    assert config["configurable"]["agent_name"] == "finalis"


def test_build_run_config_lead_agent_no_agent_name():
    """'lead_agent' assistant_id must NOT inject configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id="lead_agent")
    assert "agent_name" not in config["configurable"]


def test_build_run_config_none_assistant_id_no_agent_name():
    """None assistant_id must NOT inject configurable['agent_name']."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", None, None, assistant_id=None)
    assert "agent_name" not in config["configurable"]


def test_build_run_config_explicit_agent_name_not_overwritten():
    """An explicit configurable['agent_name'] in the request must take precedence."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"agent_name": "explicit-agent"}},
        None,
        assistant_id="other-agent",
    )
    assert config["configurable"]["agent_name"] == "explicit-agent"


def test_build_run_config_context_custom_agent_injects_agent_name():
    """Custom assistant_id must be forwarded as context['agent_name'] in context mode."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"model_name": "deepseek-v3"}},
        None,
        assistant_id="finalis",
    )

    assert config["context"]["agent_name"] == "finalis"
    assert "configurable" not in config


def test_resolve_agent_factory_returns_make_lead_agent():
    """resolve_agent_factory always returns make_lead_agent regardless of assistant_id."""
    from app.gateway.services import resolve_agent_factory
    from deerflow.agents.lead_agent.agent import make_lead_agent

    assert resolve_agent_factory(None) is make_lead_agent
    assert resolve_agent_factory("lead_agent") is make_lead_agent
    assert resolve_agent_factory("finalis") is make_lead_agent
    assert resolve_agent_factory("custom-agent-123") is make_lead_agent


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regression tests for issue #1699:
# context field in langgraph-compat requests not merged into configurable
# ---------------------------------------------------------------------------


def test_run_create_request_accepts_context():
    """RunCreateRequest must accept the ``context`` field without dropping it."""
    from app.gateway.routers.thread_runs import RunCreateRequest

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
    """RunCreateRequest without context should default to None (backward compat)."""
    from app.gateway.routers.thread_runs import RunCreateRequest

    body = RunCreateRequest(input=None)
    assert body.context is None


def test_context_merges_into_configurable():
    """Context values must be merged into config['configurable'] by start_run.

    Since start_run is async and requires many dependencies, we test the
    merging logic directly by simulating what start_run does.
    """
    from app.gateway.services import apply_context_overrides, build_run_config

    # Simulate the context merging logic from start_run
    config = build_run_config("thread-1", None, None)

    context = {
        "model_name": "deepseek-v3",
        "mode": "ultra",
        "reasoning_effort": "high",
        "thinking_enabled": True,
        "is_plan_mode": True,
        "subagent_enabled": True,
        "max_concurrent_subagents": 5,
        "thread_id": "should-be-ignored",
    }

    apply_context_overrides(config, context)

    assert config["configurable"]["model_name"] == "deepseek-v3"
    assert config["configurable"]["thinking_enabled"] is True
    assert config["configurable"]["is_plan_mode"] is True
    assert config["configurable"]["subagent_enabled"] is True
    assert config["configurable"]["max_concurrent_subagents"] == 5
    assert config["configurable"]["reasoning_effort"] == "high"
    assert config["configurable"]["mode"] == "ultra"
    # thread_id from context should NOT override the one from build_run_config
    assert config["configurable"]["thread_id"] == "thread-1"


def test_context_does_not_override_existing_configurable():
    """Values already in config.configurable must NOT be overridden by context."""
    from app.gateway.services import apply_context_overrides, build_run_config

    config = build_run_config(
        "thread-1",
        {"configurable": {"model_name": "gpt-4", "is_plan_mode": False}},
        None,
    )

    context = {
        "model_name": "deepseek-v3",
        "is_plan_mode": True,
        "subagent_enabled": True,
    }

    apply_context_overrides(config, context)

    # Existing values must NOT be overridden
    assert config["configurable"]["model_name"] == "gpt-4"
    assert config["configurable"]["is_plan_mode"] is False
    # New values should be added
    assert config["configurable"]["subagent_enabled"] is True


# ---------------------------------------------------------------------------
# build_run_config — context / configurable precedence (LangGraph >= 0.6.0)
# ---------------------------------------------------------------------------


def test_build_run_config_with_context():
    """When caller sends 'context', prefer it over 'configurable'."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"user_id": "u-42", "thread_id": "thread-1"}},
        None,
    )
    assert "context" in config
    assert config["context"]["user_id"] == "u-42"
    assert "configurable" not in config
    assert config["recursion_limit"] == 100


def test_build_run_config_null_context_becomes_empty_context():
    """When caller sends context=null, treat it as an empty context object."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None)

    assert config["context"] == {}
    assert "configurable" not in config


def test_build_run_config_rejects_non_mapping_context():
    """When caller sends a non-object context, raise a clear error instead of a TypeError."""
    import pytest

    from app.gateway.services import build_run_config

    with pytest.raises(ValueError, match="context"):
        build_run_config("thread-1", {"context": "bad-context"}, None)


def test_build_run_config_null_context_custom_agent_injects_agent_name():
    """Custom assistant_id can still be injected when context=null starts context mode."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-1", {"context": None}, None, assistant_id="finalis")

    assert config["context"] == {"agent_name": "finalis"}
    assert "configurable" not in config


def test_build_run_config_context_plus_configurable_warns(caplog):
    """When caller sends both 'context' and 'configurable', prefer 'context' and log a warning."""
    import logging

    from app.gateway.services import build_run_config

    with caplog.at_level(logging.WARNING, logger="app.gateway.services"):
        config = build_run_config(
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
    assert any("both 'context' and 'configurable'" in r.message for r in caplog.records)


def test_build_run_config_context_passthrough_other_keys():
    """Non-conflicting keys from request_config are still passed through when context is used."""
    from app.gateway.services import build_run_config

    config = build_run_config(
        "thread-1",
        {"context": {"thread_id": "thread-1"}, "tags": ["prod"]},
        None,
    )
    assert config["context"]["thread_id"] == "thread-1"
    assert "configurable" not in config
    assert config["tags"] == ["prod"]


def test_build_run_config_no_request_config():
    """When request_config is None, fall back to basic configurable with thread_id."""
    from app.gateway.services import build_run_config

    config = build_run_config("thread-abc", None, None)
    assert config["configurable"] == {"thread_id": "thread-abc"}
    assert "context" not in config


class CountingBridge:
    """Small wrapper around MemoryStreamBridge that counts publish_end calls."""

    def __init__(self):
        from deerflow.runtime import MemoryStreamBridge

        self._bridge = MemoryStreamBridge(queue_maxsize=32)
        self.end_calls: list[str] = []

    async def publish(self, run_id: str, event: str, data):
        await self._bridge.publish(run_id, event, data)

    async def publish_end(self, run_id: str):
        self.end_calls.append(run_id)
        await self._bridge.publish_end(run_id)

    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ):
        return self._bridge.subscribe(
            run_id,
            last_event_id=last_event_id,
            heartbeat_interval=heartbeat_interval,
        )

    async def cleanup(self, run_id: str, *, delay: float = 0):
        await self._bridge.cleanup(run_id, delay=delay)


def _make_gateway_request():
    from deerflow.runtime import RunManager

    app = FastAPI()
    app.state.stream_bridge = CountingBridge()
    app.state.run_manager = RunManager()
    app.state.checkpointer = SimpleNamespace()
    app.state.store = None
    return SimpleNamespace(app=app)


@pytest.mark.anyio
async def test_start_run_with_deps_launches_without_request(monkeypatch: pytest.MonkeyPatch):
    """Non-HTTP callers should be able to launch runs with explicit dependencies only."""
    from app.gateway.services import RunLaunchRequest, start_run_with_deps
    from deerflow.runtime import RunStatus

    request = _make_gateway_request()
    captured: dict[str, object] = {}

    async def fake_run_agent(bridge, run_manager, record, **kwargs):
        captured["graph_input"] = kwargs["graph_input"]
        captured["config"] = kwargs["config"]
        await run_manager.set_status(record.run_id, RunStatus.running)
        await run_manager.set_status(record.run_id, RunStatus.success)
        await bridge.publish_end(record.run_id)

    monkeypatch.setattr("app.gateway.services.run_agent", fake_run_agent)
    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda assistant_id: object())

    record = await start_run_with_deps(
        RunLaunchRequest(
            assistant_id="finalis",
            input={"messages": [{"role": "user", "content": "hi"}]},
            context={"model_name": "deepseek-v3", "is_plan_mode": True},
        ),
        "thread-1",
        bridge=request.app.state.stream_bridge,
        run_mgr=request.app.state.run_manager,
        checkpointer=request.app.state.checkpointer,
        store=request.app.state.store,
    )

    await asyncio.wait_for(record.task, timeout=1)

    config = captured["config"]
    graph_input = captured["graph_input"]
    assert record.thread_id == "thread-1"
    assert record.status == RunStatus.success
    assert graph_input["messages"][0].content == "hi"
    assert config["configurable"]["thread_id"] == "thread-1"
    assert config["configurable"]["agent_name"] == "finalis"
    assert config["configurable"]["model_name"] == "deepseek-v3"
    assert config["configurable"]["is_plan_mode"] is True


@pytest.mark.anyio
async def test_start_run_translates_conflict_error_to_http_exception(monkeypatch: pytest.MonkeyPatch):
    """The HTTP wrapper should preserve FastAPI error semantics."""
    from app.gateway.routers.thread_runs import RunCreateRequest
    from app.gateway.services import start_run
    from deerflow.runtime import ConflictError

    request = _make_gateway_request()

    async def fake_start_run_with_deps(*args, **kwargs):
        raise ConflictError("thread busy")

    monkeypatch.setattr("app.gateway.services.start_run_with_deps", fake_start_run_with_deps)

    with pytest.raises(HTTPException) as excinfo:
        await start_run(RunCreateRequest(input=None), "thread-1", request)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "thread busy"
