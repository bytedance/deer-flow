"""Tests for lead agent runtime model resolution behavior."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.agents.middlewares import summarization_middleware as summarization_middleware_module
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import DeltaThreadState, ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.config.summarization_config import SummarizationConfig
from deerflow.runtime.checkpoint_mode import INTERNAL_CHECKPOINT_MODE_KEY
from deerflow.runtime.secret_context import write_slash_skill_source_path
from deerflow.skills.types import Skill, SkillCategory

_POLICY_INTEGRATION_TOOL_CALLS: list[str] = []


@tool
def policy_integration_dangerous_tool() -> str:
    """Record an invocation of a tool that the active skill does not allow."""
    _POLICY_INTEGRATION_TOOL_CALLS.append("executed")
    return "executed"


class _PolicyBypassModel(BaseChatModel):
    """Emit a forbidden call even when the bound schema omits it."""

    call_count: int = 0
    bound_tool_names: list[list[str]] = []

    @property
    def _llm_type(self) -> str:
        return "policy-bypass-test"

    def bind_tools(self, tools: Any, **kwargs: Any):
        self.bound_tool_names.append([tool.name for tool in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "forbidden-call",
                        "name": policy_integration_dangerous_tool.name,
                        "args": {},
                    }
                ],
            )
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


class _PolicyStorageStub:
    def __init__(self, skills: list[Skill]):
        self._skills = skills

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        return [skill for skill in self._skills if skill.enabled or not enabled_only]

    def get_container_root(self) -> str:
        return "/mnt/skills"


def _make_app_config(models: list[ModelConfig], loop_detection: LoopDetectionConfig | None = None) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        loop_detection=loop_detection or LoopDetectionConfig(),
    )


def _make_model(name: str, *, supports_thinking: bool) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use="langchain_openai:ChatOpenAI",
        model=name,
        supports_thinking=supports_thinking,
        supports_vision=False,
    )


class ConfiguredGuardMiddleware(AgentMiddleware):
    pass


class ConfiguredAuditMiddleware(AgentMiddleware):
    pass


class ConfiguredInitFailureMiddleware(AgentMiddleware):
    def __init__(self) -> None:
        raise RuntimeError("configured middleware init failed")


class ConfiguredNonMiddleware:
    pass


def test_make_lead_agent_signature_matches_langgraph_server_factory_abi():
    assert list(inspect.signature(lead_agent_module.make_lead_agent).parameters) == ["config"]


def test_make_lead_agent_attaches_tracing_callbacks_at_graph_root(monkeypatch):
    """Regression guard: tracing handlers must be appended to
    ``config["callbacks"]`` (graph invocation root), and every in-graph
    ``create_chat_model`` call must pass ``attach_tracing=False``.

    Catches future contributors who forget the flag when adding new
    in-graph model creation, which would silently produce duplicate
    spans and break Langfuse session/user propagation.
    """
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    sentinel_handler = object()
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [sentinel_handler])

    seen_attach_tracing: list[bool] = []

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        seen_attach_tracing.append(attach_tracing)
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    config: dict = {"configurable": {"model_name": "safe-model"}}
    lead_agent_module._make_lead_agent(config, app_config=app_config)

    # Handler must land on the graph invocation config so the Langfuse
    # CallbackHandler fires ``on_chain_start(parent_run_id=None)`` and
    # propagates ``session_id`` / ``user_id`` onto the trace.
    assert sentinel_handler in (config.get("callbacks") or []), "build_tracing_callbacks output must be appended to config['callbacks']"

    # Every in-graph create_chat_model call must opt out of model-level
    # tracing to avoid duplicate spans.
    assert seen_attach_tracing, "_make_lead_agent did not call create_chat_model"
    assert all(flag is False for flag in seen_attach_tracing), f"in-graph create_chat_model must pass attach_tracing=False; got {seen_attach_tracing}"


def test_internal_make_lead_agent_uses_explicit_app_config(monkeypatch):
    app_config = _make_app_config([_make_model("explicit-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    def _raise_get_app_config():
        raise AssertionError("ambient get_app_config() must not be used when app_config is explicit")

    monkeypatch.setattr(lead_agent_module, "get_app_config", _raise_get_app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["name"] = name
        captured["app_config"] = app_config
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module._make_lead_agent(
        {"configurable": {"model_name": "explicit-model"}},
        app_config=app_config,
    )

    assert captured == {
        "name": "explicit-model",
        "app_config": app_config,
    }
    assert result["model"] is not None


@pytest.mark.parametrize("is_bootstrap", [False, True])
def test_internal_make_lead_agent_selects_and_normalizes_delta_state(monkeypatch, is_bootstrap):
    app_config = _make_app_config([_make_model("delta-model", supports_thinking=False)])
    middleware = ViewImageMiddleware()
    original_schema = middleware.state_schema

    import deerflow.tools as tools_module

    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        lead_agent_module,
        "build_middlewares",
        lambda config, model_name, agent_name=None, **kwargs: [middleware],
    )
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module._make_lead_agent(
        {
            "configurable": {
                "model_name": "delta-model",
                "is_bootstrap": is_bootstrap,
                INTERNAL_CHECKPOINT_MODE_KEY: "delta",
            }
        },
        app_config=app_config,
    )

    assert result["state_schema"] is DeltaThreadState
    assert result["middleware"][0] is not middleware
    assert middleware.state_schema is original_schema


def test_internal_make_lead_agent_does_not_take_mode_from_runtime_context(monkeypatch):
    app_config = _make_app_config([_make_model("full-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module._make_lead_agent(
        {
            "configurable": {
                "model_name": "full-model",
                INTERNAL_CHECKPOINT_MODE_KEY: "full",
            },
            "context": {INTERNAL_CHECKPOINT_MODE_KEY: "delta"},
        },
        app_config=app_config,
    )

    assert result["state_schema"] is ThreadState


def test_public_make_lead_agent_does_not_take_mode_from_runtime_context(monkeypatch):
    from deerflow.runtime import checkpoint_mode

    app_config = _make_app_config([_make_model("full-model", supports_thinking=False)])
    captured: dict[str, object] = {}

    monkeypatch.setattr(checkpoint_mode, "_frozen_checkpoint_channel_mode", None)

    def _capture(config, *, app_config):
        captured["config"] = config
        captured["app_config"] = app_config
        return object()

    monkeypatch.setattr(lead_agent_module, "_make_lead_agent", _capture)
    config = {
        "configurable": {"model_name": "full-model"},
        "context": {
            "app_config": app_config,
            INTERNAL_CHECKPOINT_MODE_KEY: "delta",
        },
    }

    lead_agent_module.make_lead_agent(config)

    assert config["configurable"][INTERNAL_CHECKPOINT_MODE_KEY] == "full"
    assert captured["app_config"] is app_config


def test_make_lead_agent_uses_runtime_app_config_from_context_without_global_read(monkeypatch):
    app_config = _make_app_config([_make_model("context-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    def _raise_get_app_config():
        raise AssertionError("ambient get_app_config() must not be used when runtime context already carries app_config")

    monkeypatch.setattr(lead_agent_module, "get_app_config", _raise_get_app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["name"] = name
        captured["app_config"] = app_config
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module.make_lead_agent(
        {
            "context": {
                "model_name": "context-model",
                "app_config": app_config,
            }
        }
    )

    assert captured == {
        "name": "context-model",
        "app_config": app_config,
    }
    assert result["model"] is not None


def test_resolve_model_name_falls_back_to_default(monkeypatch, caplog):
    app_config = _make_app_config(
        [
            _make_model("default-model", supports_thinking=False),
            _make_model("other-model", supports_thinking=True),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    with caplog.at_level("WARNING"):
        resolved = lead_agent_module._resolve_model_name("missing-model")

    assert resolved == "default-model"
    assert "fallback to default model 'default-model'" in caplog.text


def test_resolve_model_name_uses_default_when_none(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model("default-model", supports_thinking=False),
            _make_model("other-model", supports_thinking=True),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    resolved = lead_agent_module._resolve_model_name(None)

    assert resolved == "default-model"


def test_resolve_model_name_raises_when_no_models_configured(monkeypatch):
    app_config = _make_app_config([])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    with pytest.raises(
        ValueError,
        match="No chat models are configured",
    ):
        lead_agent_module._resolve_model_name("missing-model")


def test_make_lead_agent_disables_thinking_when_model_does_not_support_it(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["name"] = name
        captured["thinking_enabled"] = thinking_enabled
        captured["reasoning_effort"] = reasoning_effort
        captured["app_config"] = app_config
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module.make_lead_agent(
        {
            "configurable": {
                "model_name": "safe-model",
                "thinking_enabled": True,
                "is_plan_mode": False,
                "subagent_enabled": False,
            }
        }
    )

    assert captured["name"] == "safe-model"
    assert captured["thinking_enabled"] is False
    assert captured["app_config"] is app_config
    assert result["model"] is not None


def test_make_lead_agent_reads_runtime_options_from_context(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model("default-model", supports_thinking=False),
            _make_model("context-model", supports_thinking=True),
        ]
    )

    import deerflow.tools as tools_module

    get_available_tools = MagicMock(return_value=[])
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", get_available_tools)
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["name"] = name
        captured["thinking_enabled"] = thinking_enabled
        captured["reasoning_effort"] = reasoning_effort
        captured["app_config"] = app_config
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module.make_lead_agent(
        {
            "context": {
                "model_name": "context-model",
                "thinking_enabled": False,
                "reasoning_effort": "high",
                "is_plan_mode": True,
                "subagent_enabled": True,
                "max_concurrent_subagents": 7,
            }
        }
    )

    assert captured == {
        "name": "context-model",
        "thinking_enabled": False,
        "reasoning_effort": "high",
        "app_config": app_config,
    }
    get_available_tools.assert_called_once_with(model_name="context-model", groups=None, subagent_enabled=True, app_config=app_config)
    assert result["model"] is not None


def test_make_lead_agent_filters_clarification_tool_for_non_interactive_runs(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    def _named_tool(name: str):
        tool = MagicMock()
        tool.name = name
        return tool

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(
        tools_module,
        "get_available_tools",
        lambda **kwargs: [_named_tool("ask_clarification"), _named_tool("bash")],
    )
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module.make_lead_agent(
        {
            "context": {
                "model_name": "safe-model",
                "thinking_enabled": False,
                "subagent_enabled": False,
                "non_interactive": True,
            }
        }
    )

    assert [tool.name for tool in result["tools"]] == ["bash"]


def test_make_lead_agent_rejects_invalid_bootstrap_agent_name(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    with pytest.raises(ValueError, match="Invalid agent name"):
        lead_agent_module.make_lead_agent(
            {
                "configurable": {
                    "model_name": "safe-model",
                    "thinking_enabled": False,
                    "is_plan_mode": False,
                    "subagent_enabled": False,
                    "is_bootstrap": True,
                    "agent_name": "../../../tmp/evil",
                }
            }
        )


def test_build_middlewares_uses_resolved_model_name_for_vision(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model("stale-model", supports_thinking=False),
            ModelConfig(
                name="vision-model",
                display_name="vision-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="vision-model",
                supports_thinking=False,
                supports_vision=True,
            ),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda **kwargs: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"model_name": "stale-model", "is_plan_mode": False, "subagent_enabled": False}},
        model_name="vision-model",
        custom_middlewares=[MagicMock()],
        app_config=app_config,
    )

    assert any(isinstance(m, lead_agent_module.ViewImageMiddleware) for m in middlewares)
    # verify the custom middleware is injected correctly.
    # With this test's default safety config enabled, the tail order is:
    #   ..., custom, TerminalResponseMiddleware, SafetyFinishReasonMiddleware,
    #   ClarificationMiddleware, so the custom mock sits at index [-4].
    assert len(middlewares) > 0 and isinstance(middlewares[-4], MagicMock)

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware

    assert isinstance(middlewares[-3], TerminalResponseMiddleware)
    assert isinstance(middlewares[-2], SafetyFinishReasonMiddleware)
    assert isinstance(middlewares[-1], ClarificationMiddleware)


def test_build_middlewares_passes_explicit_app_config_to_shared_factory(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])
    captured: dict[str, object] = {}

    def _raise_get_app_config():
        raise AssertionError("ambient get_app_config() must not be used when app_config is explicit")

    def _fake_build_lead_runtime_middlewares(*, app_config, lazy_init):
        captured["app_config"] = app_config
        captured["lazy_init"] = lazy_init
        return ["base-middleware"]

    monkeypatch.setattr(lead_agent_module, "get_app_config", _raise_get_app_config)
    monkeypatch.setattr(
        lead_agent_module,
        "build_lead_runtime_middlewares",
        _fake_build_lead_runtime_middlewares,
    )
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda **kwargs: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)
    monkeypatch.setattr(
        lead_agent_module,
        "TitleMiddleware",
        lambda *, app_config: captured.setdefault("title_app_config", app_config) or "title-middleware",
    )
    monkeypatch.setattr(
        lead_agent_module,
        "MemoryMiddleware",
        lambda agent_name=None, *, memory_config: captured.setdefault("memory_config", memory_config) or "memory-middleware",
    )

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )

    assert captured == {
        "app_config": app_config,
        "lazy_init": True,
        "title_app_config": app_config,
        "memory_config": app_config.memory,
    }
    assert middlewares[0] == "base-middleware"


def test_build_middlewares_orders_skill_activation_before_policy_and_durable_context(monkeypatch):
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )

    activation_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, SkillActivationMiddleware))
    policy_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, SkillToolPolicyMiddleware))
    durable_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, DurableContextMiddleware))
    assert policy_idx == activation_idx + 1
    assert durable_idx == policy_idx + 1
    assert middlewares[activation_idx]._slash_source_owner_token == middlewares[policy_idx]._slash_source_owner_token


@pytest.mark.parametrize("use_stale_path", [False, True], ids=["restrictive-skill", "stale-active-path"])
def test_compiled_skill_policy_chain_filters_schema_and_blocks_execution(monkeypatch, use_stale_path):
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )
    activation_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, SkillActivationMiddleware))
    durable_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, DurableContextMiddleware))
    compiled_slice = middlewares[activation_idx : durable_idx + 1]
    assert [type(middleware) for middleware in compiled_slice] == [SkillActivationMiddleware, SkillToolPolicyMiddleware, DurableContextMiddleware]

    skill_dir = Path("/tmp/skills/public/restricted")
    restricted = Skill(
        name="restricted",
        description="Restrictive integration skill",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path("restricted"),
        category=SkillCategory.PUBLIC,
        allowed_tools=("read_file",),
        enabled=True,
    )
    policy = compiled_slice[1]
    policy._storage = lambda: _PolicyStorageStub([] if use_stale_path else [restricted])

    context: dict[str, object] = {}
    active_path = "/mnt/skills/public/missing/SKILL.md" if use_stale_path else restricted.get_container_file_path()
    write_slash_skill_source_path(
        context,
        active_path,
        owner_token=policy._slash_source_owner_token,
    )
    model = _PolicyBypassModel()
    _POLICY_INTEGRATION_TOOL_CALLS.clear()
    graph = create_agent(
        model=model,
        tools=[policy_integration_dangerous_tool],
        middleware=compiled_slice,
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="continue under the active skill")]},
        context=context,
    )

    # LangChain skips ``bind_tools`` entirely when middleware filters the
    # request to zero schemas. If the forbidden schema survived, this list
    # would contain a binding with ``policy_integration_dangerous_tool``.
    assert model.bound_tool_names == []
    assert _POLICY_INTEGRATION_TOOL_CALLS == []
    blocked = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "forbidden-call"]
    assert len(blocked) == 1
    assert blocked[0].status == "error"
    assert "not allowed by the active skill policy" in blocked[0].content


def test_build_middlewares_places_mcp_routing_before_deferred_filter(monkeypatch):
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
    from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)], loop_detection=LoopDetectionConfig(enabled=False))
    routing = McpRoutingMiddleware({"mcp_thing": {"priority": 100, "keywords": ["orders"]}}, "hash123", 3)
    setup = DeferredToolSetup(object(), frozenset({"mcp_thing"}), "hash123")

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
        deferred_setup=setup,
        mcp_routing_middleware=routing,
    )

    routing_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, McpRoutingMiddleware))
    filter_idx = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, DeferredToolFilterMiddleware))
    assert routing_idx < filter_idx


def test_build_middlewares_uses_loop_detection_config(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(
            warn_threshold=7,
            hard_limit=9,
            window_size=30,
            max_tracked_threads=40,
            tool_freq_warn=50,
            tool_freq_hard_limit=60,
        ),
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )

    loop_detection = next(m for m in middlewares if isinstance(m, LoopDetectionMiddleware))
    assert loop_detection.warn_threshold == 7
    assert loop_detection.hard_limit == 9
    assert loop_detection.window_size == 30
    assert loop_detection.max_tracked_threads == 40
    assert loop_detection.tool_freq_warn == 50
    assert loop_detection.tool_freq_hard_limit == 60


def test_build_middlewares_omits_loop_detection_when_disabled(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )

    assert not any(isinstance(m, LoopDetectionMiddleware) for m in middlewares)


def test_build_middlewares_injects_configured_extension_middlewares(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.extensions = ExtensionsConfig(
        middlewares=[
            f"{__name__}:ConfiguredGuardMiddleware",
            f"{__name__}:ConfiguredAuditMiddleware",
        ]
    )
    manual_middleware = MagicMock()

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        custom_middlewares=[manual_middleware],
        app_config=app_config,
    )

    middleware_types = [type(m).__name__ for m in middlewares]
    assert middleware_types[-5:] == [
        "ConfiguredGuardMiddleware",
        "ConfiguredAuditMiddleware",
        "TerminalResponseMiddleware",
        "SafetyFinishReasonMiddleware",
        "ClarificationMiddleware",
    ]
    assert middlewares[middleware_types.index("ConfiguredGuardMiddleware") - 1] is manual_middleware


def test_build_middlewares_passes_subagent_total_limit_from_app_config(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.subagents = SubagentsAppConfig(max_total_per_run=7)

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": True, "max_concurrent_subagents": 3}},
        model_name="safe-model",
        app_config=app_config,
    )

    limit = next(m for m in middlewares if isinstance(m, SubagentLimitMiddleware))
    assert limit.max_concurrent == 3
    assert limit.max_total == 7


def test_build_middlewares_allows_runtime_subagent_total_limit_override(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.subagents = SubagentsAppConfig(max_total_per_run=7)

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    middlewares = lead_agent_module.build_middlewares(
        {
            "configurable": {
                "is_plan_mode": False,
                "subagent_enabled": True,
                "max_concurrent_subagents": 3,
                "max_total_subagents": 5,
            }
        },
        model_name="safe-model",
        app_config=app_config,
    )

    limit = next(m for m in middlewares if isinstance(m, SubagentLimitMiddleware))
    assert limit.max_total == 5


def test_build_middlewares_rejects_invalid_configured_extension_middleware(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.extensions = ExtensionsConfig(middlewares=[f"{__name__}:_make_model"])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    with pytest.raises(ValueError, match="not an instance of type"):
        lead_agent_module.build_middlewares(
            {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
            model_name="safe-model",
            app_config=app_config,
        )


def test_build_middlewares_rejects_configured_extension_class_with_wrong_base(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.extensions = ExtensionsConfig(middlewares=[f"{__name__}:ConfiguredNonMiddleware"])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    with pytest.raises(ValueError, match="is not a subclass of AgentMiddleware"):
        lead_agent_module.build_middlewares(
            {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
            model_name="safe-model",
            app_config=app_config,
        )


def test_build_middlewares_reraises_configured_extension_instantiation_failure(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.extensions = ExtensionsConfig(middlewares=[f"{__name__}:ConfiguredInitFailureMiddleware"])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    with pytest.raises(RuntimeError, match="configured middleware init failed"):
        lead_agent_module.build_middlewares(
            {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
            model_name="safe-model",
            app_config=app_config,
        )


def test_build_middlewares_rejects_missing_configured_extension_module(monkeypatch):
    app_config = _make_app_config(
        [_make_model("safe-model", supports_thinking=False)],
        loop_detection=LoopDetectionConfig(enabled=False),
    )
    app_config.extensions = ExtensionsConfig(middlewares=["definitely_missing_pkg.middlewares_typo:GuardMiddleware"])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    with pytest.raises(ImportError, match="Could not import module definitely_missing_pkg.middlewares_typo"):
        lead_agent_module.build_middlewares(
            {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
            model_name="safe-model",
            app_config=app_config,
        )


def test_create_summarization_middleware_uses_configured_model_alias(monkeypatch):
    app_config = _make_app_config([_make_model("model-masswork", supports_thinking=False)])
    app_config.summarization = SummarizationConfig(enabled=True, model_name="model-masswork")
    app_config.memory = MemoryConfig(enabled=False)

    from unittest.mock import MagicMock

    captured: dict[str, object] = {}
    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model

    def _fake_create_chat_model(*, name=None, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["name"] = name
        captured["thinking_enabled"] = thinking_enabled
        captured["reasoning_effort"] = reasoning_effort
        captured["app_config"] = app_config
        return fake_model

    def _raise_get_app_config():
        raise AssertionError("ambient get_app_config() must not be used when app_config is explicit")

    monkeypatch.setattr(summarization_middleware_module, "get_app_config", _raise_get_app_config)
    monkeypatch.setattr(summarization_middleware_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(summarization_middleware_module, "DeerFlowSummarizationMiddleware", lambda **kwargs: kwargs)

    middleware = lead_agent_module._create_summarization_middleware(app_config=app_config)

    assert captured["name"] == "model-masswork"
    assert captured["thinking_enabled"] is False
    assert captured["app_config"] is app_config
    assert middleware["model"] is fake_model
    fake_model.with_config.assert_called_once_with(tags=["middleware:summarize"])


def test_create_summarization_middleware_omits_model_name_when_unconfigured(monkeypatch):
    app_config = _make_app_config([_make_model("default-model", supports_thinking=False)])
    app_config.summarization = SummarizationConfig(enabled=True, model_name=None)
    app_config.memory = MemoryConfig(enabled=False)

    captured: dict[str, object] = {}
    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model

    def _fake_create_chat_model(**kwargs):
        captured.update(kwargs)
        return fake_model

    monkeypatch.setattr(summarization_middleware_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(summarization_middleware_module, "DeerFlowSummarizationMiddleware", lambda **kwargs: kwargs)

    middleware = lead_agent_module._create_summarization_middleware(app_config=app_config)

    assert "name" not in captured
    assert captured["thinking_enabled"] is False
    assert captured["app_config"] is app_config
    assert middleware["model"] is fake_model


def test_create_summarization_middleware_uses_frontend_supported_update_key(monkeypatch):
    """LangGraph update keys use the middleware class name plus hook name."""

    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])
    app_config.summarization = SummarizationConfig(enabled=True)
    app_config.memory = MemoryConfig(enabled=False)

    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model
    monkeypatch.setattr(summarization_middleware_module, "create_chat_model", lambda **kwargs: fake_model)

    middleware = lead_agent_module._create_summarization_middleware(app_config=app_config)

    assert middleware is not None
    update_key = f"{type(middleware).__name__}.before_model"
    assert update_key == "DeerFlowSummarizationMiddleware.before_model"


def test_create_summarization_middleware_threads_resolved_app_config_to_model(monkeypatch):
    fallback_app_config = _make_app_config([_make_model("fallback-model", supports_thinking=False)])
    fallback_app_config.summarization = SummarizationConfig(enabled=True, model_name="fallback-model")
    fallback_app_config.memory = MemoryConfig(enabled=False)

    from unittest.mock import MagicMock

    captured: dict[str, object] = {}
    fake_model = MagicMock()
    fake_model.with_config.return_value = fake_model

    def _fake_create_chat_model(*, name=None, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["app_config"] = app_config
        return fake_model

    monkeypatch.setattr(summarization_middleware_module, "get_app_config", lambda: fallback_app_config)
    monkeypatch.setattr(summarization_middleware_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(summarization_middleware_module, "DeerFlowSummarizationMiddleware", lambda **kwargs: kwargs)

    lead_agent_module._create_summarization_middleware()

    assert captured["app_config"] is fallback_app_config


def test_memory_middleware_uses_explicit_memory_config_without_global_read(monkeypatch):
    from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

    def _raise_get_memory_config():
        raise AssertionError("ambient get_memory_config() must not be used when memory_config is explicit")

    monkeypatch.setattr(memory_middleware_module, "get_memory_config", _raise_get_memory_config)

    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=False))

    assert middleware.after_agent({"messages": []}, runtime=MagicMock(context={"thread_id": "thread-1"})) is None


# ---------------------------------------------------------------------------
# Per-agent model settings (issue #4336)
# ---------------------------------------------------------------------------


def test_resolve_runtime_option_precedence():
    # request value wins, even when falsy
    assert lead_agent_module._resolve_runtime_option({"thinking_enabled": False}, "thinking_enabled", True, True) is False
    # agent value used when request omits the key
    assert lead_agent_module._resolve_runtime_option({}, "thinking_enabled", True, False) is True
    # default when neither request nor agent set it
    assert lead_agent_module._resolve_runtime_option({}, "thinking_enabled", None, False) is False


def _make_agent_config(**kwargs):
    from deerflow.config.agents_config import AgentConfig

    return AgentConfig(name="researcher", **kwargs)


def test_make_lead_agent_applies_agent_model_settings(monkeypatch):
    """A custom agent's model_settings flow into create_chat_model as
    model_overrides, and its thinking/reasoning defaults apply when the request
    omits them (issue #4336)."""
    app_config = _make_app_config([_make_model("agent-model", supports_thinking=True)])
    agent_config = _make_agent_config(
        model="agent-model",
        model_settings={"temperature": 0.2, "max_tokens": 12000},
        thinking_enabled=False,
        reasoning_effort="high",
    )

    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda name: agent_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["thinking_enabled"] = thinking_enabled
        captured["reasoning_effort"] = reasoning_effort
        captured["model_overrides"] = model_overrides
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    lead_agent_module._make_lead_agent({"context": {"agent_name": "researcher"}}, app_config=app_config)

    assert captured["model_overrides"] == {"temperature": 0.2, "max_tokens": 12000}
    assert captured["thinking_enabled"] is False  # from agent config
    assert captured["reasoning_effort"] == "high"  # from agent config


def test_request_thinking_overrides_agent_default(monkeypatch):
    """An explicit request thinking_enabled wins over the agent's default."""
    app_config = _make_app_config([_make_model("agent-model", supports_thinking=True)])
    agent_config = _make_agent_config(model="agent-model", thinking_enabled=False)

    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda name: agent_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["thinking_enabled"] = thinking_enabled
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    lead_agent_module._make_lead_agent(
        {"context": {"agent_name": "researcher", "thinking_enabled": True}},
        app_config=app_config,
    )

    assert captured["thinking_enabled"] is True  # request wins over agent's False


def test_make_lead_agent_no_agent_settings_passes_none_overrides(monkeypatch):
    """Without a custom agent, model_overrides is None (no behavior change)."""
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda config, model_name, agent_name=None, **kwargs: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled, reasoning_effort=None, app_config=None, attach_tracing=True, model_overrides=None):
        captured["model_overrides"] = model_overrides
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    lead_agent_module._make_lead_agent({"context": {"model_name": "safe-model"}}, app_config=app_config)

    assert captured["model_overrides"] is None
