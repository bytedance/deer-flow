"""Reject ambiguous output budgets before they reach the runtime middleware."""

from types import SimpleNamespace

import pytest
import yaml
from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.tool_output_config import ToolOutputConfig

LIMIT_FIELDS = (
    "externalize_min_chars",
    "preview_head_chars",
    "preview_tail_chars",
    "fallback_max_chars",
    "fallback_head_chars",
    "fallback_tail_chars",
    "superseded_write_min_chars",
    "keep_recent_writes",
)


@pytest.mark.parametrize("field", LIMIT_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_boolean_limits_fail_at_the_field(field, value):
    with pytest.raises(ValidationError) as exc:
        ToolOutputConfig.model_validate({field: value})

    assert exc.value.errors()[0]["loc"] == (field,)
    assert "boolean" in exc.value.errors()[0]["msg"]


@pytest.mark.parametrize("value", [True, False, -1, "-1"])
def test_invalid_override_identifies_the_tool(value):
    with pytest.raises(ValidationError) as exc:
        ToolOutputConfig(tool_overrides={"web_fetch": value, "bash": 500})

    assert exc.value.errors()[0]["loc"] == ("tool_overrides", "web_fetch")


@pytest.mark.parametrize("field", LIMIT_FIELDS)
@pytest.mark.parametrize("value", [0, 120, "120", 120.0])
def test_existing_numeric_inputs_remain_supported(field, value):
    config = ToolOutputConfig.model_validate({field: value})

    assert getattr(config, field) == int(value)
    assert type(getattr(config, field)) is int


@pytest.mark.parametrize("value", [1.5, "not-a-number", None])
def test_overrides_reject_other_invalid_integer_budgets(value):
    with pytest.raises(ValidationError) as exc:
        ToolOutputConfig(tool_overrides={"web_fetch": value})

    assert exc.value.errors()[0]["loc"] == ("tool_overrides", "web_fetch")


@pytest.mark.parametrize("section", [{"fallback_max_chars": True}, {"tool_overrides": {"web_fetch": False}}])
def test_yaml_loading_rejects_boolean_budgets(tmp_path, section):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"sandbox": {"use": "test"}, "tool_output": section}), encoding="utf-8")

    with pytest.raises(ValidationError) as exc:
        AppConfig.from_file(path)

    assert exc.value.errors()[0]["loc"][0] == "tool_output"
    assert "boolean" in exc.value.errors()[0]["msg"]


def test_environment_numeric_strings_and_switches_remain_supported(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_LIMIT", "180")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "test"},
                "tool_output": {
                    "enabled": True,
                    "elide_superseded_writes": False,
                    "externalize_min_chars": "$OUTPUT_LIMIT",
                    "tool_overrides": {"web_fetch": "$OUTPUT_LIMIT", "bash": 0},
                },
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig.from_file(path).tool_output

    assert config.externalize_min_chars == 180
    assert config.tool_overrides == {"web_fetch": 180, "bash": 0}
    assert config.enabled is True
    assert config.elide_superseded_writes is False


@pytest.mark.parametrize("override", [0, "0", 100, "100"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_valid_override_controls_real_output_budgeting(tmp_path, override, asynchronous):
    content = "evidence line\n" * 100
    message = ToolMessage(content=content, name="web_fetch", tool_call_id="call-1")
    request = SimpleNamespace(
        tool_call={"name": "web_fetch", "id": "call-1"},
        runtime=SimpleNamespace(state={"thread_data": {"outputs_path": str(tmp_path)}}),
    )
    config = ToolOutputConfig(
        externalize_min_chars=10_000,
        fallback_max_chars=200,
        fallback_head_chars=60,
        fallback_tail_chars=40,
        tool_overrides={"web_fetch": override},
    )
    middleware = ToolOutputBudgetMiddleware(config)
    calls = []

    def handler(actual_request):
        calls.append(actual_request)
        return message

    async def async_handler(actual_request):
        return handler(actual_request)

    if asynchronous:
        result = await middleware.awrap_tool_call(request, async_handler)
    else:
        result = middleware.wrap_tool_call(request, handler)

    assert calls == [request]
    assert message.content == content
    assert result.tool_call_id == message.tool_call_id
    assert result.content != content
    stored = [path for path in tmp_path.rglob("*") if path.is_file()]
    if int(override) == 0:
        assert stored == []
        assert "chars omitted" in result.content
    else:
        assert len(stored) == 1
        assert stored[0].read_text(encoding="utf-8") == content


def test_zero_override_and_zero_fallback_leave_output_unchanged(tmp_path):
    message = ToolMessage(content="evidence" * 200, name="web_fetch", tool_call_id="call-1")
    request = SimpleNamespace(
        tool_call={"name": "web_fetch", "id": "call-1"},
        runtime=SimpleNamespace(state={"thread_data": {"outputs_path": str(tmp_path)}}),
    )
    middleware = ToolOutputBudgetMiddleware(ToolOutputConfig(tool_overrides={"web_fetch": 0}, fallback_max_chars=0))

    result = middleware.wrap_tool_call(request, lambda _: message)

    assert result is message
    assert list(tmp_path.iterdir()) == []
