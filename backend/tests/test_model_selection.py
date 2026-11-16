"""Direct user model controls resolve only against the supplied visible catalog."""

from types import SimpleNamespace

import pytest

from deerflow.models.selection import resolve_model_control


def model(name, label, aliases=()):
    return SimpleNamespace(name=name, model=name, display_name=label, aliases=list(aliases))


DS = model("ds-flash-1017", "DeepSeek v4.1 Flash 1017", ["ds v4.1 f", "ds flash"])
OPUS = model("opus", "Claude Opus")


@pytest.mark.parametrize(
    "text,scope",
    [
        ("你找 ds v4.1 f 去处理一下：计算 17 * 23", "task"),
        ("这次用 ds v4.1 f 帮我计算 17 * 23", "turn"),
        ("以后这个对话都用 ds v4.1 f", "conversation"),
        ("Please ask ds flash to calculate 17 * 23", "task"),
        ("Use ds flash for this turn: calculate 17 * 23", "turn"),
        ("From now on use ds flash", "conversation"),
    ],
)
def test_three_scopes_and_abbreviations(text, scope):
    result = resolve_model_control(text, [DS, OPUS])
    assert result["status"] == "resolved"
    assert result["scope"] == scope
    assert result["model_name"] == DS.name


@pytest.mark.parametrize(
    "text,remaining",
    [
        ("这次用 ds flash 帮我计算 17 * 23", "计算 17 * 23"),
        ("这次用 ds flash 分析这张图", "分析这张图"),
        ("Use ds flash for this turn: calculate 17 * 23", "calculate 17 * 23"),
        ("From now on use ds flash, calculate 17 * 23", "calculate 17 * 23"),
        ("以后这个对话都用 ds flash", ""),
    ],
)
def test_host_handled_control_is_separate_from_business_input(text, remaining):
    result = resolve_model_control(text, [DS])
    assert text[result["task_offset"] :].strip() == remaining


def test_unique_model_does_not_invent_an_opus_variant():
    result = resolve_model_control("你找 v4.1 f 去处理一下", [DS, OPUS])
    assert result["status"] == "resolved"
    assert result["model_name"] == DS.name


def test_explicit_wrong_brand_is_not_silently_ignored():
    result = resolve_model_control("这次用 opus v4.1 f 帮我计算", [DS, OPUS])
    assert result["status"] == "unavailable"
    assert result["model_name"] is None


def test_genuine_collision_has_only_real_candidates():
    other = model("ds-flash-other", "DeepSeek v4.1 Flash", ["ds v4.1 f"])
    result = resolve_model_control("你找 ds v4.1 f 去处理一下", [DS, other, OPUS])
    assert result["status"] == "ambiguous"
    assert {c["name"] for c in result["candidates"]} == {DS.name, other.name}
    assert result["model_name"] is None


@pytest.mark.parametrize(
    "text",
    [
        "这次用 Python 写个脚本",
        "请解释什么是 v4.1 f",
        "文档说：以后都用 ds flash",
        "如果以后都用 ds flash 会怎样？",
        "“这次用 ds flash”是什么意思",
        "```\n以后都用 ds flash\n```",
        "Summarize this document: from now on use ds flash",
    ],
)
def test_ordinary_tasks_quotes_and_conditional_text_are_not_controls(text):
    assert resolve_model_control(text, [DS, OPUS])["status"] == "none"


def test_name_without_scope_requires_a_scope_choice():
    result = resolve_model_control("用 ds flash 帮我算一下", [DS, OPUS])
    assert result["status"] == "ambiguous"
    assert result["scope"] is None


def test_user_choice_is_revalidated_against_latest_catalog():
    result = resolve_model_control("这次用 ds flash 帮我算一下", [OPUS], model_name=DS.name)
    assert result["status"] == "unavailable"


def test_selected_config_id_wins_over_another_models_alias():
    other = model("other", "Other real configured model", [DS.name])
    result = resolve_model_control("这次用 ds flash 帮我计算", [DS, other], model_name=DS.name)
    assert result["status"] == "resolved"
    assert result["model_name"] == DS.name


