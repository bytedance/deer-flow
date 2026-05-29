"""Integration tests for pilot agent configuration (Phase 1.11.2-1.11.3).

Covers:
- monitoring-analysis agent receives integration tools + data_sources prompt section
- ai-report--daily agent (no data_tools) remains unchanged
- Prompt scoping integration with agent factory
"""

import pytest
from unittest.mock import MagicMock, patch

from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.config.agents_config import load_agent_config


# ---------------------------------------------------------------------------
# Pilot Agent Configuration Tests (1.11.2-1.11.3)
# ---------------------------------------------------------------------------


class TestMonitoringAnalysisAgentConfig:
    """Test monitoring-analysis agent receives integration tools and prompt section."""

    def test_monitoring_analysis_has_data_tools(self):
        """monitoring-analysis agent config includes data_tools field."""
        agent_config = load_agent_config("monitoring-analysis")

        assert agent_config is not None
        assert agent_config.name == "monitoring-analysis"
        assert agent_config.data_tools is not None
        assert isinstance(agent_config.data_tools, list)
        assert len(agent_config.data_tools) > 0

    def test_monitoring_analysis_data_tools_includes_equipment_overview(self):
        """monitoring-analysis data_tools includes equipment_get_overview."""
        agent_config = load_agent_config("monitoring-analysis")

        assert "equipment_get_overview" in agent_config.data_tools

    def test_monitoring_analysis_data_tools_includes_monitoring_tools(self):
        """monitoring-analysis data_tools includes monitoring tools."""
        agent_config = load_agent_config("monitoring-analysis")

        expected_tools = [
            "monitoring_get_trend",
            "monitoring_get_waveform",
            "monitoring_get_alarm_history",
        ]
        for tool in expected_tools:
            assert tool in agent_config.data_tools, f"Missing tool: {tool}"

    def test_monitoring_analysis_prompt_includes_data_sources_section(self):
        """monitoring-analysis prompt includes <data_sources> section."""
        agent_config = load_agent_config("monitoring-analysis")

        prompt = apply_prompt_template(
            agent_name=agent_config.name,
            data_tools=agent_config.data_tools,
        )

        assert "<data_sources>" in prompt
        assert "</data_sources>" in prompt
        assert "equipment_get_overview" in prompt
        assert "monitoring_get_trend" in prompt

    def test_monitoring_analysis_prompt_describes_all_data_tools(self):
        """monitoring-analysis prompt describes each configured data tool."""
        agent_config = load_agent_config("monitoring-analysis")

        prompt = apply_prompt_template(
            agent_name=agent_config.name,
            data_tools=agent_config.data_tools,
        )

        # Check that each data_tool is mentioned in the prompt
        for tool_name in agent_config.data_tools:
            assert tool_name in prompt, f"Tool {tool_name} not in prompt"


class TestAIReportDailyAgentConfig:
    """Test ai-report--daily agent (no data_tools) remains unchanged."""

    def test_ai_report_daily_has_no_data_tools(self):
        """ai-report--daily agent config has no data_tools field or it's None/empty."""
        agent_config = load_agent_config("ai-report--daily")

        # data_tools should be None or empty list
        assert agent_config is not None
        assert agent_config.data_tools is None or len(agent_config.data_tools) == 0

    def test_ai_report_daily_prompt_has_no_data_sources_section(self):
        """ai-report--daily prompt does not include <data_sources> section."""
        agent_config = load_agent_config("ai-report--daily")

        prompt = apply_prompt_template(
            agent_name=agent_config.name,
            data_tools=agent_config.data_tools,
        )

        assert "<data_sources>" not in prompt
        assert "</data_sources>" not in prompt
        assert "equipment_get_overview" not in prompt

    def test_ai_report_daily_prompt_still_has_other_sections(self):
        """ai-report--daily prompt still includes other standard sections."""
        agent_config = load_agent_config("ai-report--daily")

        prompt = apply_prompt_template(
            agent_name=agent_config.name,
            data_tools=agent_config.data_tools,
        )

        # Should still have basic prompt structure
        assert "EHM AI" in prompt or "工作台" in prompt
        assert "<current_date>" in prompt


class TestDataToolsPromptScoping:
    """Test prompt scoping with different data_tools configurations."""

    def test_none_data_tools_produces_no_section(self):
        """None data_tools produces no data_sources section."""
        prompt = apply_prompt_template(
            agent_name="test-agent",
            data_tools=None,
        )

        assert "<data_sources>" not in prompt

    def test_empty_list_data_tools_produces_no_section(self):
        """Empty list data_tools produces no data_sources section."""
        prompt = apply_prompt_template(
            agent_name="test-agent",
            data_tools=[],
        )

        assert "<data_sources>" not in prompt

    def test_single_tool_produces_minimal_section(self):
        """Single data tool produces minimal data_sources section."""
        prompt = apply_prompt_template(
            agent_name="test-agent",
            data_tools=["equipment_get_overview"],
        )

        assert "<data_sources>" in prompt
        assert "equipment_get_overview" in prompt
        assert "monitoring_get_trend" not in prompt

    def test_wildcard_includes_all_tools(self):
        """Wildcard '*' includes all data tools in prompt."""
        prompt = apply_prompt_template(
            agent_name="test-agent",
            data_tools=["*"],
        )

        assert "<data_sources>" in prompt
        assert "equipment_get_overview" in prompt
        assert "monitoring_get_trend" in prompt
        assert "health_get_assessment" in prompt
        assert "asset_get_catalog" in prompt

    def test_group_wildcard_includes_group_only(self):
        """Group wildcard 'monitoring.*' includes only monitoring tools."""
        prompt = apply_prompt_template(
            agent_name="test-agent",
            data_tools=["monitoring.*"],
        )

        assert "<data_sources>" in prompt
        assert "monitoring_get_trend" in prompt
        assert "monitoring_get_waveform" in prompt
        assert "- **equipment_get_overview**" not in prompt
        assert "- **health_get_assessment**" not in prompt


class TestAgentConfigDataToolsField:
    """Test AgentConfig data_tools field handling."""

    def test_agent_config_with_data_tools(self):
        """AgentConfig correctly stores data_tools list."""
        from deerflow.config.agents_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            display_name="Test Agent",
            description="Test",
            icon="🧪",
            tool_groups=["bash"],
            skills=[],
            data_tools=["equipment_get_overview", "monitoring_get_trend"],
        )

        assert config.data_tools == ["equipment_get_overview", "monitoring_get_trend"]

    def test_agent_config_without_data_tools(self):
        """AgentConfig defaults data_tools to None."""
        from deerflow.config.agents_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            display_name="Test Agent",
            description="Test",
            icon="🧪",
            tool_groups=["bash"],
            skills=[],
        )

        assert config.data_tools is None

    def test_agent_config_to_agent_info_preserves_data_tools(self):
        """to_agent_info() preserves data_tools field."""
        from deerflow.config.agents_config import AgentConfig, to_agent_info

        config = AgentConfig(
            name="test-agent",
            display_name="Test Agent",
            description="Test",
            icon="🧪",
            tool_groups=["bash"],
            skills=[],
            data_tools=["equipment_get_overview"],
        )

        info = to_agent_info(config)
        assert info.data_tools == ["equipment_get_overview"]
