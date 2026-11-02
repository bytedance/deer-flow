import asyncio

import pytest
from deerflow_extension_api import AgentBuildContext, AgentScope, ExtensionData, Placement
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool

import deerflow_extension_skill_evolution.middleware as middleware_module
from deerflow_extension_skill_evolution.config import SCOPE_LEAD_AND_SUBAGENT, SkillEvolutionSettings
from deerflow_extension_skill_evolution.middleware import (
    POLICY_MESSAGE_ID,
    SkillEvolutionContributor,
    SkillEvolutionMiddleware,
)


def _fake_tool() -> StructuredTool:
    def _run(action: str, name: str = "", content: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(func=_run, name="skill_manage", description="fake host tool")


def _fake_feedback_tool() -> StructuredTool:
    async def _run(skill_name: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(coroutine=_run, name="skill_feedback", description="fake feedback tool")


def _make_middleware(**overrides) -> SkillEvolutionMiddleware:
    settings = overrides.pop("settings", SkillEvolutionSettings())
    tools = overrides.pop("tools", (_fake_tool(),))
    return SkillEvolutionMiddleware(tools=tools, settings=settings, **overrides)


def _ctx(scope: AgentScope) -> AgentBuildContext:
    return AgentBuildContext(scope=scope)


def test_middleware_declares_the_tool_as_a_plain_instance_attribute() -> None:
    middleware = _make_middleware()
    assert isinstance(middleware.tools, tuple)
    assert [tool.name for tool in middleware.tools] == ["skill_manage"]
    # Declaration narrowing writes clone.__dict__["tools"] directly; the
    # attribute must live on the instance, not on the class.
    assert "tools" in middleware.__dict__


def test_before_agent_injects_a_hidden_stamped_policy_message() -> None:
    middleware = _make_middleware()
    update = middleware.before_agent({"messages": []}, None)
    assert update is not None
    (message,) = update["messages"]
    assert isinstance(message, SystemMessage)
    assert message.id == POLICY_MESSAGE_ID
    assert message.additional_kwargs["hide_from_ui"] is True
    assert message.additional_kwargs["deerflow_content_kind"] == "middleware_injection"
    assert message.additional_kwargs["deerflow_producer_kind"] == "skill_evolution_extension"
    assert "skill_manage" in message.content


def test_injection_is_idempotent_across_runs() -> None:
    middleware = _make_middleware()
    first = middleware.before_agent({"messages": []}, None)
    assert first is not None
    # Second run on the same thread: the policy is already in state.
    assert middleware.before_agent({"messages": list(first["messages"])}, None) is None


def test_prompt_disabled_injects_nothing() -> None:
    middleware = _make_middleware(prompt_enabled=False)
    assert middleware.before_agent({"messages": []}, None) is None


def test_async_path_matches_sync_path() -> None:
    middleware = _make_middleware()
    sync_update = middleware.before_agent({"messages": []}, None)
    async_update = asyncio.run(middleware.abefore_agent({"messages": []}, None))
    assert sync_update is not None and async_update is not None
    assert sync_update["messages"][0].content == async_update["messages"][0].content
    assert sync_update["messages"][0].id == async_update["messages"][0].id


def test_release_policy_parameters_are_json_safe() -> None:
    params = _make_middleware().release_policy_parameters()
    assert params == {
        "skill_manage_tool_declared": True,
        "skill_feedback_tool_declared": False,
        "feedback_mode": "draft",
        "prompt_enabled": True,
        "min_tool_calls_hint": 5,
        "prefer_patch": True,
        "confirm_before_create": True,
    }


def test_feedback_tool_declaration_shapes_tools_and_policy() -> None:
    # Plan B: the middleware declares both tools, and the policy advertises
    # skill_feedback only because it is in the same tools tuple.
    middleware = _make_middleware(tools=(_fake_tool(), _fake_feedback_tool()), settings=SkillEvolutionSettings(feedback_mode="agent"))
    assert [tool.name for tool in middleware.tools] == ["skill_manage", "skill_feedback"]
    update = middleware.before_agent({"messages": []}, None)
    assert update is not None
    assert "skill_feedback(skill_name=" in update["messages"][0].content
    params = middleware.release_policy_parameters()
    assert params["skill_feedback_tool_declared"] is True
    assert params["feedback_mode"] == "agent"
    # Draft mode (or a missing tool): the policy must not mention the tool.
    draft = _make_middleware()
    update = draft.before_agent({"messages": []}, None)
    assert update is not None
    assert "skill_feedback" not in update["messages"][0].content


def test_contributor_defaults_to_lead_scope() -> None:
    contributor = SkillEvolutionContributor(settings=SkillEvolutionSettings(), tools=(_fake_tool(),))
    (placement,) = contributor.contribute_middlewares(ExtensionData("test"), _ctx(AgentScope.LEAD))
    assert placement.placement == Placement.STANDARD
    assert placement.scope == AgentScope.LEAD


def test_contributor_opt_in_widens_scope_to_both() -> None:
    contributor = SkillEvolutionContributor(settings=SkillEvolutionSettings(scope=SCOPE_LEAD_AND_SUBAGENT), tools=(_fake_tool(),))
    (placement,) = contributor.contribute_middlewares(ExtensionData("test"), _ctx(AgentScope.SUBAGENT))
    assert placement.scope & AgentScope.SUBAGENT


def test_contributor_suppresses_prompt_when_legacy_core_switch_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(middleware_module, "_legacy_core_switch_enabled", lambda: True)
    monkeypatch.setattr(middleware_module, "_legacy_switch_warned", False)
    contributor = SkillEvolutionContributor(settings=SkillEvolutionSettings(), tools=(_fake_tool(),))
    (placement,) = contributor.contribute_middlewares(ExtensionData("test"), _ctx(AgentScope.LEAD))
    middleware = placement.middleware
    # The tool is still contributed; only the duplicate prompt is suppressed.
    assert [tool.name for tool in middleware.tools] == ["skill_manage"]
    assert middleware.before_agent({"messages": []}, None) is None


def test_contributor_warns_about_the_legacy_switch_once(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(middleware_module, "_legacy_core_switch_enabled", lambda: True)
    monkeypatch.setattr(middleware_module, "_legacy_switch_warned", False)
    contributor = SkillEvolutionContributor(settings=SkillEvolutionSettings(), tools=(_fake_tool(),))
    with caplog.at_level("WARNING", logger="deerflow_extension_skill_evolution.middleware"):
        contributor.contribute_middlewares(ExtensionData("test"), _ctx(AgentScope.LEAD))
        contributor.contribute_middlewares(ExtensionData("test"), _ctx(AgentScope.LEAD))
    warnings = [record for record in caplog.records if "deprecated core" in record.message]
    assert len(warnings) == 1


def test_legacy_switch_probe_fails_open_without_deerflow(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    # ``None`` in sys.modules is the canonical "import must fail" sentinel;
    # it works regardless of whether the host package is really installed.
    monkeypatch.setitem(sys.modules, "deerflow.config", None)
    assert middleware_module._legacy_core_switch_enabled() is False
