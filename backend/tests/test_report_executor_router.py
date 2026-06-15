"""Tests for report executor router."""


from deerflow.report_executor.router import (
    get_executor_type_from_config,
    get_report_tools_for_agent,
    is_direct_executor_agent,
)


class MockAgentConfig:
    """Mock agent config for testing."""

    def __init__(self, executor_type=None):
        self.executor_type = executor_type


class TestReportExecutorRouter:
    """Test suite for report executor routing logic."""

    def test_is_direct_executor_agent_with_direct(self):
        """Test that agent with executor_type='direct' is recognized."""
        config = MockAgentConfig(executor_type="direct")
        assert is_direct_executor_agent(config) is True

    def test_is_direct_executor_agent_with_dsl(self):
        """Test that agent with executor_type='dsl' is not direct."""
        config = MockAgentConfig(executor_type="dsl")
        assert is_direct_executor_agent(config) is False

    def test_is_direct_executor_agent_with_none(self):
        """Test that agent with executor_type=None is not direct."""
        config = MockAgentConfig(executor_type=None)
        assert is_direct_executor_agent(config) is False

    def test_is_direct_executor_agent_none_config(self):
        """Test that None config is not direct."""
        assert is_direct_executor_agent(None) is False

    def test_get_executor_type_from_config_direct(self):
        """Test that direct executor_type is extracted correctly."""
        config = MockAgentConfig(executor_type="direct")
        assert get_executor_type_from_config(config) == "direct"

    def test_get_executor_type_from_config_dsl(self):
        """Test that dsl executor_type is extracted correctly."""
        config = MockAgentConfig(executor_type="dsl")
        assert get_executor_type_from_config(config) == "dsl"

    def test_get_executor_type_from_config_none(self):
        """Test that None executor_type defaults to dsl."""
        config = MockAgentConfig(executor_type=None)
        assert get_executor_type_from_config(config) == "dsl"

    def test_get_executor_type_from_config_none_config(self):
        """Test that None config defaults to dsl."""
        assert get_executor_type_from_config(None) == "dsl"

    def test_get_executor_type_from_config_dict(self):
        """Test that dict config is handled correctly."""
        config = {"executor_type": "direct"}
        assert get_executor_type_from_config(config) == "direct"

    def test_get_report_tools_for_agent_direct(self):
        """Test that direct executor agents get direct execution tools."""
        config = MockAgentConfig(executor_type="direct")
        tools = get_report_tools_for_agent(config)
        assert len(tools) == 1
        assert tools[0].name == "report_direct_execute"

    def test_get_report_tools_for_agent_dsl(self):
        """Test that dsl executor agents get DSL template tools."""
        config = MockAgentConfig(executor_type="dsl")
        tools = get_report_tools_for_agent(config)
        # Should include lifecycle tools, runtime tools, and fallback tool
        assert len(tools) > 1
        tool_names = [t.name for t in tools]
        # Check that DSL tools are present
        assert "report_template_prepare_run" in tool_names
        assert "report_template_render_step" in tool_names
        assert "report_template_submit_step" in tool_names
        # Check that direct execute is NOT present
        assert "report_direct_execute" not in tool_names

    def test_get_report_tools_for_agent_none_config(self):
        """Test that None config gets DSL template tools."""
        tools = get_report_tools_for_agent(None)
        # Should include lifecycle tools, runtime tools, and fallback tool
        assert len(tools) > 1
        tool_names = [t.name for t in tools]
        assert "report_template_prepare_run" in tool_names
        assert "report_direct_execute" not in tool_names
