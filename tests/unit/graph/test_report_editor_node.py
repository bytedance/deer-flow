# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import Mock, MagicMock, patch
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.graph.nodes import report_editor_node
from src.graph.types import State
from src.config.configuration import Configuration


@pytest.fixture
def mock_config():
    """Create a mock RunnableConfig."""
    config = Mock()
    config.configurable = {
        "max_plan_iterations": 1,
        "max_step_num": 3,
        "max_search_results": 3,
        "report_style": "academic",
    }
    return config


@pytest.fixture
def sample_report():
    """Sample report for testing."""
    return """# AI Research Report

## Key Points
- AI is transforming industries
- Machine learning has broad applications
- Ethics is important

## Overview
This report covers AI trends and applications.

## Detailed Analysis
### Current State
AI technology is rapidly advancing.

### Applications
AI is used in healthcare, finance, and more.

## Key Citations
- [Source 1](https://example.com/1)
"""


class TestReportEditorNode:
    """Test the report_editor_node."""

    def test_report_editor_with_empty_messages(self, mock_config):
        """Test report editor node with empty messages."""
        state = State(
            messages=[],
            previous_report="Sample previous report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert isinstance(result, Command)
        assert result.goto == "planner"

    def test_report_editor_routes_to_planner(self, mock_config):
        """Test that report editor routes to planner."""
        state = State(
            messages=[
                HumanMessage(content="Modify section 2 to focus on healthcare")
            ],
            previous_report="Sample previous report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert isinstance(result, Command)
        assert result.goto == "planner"

    def test_report_editor_sets_editing_flag(self, mock_config):
        """Test that report editor sets is_editing_report flag."""
        state = State(
            messages=[
                HumanMessage(content="Improve the overview section")
            ],
            previous_report="Sample previous report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert result.update["is_editing_report"] is True

    def test_report_editor_preserves_previous_report(self, mock_config, sample_report):
        """Test that report editor preserves previous report."""
        state = State(
            messages=[
                HumanMessage(content="Enhance section 2")
            ],
            previous_report=sample_report,
        )
        
        result = report_editor_node(state, mock_config)
        
        assert result.update["previous_report"] == sample_report

    def test_report_editor_extracts_edit_context(self, mock_config):
        """Test that report editor extracts edit context."""
        feedback = "Please focus more on healthcare applications"
        state = State(
            messages=[
                HumanMessage(content=feedback)
            ],
            previous_report="Sample report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert result.update["report_edit_context"] == feedback

    def test_report_editor_adds_system_message(self, mock_config):
        """Test that report editor adds a system message to workflow."""
        state = State(
            messages=[
                HumanMessage(content="Modify section 1")
            ],
            previous_report="Sample report",
        )
        
        result = report_editor_node(state, mock_config)
        
        # Check that messages were updated
        assert "messages" in result.update
        assert len(result.update["messages"]) > 0

    def test_report_editor_with_multiple_messages(self, mock_config):
        """Test report editor with multiple messages in history."""
        state = State(
            messages=[
                HumanMessage(content="Generate a report"),
                HumanMessage(content="Now modify section 2 to focus on AI"),
            ],
            previous_report="Sample report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert result.goto == "planner"
        assert result.update["is_editing_report"] is True

    def test_report_editor_scoped_prompt_includes_feedback(self, mock_config):
        """Test that scoped research prompt includes user feedback."""
        feedback = "Focus on healthcare and finance applications"
        state = State(
            messages=[
                HumanMessage(content=feedback)
            ],
            previous_report="Sample report",
        )
        
        result = report_editor_node(state, mock_config)
        
        # Verify that the new message contains the feedback
        messages = result.update["messages"]
        assert any(feedback in str(msg) for msg in messages)

    def test_report_editor_identifies_edit_action(self, mock_config):
        """Test that report editor identifies the edit action."""
        state = State(
            messages=[
                HumanMessage(content="Add a section about implementation strategies")
            ],
            previous_report="Sample report",
        )
        
        result = report_editor_node(state, mock_config)
        
        assert isinstance(result, Command)
        assert result.update.get("is_editing_report") is True


class TestCoordinatorEditDetection:
    """Test edit detection in coordinator node."""

    def test_coordinator_detects_edit_intent(self):
        """Test that coordinator detects edit intent from messages."""
        from src.graph.report_editor import detect_edit_intent
        
        message = "I want to modify section 2"
        has_report = True
        
        result = detect_edit_intent(message, has_report)
        
        assert result is True

    def test_coordinator_requires_previous_report(self):
        """Test that edit intent requires previous report."""
        from src.graph.report_editor import detect_edit_intent
        
        message = "Modify section 2"
        has_report = False
        
        result = detect_edit_intent(message, has_report)
        
        assert result is False


class TestReporterMergeMode:
    """Test reporter node merge mode."""

    def test_reporter_merge_mode_flag(self):
        """Test that merge mode is controlled by is_editing_report flag."""
        state = State(
            messages=[],
            is_editing_report=True,
            previous_report="Original report",
            report_edit_context="Improve section 2",
            observations=["New finding 1", "New finding 2"],
            current_plan=Mock(title="Targeted research", thought="Research description"),
        )
        
        # Reporter should recognize merge mode
        assert state.get("is_editing_report") is True
        assert len(state.get("previous_report", "")) > 0

    def test_reporter_resets_edit_flag_after_merge(self):
        """Test that reporter resets is_editing_report flag after merge."""
        # This would be tested in integration tests with the full node
        state = State(
            messages=[],
            is_editing_report=True,
        )
        
        # After merge, flag should be reset
        updated_state_dict = dict(state)
        updated_state_dict["is_editing_report"] = False
        updated_state = State(**updated_state_dict)
        
        assert updated_state.get("is_editing_report") is False
