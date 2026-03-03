"""Tests for prompt composition: _build_subagent_section, _get_memory_context, get_skills_prompt_section, apply_prompt_template."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.lead_agent.prompt import (
    _build_subagent_section,
    _get_memory_context,
    apply_prompt_template,
    get_skills_prompt_section,
)


# ---------------------------------------------------------------------------
# _build_subagent_section
# ---------------------------------------------------------------------------
class TestBuildSubagentSection:
    """Tests for _build_subagent_section()."""

    def test_contains_max_concurrent_limit(self) -> None:
        result = _build_subagent_section(5)
        assert "MAXIMUM 5" in result
        assert "max 5" in result

    def test_contains_subagent_system_tags(self) -> None:
        result = _build_subagent_section(3)
        assert "<subagent_system>" in result
        assert "</subagent_system>" in result

    def test_default_limit_3(self) -> None:
        result = _build_subagent_section(3)
        assert "MAXIMUM 3 `task` CALLS PER RESPONSE" in result

    def test_different_limit(self) -> None:
        result = _build_subagent_section(10)
        assert "MAXIMUM 10 `task` CALLS PER RESPONSE" in result


# ---------------------------------------------------------------------------
# _get_memory_context
# ---------------------------------------------------------------------------
class TestGetMemoryContext:
    """Tests for _get_memory_context().

    Note: _get_memory_context uses lazy imports inside its body,
    so we must patch at the source module level.
    """

    def test_disabled_returns_empty(self) -> None:
        mock_config = MagicMock(enabled=False, injection_enabled=True)
        with patch("src.config.memory_config.get_memory_config", return_value=mock_config):
            assert _get_memory_context() == ""

    def test_injection_disabled_returns_empty(self) -> None:
        mock_config = MagicMock(enabled=True, injection_enabled=False)
        with patch("src.config.memory_config.get_memory_config", return_value=mock_config):
            assert _get_memory_context() == ""

    def test_returns_memory_block(self) -> None:
        mock_config = MagicMock(enabled=True, injection_enabled=True, max_injection_tokens=500)
        with patch("src.config.memory_config.get_memory_config", return_value=mock_config):
            with patch("src.agents.memory.get_memory_data", return_value={"facts": []}):
                with patch("src.agents.memory.format_memory_for_injection", return_value="User prefers dark mode."):
                    result = _get_memory_context()
                    assert "<memory>" in result
                    assert "User prefers dark mode." in result
                    assert "</memory>" in result

    def test_empty_memory_returns_empty(self) -> None:
        mock_config = MagicMock(enabled=True, injection_enabled=True, max_injection_tokens=500)
        with patch("src.config.memory_config.get_memory_config", return_value=mock_config):
            with patch("src.agents.memory.get_memory_data", return_value={}):
                with patch("src.agents.memory.format_memory_for_injection", return_value="   "):
                    assert _get_memory_context() == ""

    def test_exception_returns_empty(self) -> None:
        with patch("src.config.memory_config.get_memory_config", side_effect=RuntimeError("broken")):
            result = _get_memory_context()
            assert result == ""


# ---------------------------------------------------------------------------
# get_skills_prompt_section
# ---------------------------------------------------------------------------
class TestGetSkillsPromptSection:
    """Tests for get_skills_prompt_section().

    Note: load_skills is a top-level import from src.skills,
    and get_app_config is imported lazily inside the function.
    """

    @patch("src.agents.lead_agent.prompt.load_skills")
    def test_no_skills_returns_empty(self, mock_load) -> None:
        mock_load.return_value = []
        assert get_skills_prompt_section() == ""

    @patch("src.agents.lead_agent.prompt.load_skills")
    def test_with_skills_returns_block(self, mock_load) -> None:
        skill = MagicMock()
        skill.name = "deep-research"
        skill.description = "Research deeply"
        skill.get_container_file_path.return_value = "/mnt/skills/public/deep-research/SKILL.md"
        mock_load.return_value = [skill]

        with patch("src.config.app_config.get_app_config") as mock_config:
            mock_config.return_value = MagicMock(skills=MagicMock(container_path="/mnt/skills"))
            result = get_skills_prompt_section()
            assert "<skill_system>" in result
            assert "deep-research" in result
            assert "Research deeply" in result
            assert "</skill_system>" in result

    @patch("src.agents.lead_agent.prompt.load_skills")
    def test_config_error_uses_default_path(self, mock_load) -> None:
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "A test"
        skill.get_container_file_path.return_value = "/mnt/skills/test-skill/SKILL.md"
        mock_load.return_value = [skill]

        with patch("src.config.app_config.get_app_config", side_effect=RuntimeError("no config")):
            with patch("src.config.get_app_config", side_effect=RuntimeError("no config")):
                result = get_skills_prompt_section()
                assert "/mnt/skills" in result
                assert "test-skill" in result


# ---------------------------------------------------------------------------
# apply_prompt_template
# ---------------------------------------------------------------------------
class TestApplyPromptTemplate:
    """Tests for apply_prompt_template()."""

    @patch("src.agents.lead_agent.prompt._composer")
    @patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="")
    @patch("src.agents.lead_agent.prompt._get_memory_context", return_value="")
    def test_no_subagent(self, mock_mem, mock_skills, mock_composer) -> None:
        mock_composer.compose.return_value = "system prompt"
        result = apply_prompt_template(subagent_enabled=False)
        assert result == "system prompt"
        call_kwargs = mock_composer.compose.call_args[1]
        assert call_kwargs["subagent_section"] == ""
        assert call_kwargs["subagent_reminder"] == ""
        assert call_kwargs["subagent_thinking"] == ""

    @patch("src.agents.lead_agent.prompt._composer")
    @patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="")
    @patch("src.agents.lead_agent.prompt._get_memory_context", return_value="")
    def test_with_subagent(self, mock_mem, mock_skills, mock_composer) -> None:
        mock_composer.compose.return_value = "prompt"
        apply_prompt_template(subagent_enabled=True, max_concurrent_subagents=5)
        call_kwargs = mock_composer.compose.call_args[1]
        assert "<subagent_system>" in call_kwargs["subagent_section"]
        assert "MAXIMUM 5" in call_kwargs["subagent_section"]
        assert "max 5" in call_kwargs["subagent_reminder"]
        assert "DECOMPOSITION CHECK" in call_kwargs["subagent_thinking"]

    @patch("src.agents.lead_agent.prompt._composer")
    @patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="<skill_system>test</skill_system>")
    @patch("src.agents.lead_agent.prompt._get_memory_context", return_value="<memory>facts</memory>")
    def test_passes_memory_and_skills(self, mock_mem, mock_skills, mock_composer) -> None:
        mock_composer.compose.return_value = "full prompt"
        apply_prompt_template()
        call_kwargs = mock_composer.compose.call_args[1]
        assert call_kwargs["memory_context"] == "<memory>facts</memory>"
        assert call_kwargs["skills_section"] == "<skill_system>test</skill_system>"

    @patch("src.agents.lead_agent.prompt._composer")
    @patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="")
    @patch("src.agents.lead_agent.prompt._get_memory_context", return_value="")
    def test_passes_tool_policies(self, mock_mem, mock_skills, mock_composer) -> None:
        mock_composer.compose.return_value = "prompt"
        apply_prompt_template(tool_policies="<policies>be safe</policies>")
        call_kwargs = mock_composer.compose.call_args[1]
        assert call_kwargs["tool_policies"] == "<policies>be safe</policies>"

    @patch("src.agents.lead_agent.prompt._composer")
    @patch("src.agents.lead_agent.prompt.get_skills_prompt_section", return_value="")
    @patch("src.agents.lead_agent.prompt._get_memory_context", return_value="")
    def test_passes_current_date(self, mock_mem, mock_skills, mock_composer) -> None:
        mock_composer.compose.return_value = "prompt"
        apply_prompt_template()
        call_kwargs = mock_composer.compose.call_args[1]
        assert "current_date" in call_kwargs
        assert len(call_kwargs["current_date"]) > 8
