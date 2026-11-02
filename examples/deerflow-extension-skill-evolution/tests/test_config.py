import pytest

from deerflow_extension_skill_evolution.config import (
    FEEDBACK_MODE_AGENT,
    FEEDBACK_MODE_DRAFT,
    SCOPE_LEAD,
    SCOPE_LEAD_AND_SUBAGENT,
    SkillEvolutionSettings,
    parse_config,
)


def test_defaults_match_legacy_core_policy() -> None:
    settings = parse_config({})
    assert settings == SkillEvolutionSettings()
    assert settings.min_tool_calls_hint == 5
    assert settings.prefer_patch is True
    assert settings.confirm_before_create is True
    assert settings.scope == SCOPE_LEAD
    assert settings.includes_subagents is False
    # Annotation-driven evolution defaults to the offline draft shape (Plan A).
    assert settings.feedback_mode == FEEDBACK_MODE_DRAFT


def test_full_valid_config_round_trips() -> None:
    settings = parse_config(
        {
            "min_tool_calls_hint": 8,
            "prefer_patch": False,
            "confirm_before_create": False,
            "scope": SCOPE_LEAD_AND_SUBAGENT,
            "feedback_mode": FEEDBACK_MODE_AGENT,
        }
    )
    assert settings.min_tool_calls_hint == 8
    assert settings.prefer_patch is False
    assert settings.confirm_before_create is False
    assert settings.includes_subagents is True
    assert settings.feedback_mode == FEEDBACK_MODE_AGENT


def test_unknown_keys_are_rejected_with_guidance() -> None:
    with pytest.raises(ValueError, match="Unknown skill-evolution config key") as exc_info:
        parse_config({"enabled": True, "min_tool_calls_hint": 5})
    assert "enabled" in str(exc_info.value)


def test_bool_is_not_accepted_as_int_hint() -> None:
    with pytest.raises(ValueError, match="min_tool_calls_hint"):
        parse_config({"min_tool_calls_hint": True})


@pytest.mark.parametrize("value", [0, -1, 101, "5", 5.5, None])
def test_tool_call_hint_range_and_type(value) -> None:
    with pytest.raises(ValueError, match="min_tool_calls_hint"):
        parse_config({"min_tool_calls_hint": value})


@pytest.mark.parametrize("key", ["prefer_patch", "confirm_before_create"])
def test_boolean_fields_reject_non_bools(key) -> None:
    with pytest.raises(ValueError, match=key):
        parse_config({key: 1})
    with pytest.raises(ValueError, match=key):
        parse_config({key: "true"})


def test_scope_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="scope"):
        parse_config({"scope": "subagent"})
    with pytest.raises(ValueError, match="scope"):
        parse_config({"scope": 1})


def test_feedback_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="feedback_mode"):
        parse_config({"feedback_mode": "always"})
    with pytest.raises(ValueError, match="feedback_mode"):
        parse_config({"feedback_mode": True})


def test_settings_are_frozen() -> None:
    settings = parse_config({})
    with pytest.raises(AttributeError):
        settings.min_tool_calls_hint = 7  # type: ignore[misc]
