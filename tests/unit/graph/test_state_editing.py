# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from src.graph.types import State


class TestStateWithEditingFields:
    """Test State class with new report editing fields."""

    def test_state_has_previous_report_field(self):
        """Test that State can store previous_report field."""
        state = State(messages=[], previous_report="test")
        assert "previous_report" in state
        assert state.get("previous_report") == "test"

    def test_state_has_is_editing_report_field(self):
        """Test that State can store is_editing_report field."""
        state = State(messages=[], is_editing_report=True)
        assert "is_editing_report" in state
        assert state.get("is_editing_report") is True

    def test_state_has_report_edit_context_field(self):
        """Test that State can store report_edit_context field."""
        state = State(messages=[], report_edit_context="test context")
        assert "report_edit_context" in state
        assert state.get("report_edit_context") == "test context"

    def test_state_has_report_sections_to_edit_field(self):
        """Test that State can store report_sections_to_edit field."""
        state = State(messages=[], report_sections_to_edit=["section_1"])
        assert "report_sections_to_edit" in state
        assert isinstance(state.get("report_sections_to_edit", []), list)
        assert len(state.get("report_sections_to_edit", [])) == 1

    def test_state_initialization_with_previous_report(self):
        """Test state initialization with previous_report."""
        report = "Sample report content"
        state = State(
            messages=[],
            previous_report=report,
        )
        
        assert state.get("previous_report") == report

    def test_state_initialization_with_editing_flag(self):
        """Test state initialization with is_editing_report."""
        state = State(
            messages=[],
            is_editing_report=True,
        )
        
        assert state.get("is_editing_report") is True

    def test_state_initialization_with_edit_context(self):
        """Test state initialization with report_edit_context."""
        context = "User wants to improve section 2"
        state = State(
            messages=[],
            report_edit_context=context,
        )
        
        assert state.get("report_edit_context") == context

    def test_state_initialization_with_sections_to_edit(self):
        """Test state initialization with report_sections_to_edit."""
        sections = ["section_1", "section_2", "section_3"]
        state = State(
            messages=[],
            report_sections_to_edit=sections,
        )
        
        assert state.get("report_sections_to_edit") == sections

    def test_state_full_editing_initialization(self):
        """Test state initialization with all editing fields."""
        report = "Original report"
        context = "Improve section 2"
        sections = ["section_2"]
        
        state = State(
            messages=[],
            previous_report=report,
            is_editing_report=True,
            report_edit_context=context,
            report_sections_to_edit=sections,
        )
        
        assert state.get("previous_report") == report
        assert state.get("is_editing_report") is True
        assert state.get("report_edit_context") == context
        assert state.get("report_sections_to_edit") == sections

    def test_state_editing_fields_default_values(self):
        """Test that editing fields can use defaults."""
        state = State(messages=[])
        
        assert state.get("previous_report", "") == ""
        assert state.get("is_editing_report", False) is False
        assert state.get("report_edit_context", "") == ""
        assert state.get("report_sections_to_edit", []) == []

    def test_state_maintains_other_fields(self):
        """Test that existing State fields are not affected."""
        state = State(
            messages=[],
            locale="en-US",
            research_topic="AI trends",
            final_report="Generated report",
            is_editing_report=True,
        )
        
        # Verify new fields
        assert state.get("is_editing_report") is True
        
        # Verify existing fields still work
        assert state.get("locale") == "en-US"
        assert state.get("research_topic") == "AI trends"
        assert state.get("final_report") == "Generated report"

    def test_state_editing_workflow_sequence(self):
        """Test typical state transitions in editing workflow."""
        # Step 1: Initial report generation
        state1 = State(
            messages=[],
            final_report="Generated report content",
            is_editing_report=False,
        )
        
        assert state1.get("is_editing_report") is False
        assert len(state1.get("final_report", "")) > 0
        assert state1.get("previous_report", "") == ""
        
        # Step 2: User requests edit
        state2 = State(
            messages=state1.get("messages", []),
            previous_report=state1.get("final_report", ""),
            is_editing_report=True,
            report_edit_context="Modify section 2",
            report_sections_to_edit=["section_2"],
        )
        
        assert state2.get("is_editing_report") is True
        assert state2.get("previous_report") == state1.get("final_report", "")
        assert len(state2.get("report_sections_to_edit", [])) > 0
        
        # Step 3: After merge completion
        state3 = State(
            messages=state2.get("messages", []),
            final_report="Merged report content",
            is_editing_report=False,
            previous_report="",
        )
        
        assert state3.get("is_editing_report") is False
        assert state3.get("final_report") == "Merged report content"
        assert state3.get("previous_report") == ""

    def test_state_copy_preserves_editing_fields(self):
        """Test that state copying preserves editing fields."""
        original = State(
            messages=[],
            previous_report="Sample report",
            is_editing_report=True,
            report_edit_context="Edit feedback",
            report_sections_to_edit=["section_1"],
        )
        
        # Create a copy with the same fields
        copied_dict = {
            "messages": original.get("messages", []),
            "previous_report": original.get("previous_report"),
            "is_editing_report": original.get("is_editing_report"),
            "report_edit_context": original.get("report_edit_context"),
            "report_sections_to_edit": original.get("report_sections_to_edit"),
        }
        copied = State(**copied_dict)
        
        assert copied.get("previous_report") == original.get("previous_report")
        assert copied.get("is_editing_report") == original.get("is_editing_report")
        assert copied.get("report_edit_context") == original.get("report_edit_context")
        assert copied.get("report_sections_to_edit") == original.get("report_sections_to_edit")

    def test_state_sections_list_mutability(self):
        """Test that report_sections_to_edit list is mutable."""
        sections = ["section_1"]
        state = State(
            messages=[],
            report_sections_to_edit=sections,
        )
        
        assert len(state.get("report_sections_to_edit", [])) == 1
        
        # Modify the list
        sections.append("section_2")
        
        assert len(sections) == 2
        assert "section_2" in sections

    def test_state_large_report_handling(self):
        """Test State can handle large report content."""
        large_report = "Content. " * 10000  # Large content
        
        state = State(
            messages=[],
            previous_report=large_report,
        )
        
        assert state.get("previous_report") == large_report
        assert len(state.get("previous_report", "")) > 1000

    def test_state_special_characters_in_context(self):
        """Test State can handle special characters in context."""
        context = "Fix <html> [markdown] {json} @mentions #hashtags"
        
        state = State(
            messages=[],
            report_edit_context=context,
        )
        
        assert state.get("report_edit_context") == context

    def test_state_unicode_support(self):
        """Test State supports unicode in editing fields."""
        unicode_context = "修改第2部分关于AI应用的内容"
        
        state = State(
            messages=[],
            report_edit_context=unicode_context,
        )
        
        assert state.get("report_edit_context") == unicode_context
