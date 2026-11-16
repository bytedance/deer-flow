"""Scheduler tools use a current-run host grant, never model-owned identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.tools.tools import get_available_tools


def _config(*, enabled=True, tool_enabled=True):
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "safe-model", "use": "langchain_openai:ChatOpenAI", "model": "safe-model"}],
            "scheduler": {"enabled": enabled, "tool_enabled": tool_enabled},
        }
    )


def _capability(mode="interactive"):
    return SimpleNamespace(mode=mode, manage=AsyncMock(return_value={"task_id": "task-1"}), stop_current_schedule=AsyncMock(return_value={"stop_requested": True}))


def _runtime(*, capability=None, mode="interactive", is_subagent=False, enabled=True, tool_enabled=True):
    return SimpleNamespace(
        context={
            "app_config": _config(enabled=enabled, tool_enabled=tool_enabled),
            "__scheduler_capability": capability,
            "interaction_mode": mode,
            "is_subagent": is_subagent,
        },
        config={},
        state={},
    )


def test_conversation_schedule_tools_are_off_by_default():
    assert SchedulerConfig().tool_enabled is False


@pytest.mark.parametrize(
    ("enabled", "tool_enabled", "mode", "expected"),
    [
        (True, True, "interactive", {"schedule_task"}),
        (True, True, "scheduled", {"stop_scheduled_task"}),
        (False, True, "interactive", set()),
        (True, False, "interactive", set()),
        (False, False, "scheduled", set()),
        (True, True, "webhook", set()),
    ],
)
def test_tool_assembly_requires_both_flags_and_selects_only_the_bound_mode(enabled, tool_enabled, mode, expected):
    tools = get_available_tools(include_mcp=False, include_upload_tool=False, app_config=_config(enabled=enabled, tool_enabled=tool_enabled), scheduler_capability=_capability(mode))
    assert {tool.name for tool in tools} & {"schedule_task", "stop_scheduled_task"} == expected


def test_tool_assembly_without_host_grant_keeps_legacy_tools_and_no_scheduler():
    tools = get_available_tools(include_mcp=False, include_upload_tool=False, app_config=_config())
    names = {tool.name for tool in tools}
    assert {"ask_clarification", "present_files"} <= names
    assert names.isdisjoint({"schedule_task", "stop_scheduled_task"})


@pytest.mark.parametrize(("enabled", "tool_enabled", "mode"), [(False, True, "interactive"), (True, False, "scheduled"), (True, True, None), (True, True, "interactive"), (True, True, "scheduled")])
def test_direct_yaml_registration_cannot_bypass_dynamic_tool_scope(enabled, tool_enabled, mode):
    config = _config(enabled=enabled, tool_enabled=tool_enabled)
    config = AppConfig.model_validate(
        {
            **config.model_dump(),
            "tools": [{"name": name, "group": "scheduler", "use": f"deerflow.tools.scheduled_tasks:{name}"} for name in ("schedule_task", "stop_scheduled_task")],
        }
    )
    kwargs = {"scheduler_capability": _capability(mode)} if mode is not None else {}
    tools = get_available_tools(include_mcp=False, include_upload_tool=False, app_config=config, **kwargs)
    expected = {"schedule_task" if mode == "interactive" else "stop_scheduled_task"} if enabled and tool_enabled and mode is not None else set()
    assert {tool.name for tool in tools} & {"schedule_task", "stop_scheduled_task"} == expected


@pytest.mark.parametrize("capability", [None, {"mode": "interactive"}, SimpleNamespace(mode="interactive"), _capability(["interactive"])])
def test_tool_assembly_rejects_data_shaped_like_a_capability(capability):
    tools = get_available_tools(include_mcp=False, include_upload_tool=False, app_config=_config(), scheduler_capability=capability)
    assert {tool.name for tool in tools}.isdisjoint({"schedule_task", "stop_scheduled_task"})


@pytest.mark.asyncio
async def test_create_passes_only_definition_fields_to_host_capability():
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability()
    result = await schedule_task.coroutine(
        runtime=_runtime(capability=capability),
        action="create",
        title="Weekly report",
        prompt="Write the weekly report",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * 5"},
        timezone="Asia/Shanghai",
        goal_objective="Write a report using this week's source documents",
        max_runs=3,
        end_at="2026-11-01T00:00:00+08:00",
    )
    assert result == {"task_id": "task-1"}
    capability.manage.assert_awaited_once_with(
        action="create",
        request={
            "title": "Weekly report",
            "prompt": "Write the weekly report",
            "schedule_type": "cron",
            "schedule_spec": {"cron": "0 9 * * 5"},
            "timezone": "Asia/Shanghai",
            "context_mode": "fresh_thread_per_run",
            "goal_objective": "Write a report using this week's source documents",
            "max_runs": 3,
            "end_at": "2026-11-01T00:00:00+08:00",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["list", "pause", "delete", "note", "trial"])
async def test_interactive_actions_forward_a_bounded_task_selector_without_identity(action):
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability()
    kwargs = {} if action == "list" else {"task_id": "task-1"}
    if action == "note":
        kwargs["note"] = "  use the develop branch  "
    await schedule_task.coroutine(runtime=_runtime(capability=capability), action=action, **kwargs)
    capability.manage.assert_awaited_once_with(action=action, request=kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "capability_mode", "is_subagent", "enabled", "tool_enabled"),
    [
        ("scheduled", "interactive", False, True, True),
        ("autonomous", "interactive", False, True, True),
        ("webhook", "interactive", False, True, True),
        ("interactive", "scheduled", False, True, True),
        ("interactive", "interactive", True, True, True),
        ("interactive", "interactive", False, False, True),
        ("interactive", "interactive", False, True, False),
    ],
)
async def test_management_invocation_cannot_bypass_mode_subagent_or_config_gate(mode, capability_mode, is_subagent, enabled, tool_enabled):
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability(capability_mode)
    result = await schedule_task.coroutine(runtime=_runtime(capability=capability, mode=mode, is_subagent=is_subagent, enabled=enabled, tool_enabled=tool_enabled), action="list")
    assert (result["code"], result["status_code"]) == ("scheduler_tools_disabled", 503)
    assert result["error"]
    capability.manage.assert_not_awaited()
    capability.stop_current_schedule.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("grant_location", ["state", "configurable"])
async def test_saved_state_and_configurable_cannot_supply_scheduler_authority(grant_location):
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability()
    runtime = _runtime()
    if grant_location == "state":
        runtime.state["__scheduler_capability"] = capability
    else:
        runtime.config["configurable"] = {"__scheduler_capability": capability}
    result = await schedule_task.coroutine(runtime=runtime, action="list")
    assert "error" in result
    capability.manage.assert_not_awaited()


@pytest.mark.asyncio
async def test_self_stop_uses_bound_occurrence_without_any_model_identity_arguments():
    from deerflow.tools.scheduled_tasks import stop_scheduled_task

    capability = _capability("scheduled")
    result = await stop_scheduled_task.coroutine(runtime=_runtime(capability=capability, mode="scheduled"))
    assert result == {"stop_requested": True}
    capability.stop_current_schedule.assert_awaited_once_with()
    capability.manage.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "is_subagent"), [("interactive", False), ("webhook", False), ("autonomous", False), ("scheduled", True)])
async def test_self_stop_requires_a_scheduled_lead_run(mode, is_subagent):
    from deerflow.tools.scheduled_tasks import stop_scheduled_task

    capability = _capability("scheduled")
    result = await stop_scheduled_task.coroutine(runtime=_runtime(capability=capability, mode=mode, is_subagent=is_subagent))
    assert (result["code"], result["status_code"]) == ("scheduler_tools_disabled", 503)
    assert result["error"]
    capability.stop_current_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_self_stop_accepts_the_scheduler_legacy_non_interactive_policy():
    from deerflow.tools.scheduled_tasks import stop_scheduled_task

    capability = _capability("scheduled")
    runtime = _runtime(capability=capability)
    runtime.context.pop("interaction_mode")
    runtime.context["non_interactive"] = True
    result = await stop_scheduled_task.coroutine(runtime=runtime)
    assert result == {"stop_requested": True}


@pytest.mark.asyncio
async def test_missing_worker_config_cannot_fall_back_to_an_ambient_enabled_config():
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability()
    runtime = _runtime(capability=capability)
    runtime.context.pop("app_config")
    result = await schedule_task.coroutine(runtime=runtime, action="list")
    assert "error" in result
    capability.manage.assert_not_awaited()


def test_model_visible_schema_excludes_authority_and_self_stop_has_no_arguments():
    from deerflow.tools.scheduled_tasks import schedule_task, stop_scheduled_task

    management = schedule_task.tool_call_schema.model_json_schema()
    assert set(management["properties"]).isdisjoint({"runtime", "user_id", "thread_id", "run_id", "occurrence_id", "origin_thread_id", "assistant_id"})
    assert set(management["properties"]["action"]["enum"]) == {"create", "update", "list", "pause", "resume", "delete", "note", "trial"}
    assert {"stop_condition", "clear_fields"} <= set(management["properties"])
    assert stop_scheduled_task.tool_call_schema.model_json_schema()["properties"] == {}
    assert "explicit" in schedule_task.description.lower()
    assert "repeat the returned" not in schedule_task.description.lower()


def test_schedule_description_steers_the_conversation_contract():
    from deerflow.tools.scheduled_tasks import schedule_task, stop_scheduled_task

    description = " ".join(schedule_task.description.split())
    for phrase in (
        "stop_scheduled_task",
        "never tell the user a task cannot stop itself",
        "Never assume UTC",
        "never delete and recreate",
        "never promise to report back",
        "Intervals need no timezone",
    ):
        assert phrase in description
    assert "Repeat the returned" not in description
    assert "Run this task now" not in description
    assert "task paused itself" in " ".join(stop_scheduled_task.description.split())


def _constraint_keys(schema):
    found = set()
    if isinstance(schema, dict):
        found |= {key for key in schema if key in {"minimum", "exclusiveMinimum", "maximum", "maxLength", "minLength", "strict"}}
        for value in schema.values():
            found |= _constraint_keys(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _constraint_keys(value)
    return found


def test_model_visible_parameters_carry_no_value_constraints():
    from deerflow.tools.scheduled_tasks import schedule_task

    # Value rules come back as coded results (same codes as REST), never as a
    # schema rejection the model cannot read.
    assert _constraint_keys(schedule_task.tool_call_schema.model_json_schema()) == set()


@pytest.mark.asyncio
async def test_update_and_resume_forward_only_allowlisted_fields():
    from deerflow.tools.scheduled_tasks import schedule_task

    capability = _capability()
    await schedule_task.coroutine(
        runtime=_runtime(capability=capability),
        action="update",
        task_id="task-1",
        prompt="Check the checklist",
        stop_condition="every item is checked",
        schedule_type="cron",
        schedule_spec={"cron": "0 10 * * *"},
        clear_fields=["goal_objective", "max_runs"],
    )
    capability.manage.assert_awaited_once_with(
        action="update",
        request={"task_id": "task-1", "prompt": "Check the checklist", "stop_condition": "every item is checked", "schedule_type": "cron", "schedule_spec": {"cron": "0 10 * * *"}, "clear_fields": ["goal_objective", "max_runs"]},
    )
    capability.manage.reset_mock()
    await schedule_task.coroutine(runtime=_runtime(capability=capability), action="resume", task_id="task-1", max_runs=10)
    # context_mode is a create-only field; it is never forwarded to resume/update.
    capability.manage.assert_awaited_once_with(action="resume", request={"task_id": "task-1", "max_runs": 10})


@pytest.mark.parametrize(
    ("capability_mode", "interaction_mode", "is_subagent", "is_bootstrap", "expected"),
    [
        ("interactive", "interactive", False, False, True),
        ("scheduled", "scheduled", False, False, True),
        ("interactive", "scheduled", False, False, False),
        ("scheduled", "interactive", False, False, False),
        ("interactive", "webhook", False, False, False),
        ("interactive", "interactive", True, False, False),
        ("interactive", "interactive", False, True, False),
    ],
)
def test_lead_assembly_only_passes_a_host_capability_for_its_matching_mode(monkeypatch, capability_mode, interaction_mode, is_subagent, is_bootstrap, expected):
    import deerflow.tools as tools_module
    from deerflow.agents.lead_agent import agent as lead_agent_module

    config = _config()
    capability = _capability(capability_mode)
    assembly = MagicMock(return_value=[])
    monkeypatch.setattr(tools_module, "get_available_tools", assembly)
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "system prompt")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    lead_agent_module._make_lead_agent(
        {"context": {"__scheduler_capability": capability, "interaction_mode": interaction_mode, "is_subagent": is_subagent, "is_bootstrap": is_bootstrap}},
        app_config=config,
    )
    assert assembly.call_args.kwargs.get("scheduler_capability") is (capability if expected else None)


def test_lead_assembly_does_not_read_a_capability_from_checkpoint_configurable(monkeypatch):
    import deerflow.tools as tools_module
    from deerflow.agents.lead_agent import agent as lead_agent_module

    assembly = MagicMock(return_value=[])
    monkeypatch.setattr(tools_module, "get_available_tools", assembly)
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "system prompt")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    lead_agent_module._make_lead_agent({"configurable": {"__scheduler_capability": _capability()}}, app_config=_config())
    assert assembly.call_args.kwargs.get("scheduler_capability") is None
