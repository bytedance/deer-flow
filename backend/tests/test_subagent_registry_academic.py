"""Tests for academic subagent registration in the built-in registry."""

from src.subagents.builtins import BUILTIN_SUBAGENTS


def test_literature_reviewer_registered():
    assert "literature-reviewer" in BUILTIN_SUBAGENTS


def test_statistical_analyst_registered():
    assert "statistical-analyst" in BUILTIN_SUBAGENTS


def test_code_reviewer_registered():
    assert "code-reviewer" in BUILTIN_SUBAGENTS


def test_general_purpose_registered():
    assert "general-purpose" in BUILTIN_SUBAGENTS


def test_bash_registered():
    assert "bash" in BUILTIN_SUBAGENTS


def test_all_builtin_subagents_count():
    assert len(BUILTIN_SUBAGENTS) == 5


def test_all_subagents_have_valid_name():
    for name, config in BUILTIN_SUBAGENTS.items():
        assert config.name == name, f"Config name '{config.name}' does not match registry key '{name}'"


def test_all_subagents_have_description():
    for name, config in BUILTIN_SUBAGENTS.items():
        assert config.description, f"Subagent '{name}' has no description"
        assert len(config.description) > 10, f"Subagent '{name}' description is too short"


def test_all_subagents_have_system_prompt():
    for name, config in BUILTIN_SUBAGENTS.items():
        assert config.system_prompt, f"Subagent '{name}' has no system prompt"
        assert len(config.system_prompt) > 50, f"Subagent '{name}' system prompt is too short"


def test_all_subagents_have_valid_timeout():
    for name, config in BUILTIN_SUBAGENTS.items():
        assert config.timeout_seconds > 0, f"Subagent '{name}' has non-positive timeout"
        assert config.timeout_seconds <= 7200, f"Subagent '{name}' timeout exceeds 2 hours"


def test_literature_reviewer_config_details():
    config = BUILTIN_SUBAGENTS["literature-reviewer"]
    assert "literature" in config.description.lower() or "paper" in config.description.lower()
    prompt_lower = config.system_prompt.lower()
    assert "semantic scholar" in prompt_lower or "citation" in prompt_lower or "literature" in prompt_lower


def test_statistical_analyst_config_details():
    config = BUILTIN_SUBAGENTS["statistical-analyst"]
    assert "statistic" in config.description.lower() or "analysis" in config.description.lower()
    prompt_lower = config.system_prompt.lower()
    assert "statistic" in prompt_lower or "hypothesis" in prompt_lower or "apa" in prompt_lower


def test_code_reviewer_config_details():
    config = BUILTIN_SUBAGENTS["code-reviewer"]
    assert "code" in config.description.lower() or "review" in config.description.lower()
    prompt_lower = config.system_prompt.lower()
    assert "code" in prompt_lower or "review" in prompt_lower or "reproducib" in prompt_lower