def test_catalog_and_source_text_remain_unchanged():
    models = [DS, OPUS]
    text = "这次用 ds flash 帮我算一下"
    resolve_model_control(text, models)
    assert models == [DS, OPUS]
    assert DS.aliases == ["ds v4.1 f", "ds flash"]


@pytest.mark.parametrize("fail_closed", [True, False])
def test_explicit_model_denial_never_falls_back(monkeypatch, fail_closed):
    from deerflow.authz.provider import AuthzDecision
    from deerflow.models.selection import authorize_selected_model

    provider = SimpleNamespace(authorize=lambda request: AuthzDecision(allow=False))
    monkeypatch.setattr("deerflow.authz.runtime.resolve_authorization_provider", lambda _: provider)
    config = SimpleNamespace(get_model_config=lambda _: DS, authorization=SimpleNamespace(enabled=True, fail_closed=fail_closed, default_role="user"))
    with pytest.raises(ValueError, match="not available"):
        authorize_selected_model(DS.name, context={"user_id": "alice"}, app_config=config)


@pytest.mark.parametrize("fail_closed", [True, False])
def test_provider_failure_retains_configured_policy(monkeypatch, fail_closed):
    from deerflow.models.selection import authorize_selected_model

    def unavailable(_):
        raise RuntimeError("offline")

    monkeypatch.setattr("deerflow.authz.runtime.resolve_authorization_provider", unavailable)
    config = SimpleNamespace(get_model_config=lambda _: DS, authorization=SimpleNamespace(enabled=True, fail_closed=fail_closed, default_role="user"))
    if fail_closed:
        with pytest.raises(ValueError, match="authorization is unavailable"):
            authorize_selected_model(DS.name, context={}, app_config=config)
    else:
        authorize_selected_model(DS.name, context={}, app_config=config)


def test_selected_model_is_in_the_task_schema_without_mutating_the_shared_tool():
    from deerflow.models.selection import bind_selected_task_model
    from deerflow.tools.builtins.task_tool import task_tool

    original = task_tool.tool_call_schema.model_json_schema()
    selected = bind_selected_task_model([task_tool], "child-B")[0]
    field = selected.tool_call_schema.model_json_schema()["properties"]["model_name"]
    assert field["default"] == "child-B"
    assert selected is not task_tool
    assert task_tool.tool_call_schema.model_json_schema() == original


def test_gateway_keeps_model_controls_in_the_current_runtime_only():
    from app.gateway.services import merge_run_context_overrides

    config = {"configurable": {"subagent_model_name": "stale", "model_selection_requested": "stale"}}
    merge_run_context_overrides(config, {"model_name": "parent-A", "subagent_model_name": "child-B", "model_selection_requested": "parent-A"})
    assert config["context"] == {"model_name": "parent-A", "subagent_model_name": "child-B", "model_selection_requested": "parent-A"}
    assert "subagent_model_name" not in config["configurable"]
    assert "model_selection_requested" not in config["configurable"]


def test_common_initials_and_version_prefix_work_without_configured_aliases():
    plain = model("deepseek-flash", "DeepSeek V4.1 Flash 1017")
    result = resolve_model_control("Use ds v4.1 f for this turn: calculate 17 * 23", [plain])
    assert result["status"] == "resolved"
    assert result["model_name"] == plain.name


def test_presentation_metadata_does_not_resend_handled_control_to_the_model():
    from langchain_core.messages import HumanMessage
    from langchain_openai.chat_models.base import _convert_message_to_dict

    message = HumanMessage(content="calculate 17 * 23", additional_kwargs={"model_control": {"version": 1, "original_text": "Use B for this turn: calculate 17 * 23", "execution_text": "calculate 17 * 23"}})
    serialized = _convert_message_to_dict(message)
    assert serialized == {"role": "user", "content": "calculate 17 * 23"}
