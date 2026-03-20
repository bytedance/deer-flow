"""Tests for plugin command system prompt injection."""

from src.plugins.prompt import build_commands_prompt_section
from src.plugins.types import Command


class TestBuildCommandsPromptSection:
    """Tests for generating the command system prompt section."""

    def test_empty_commands(self):
        """Should return empty string when no commands."""
        result = build_commands_prompt_section([])
        assert result == ""

    def test_single_command(self):
        """Should generate XML section for a single command."""
        commands = [
            Command(
                name="forecast",
                description="Generate a sales forecast",
                argument_hint="<period>",
                content="# Forecast\n\nGenerate a forecast.",
                plugin_name="sales",
            ),
        ]

        result = build_commands_prompt_section(commands)

        assert "<command_system>" in result
        assert "</command_system>" in result
        assert "<available_commands>" in result
        assert "sales:forecast" in result
        assert "Generate a sales forecast" in result
        assert "<period>" in result

    def test_multiple_commands_from_different_plugins(self):
        """Should list commands from multiple plugins."""
        commands = [
            Command(name="forecast", description="Forecast", argument_hint="<period>", content="Body", plugin_name="sales"),
            Command(name="query", description="Query data", argument_hint="<sql>", content="Body", plugin_name="data"),
        ]

        result = build_commands_prompt_section(commands)

        assert "sales:forecast" in result
        assert "data:query" in result

    def test_command_xml_structure(self):
        """Should have correct XML structure for each command."""
        commands = [
            Command(name="forecast", description="Forecast", argument_hint="<period>", content="Body", plugin_name="sales"),
        ]

        result = build_commands_prompt_section(commands)

        assert "<command>" in result
        assert "<name>" in result
        assert "<description>" in result
        assert "<usage>" in result
        assert "</command>" in result
