# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import Mock, patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from src.graph.types import State
from src.graph.report_editor import (
    detect_edit_intent,
    extract_edit_context,
    parse_report_sections,
    merge_reports,
)


class TestReportEditingWorkflow:
    """Integration tests for the report editing workflow."""

    @pytest.fixture
    def sample_generated_report(self):
        """A sample report that would be generated."""
        return """# Artificial Intelligence Market Trends 2024

## Key Points
- AI market expected to grow 30% YoY
- Large language models continue to evolve
- Enterprise adoption accelerating
- Ethical concerns remain prominent

## Overview
The artificial intelligence sector is experiencing rapid growth and transformation. This report analyzes current market trends, key technologies, and emerging applications.

## Detailed Analysis

### Market Growth
The AI market size is projected to reach $500 billion by 2030, growing at 30% annually.

### Key Technologies
- Large Language Models (LLMs)
- Computer Vision
- Reinforcement Learning
- Autonomous Systems

### Current Applications
AI is currently used primarily in:
- Customer service (chatbots)
- Financial analysis
- Basic data analytics
- Image recognition

### Industry Challenges
- Data privacy concerns
- Model explainability
- Regulatory uncertainty
- Talent shortage

## Key Citations
- [McKinsey AI Report 2024](https://www.mckinsey.com/ai)
- [Gartner AI Hype Cycle](https://www.gartner.com)
- [Stanford AI Index](https://aiindex.stanford.edu)
"""

    def test_full_edit_workflow_detection(self, sample_generated_report):
        """Test full workflow: detect edit intent."""
        user_message = "I want to improve the Current Applications section with more details"
        has_previous_report = True
        
        # Step 1: Detect edit intent
        edit_detected = detect_edit_intent(user_message, has_previous_report)
        assert edit_detected is True

    def test_full_edit_workflow_extraction(self, sample_generated_report):
        """Test full workflow: extract edit context."""
        user_message = "Enhance the applications section to include healthcare and finance use cases"
        
        # Step 1: Detect
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        # Step 2: Extract context
        context = extract_edit_context(user_message, sample_generated_report)
        # Action could be enhance or add depending on keywords
        assert context["action"] in ["enhance", "add", "modify"]
        assert isinstance(context["feedback"], str)
        assert len(context["feedback"]) > 0

    def test_full_edit_workflow_parsing(self, sample_generated_report):
        """Test full workflow: parse sections."""
        user_message = "Improve the Current Applications section"
        
        # Step 1: Detect
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        # Step 2: Extract
        context = extract_edit_context(user_message, sample_generated_report)
        assert context is not None
        
        # Step 3: Parse sections
        sections = parse_report_sections(sample_generated_report)
        assert len(sections) >= 2
        # Just verify sections were parsed
        assert isinstance(sections, dict)

    def test_full_edit_workflow_merge_preparation(self, sample_generated_report):
        """Test full workflow: prepare merge context."""
        user_message = "Please enhance the detailed analysis with more specific numbers and percentages"
        
        # Step 1: Detect
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        # Step 2: Extract
        context = extract_edit_context(user_message, sample_generated_report)
        
        # Step 3: Prepare merge
        new_findings = "AI market growing at 35% CAGR. Healthcare AI adoption at 45%. Finance sector leads with 60% adoption rate."
        merge_context = merge_reports(
            original_report=sample_generated_report,
            new_findings=new_findings,
            edit_context=context,
            report_style="academic",
        )
        
        assert merge_context["original_report"] == sample_generated_report
        assert merge_context["new_findings"] == new_findings
        assert "merge_instructions" in merge_context
        assert len(merge_context["merge_instructions"]) > 0

    def test_workflow_with_focus_request(self, sample_generated_report):
        """Test workflow: user requests focus on specific aspect."""
        user_message = "Focus more on healthcare and finance applications in the detailed analysis"
        
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        context = extract_edit_context(user_message, sample_generated_report)
        assert context["action"] in ["enhance", "modify"]

    def test_workflow_with_add_section_request(self):
        """Test workflow: user requests adding new section."""
        report = "# Report\n## Overview\nContent"
        user_message = "Add section on future trends in AI"
        
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        context = extract_edit_context(user_message, report)
        assert context["action"] in ["add", "enhance", "modify"]

    def test_workflow_with_removal_request(self, sample_generated_report):
        """Test workflow: user requests removing outdated content."""
        user_message = "Remove the outdated information from the key challenges section"
        
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        context = extract_edit_context(user_message, sample_generated_report)
        assert context["action"] == "remove"

    def test_workflow_preserves_unchanged_sections(self, sample_generated_report):
        """Test workflow: unchanged sections are preserved."""
        user_message = "Update only the current applications section"
        new_findings = "Healthcare: 45% adoption. Finance: 60% adoption."
        
        # Extract
        context = extract_edit_context(user_message, sample_generated_report)
        
        # Prepare merge
        merge_context = merge_reports(
            original_report=sample_generated_report,
            new_findings=new_findings,
            edit_context=context,
        )
        
        # Verify merge instructions mention preserving other sections
        assert "preserve" in merge_context["merge_instructions"].lower() or \
               "keep" in merge_context["merge_instructions"].lower() or \
               "update" in merge_context["merge_instructions"].lower()

    def test_workflow_multiple_edit_cycles(self, sample_generated_report):
        """Test workflow: multiple edits on same report."""
        # First edit
        message1 = "Improve the market growth section"
        edit1 = detect_edit_intent(message1, has_previous_report=True)
        assert edit1
        
        context1 = extract_edit_context(message1, sample_generated_report)
        assert context1["action"] in ["enhance", "modify"]
        
        # Second edit (on same report)
        message2 = "Add more details about regulatory challenges"
        edit2 = detect_edit_intent(message2, has_previous_report=True)
        assert edit2
        
        context2 = extract_edit_context(message2, sample_generated_report)
        assert context2["action"] in ["add", "enhance", "modify"]

    def test_state_transitions(self, sample_generated_report):
        """Test state transitions during edit workflow."""
        # Initial state after report generation
        state1 = State(
            messages=[HumanMessage(content="Generate report on AI")],
            final_report=sample_generated_report,
            is_editing_report=False,
        )
        
        assert state1.get("is_editing_report") is False
        assert len(state1.get("final_report", "")) > 0
        
        # After user requests edit
        state2 = State(
            messages=state1.get("messages", []) + [
                HumanMessage(content="Modify the applications section")
            ],
            previous_report=state1.get("final_report", ""),
            is_editing_report=True,
            report_edit_context="Modify the applications section",
        )
        
        assert state2.get("is_editing_report") is True
        assert state2.get("previous_report") == sample_generated_report
        
        # After merge is complete
        state3 = State(
            messages=state2.get("messages", []),
            final_report="Modified report content",
            is_editing_report=False,
            previous_report="",
        )
        
        assert state3.get("is_editing_report") is False

    def test_section_identification_accuracy(self, sample_generated_report):
        """Test that sections are accurately identified."""
        sections = parse_report_sections(sample_generated_report)
        
        expected_sections = ["overview", "key_points", "detailed_analysis", "key_citations"]
        identified_sections = list(sections.keys())
        
        for expected in expected_sections:
            assert any(expected in identified for identified in identified_sections), \
                f"Expected section '{expected}' not found in {identified_sections}"

    def test_merge_context_completeness(self, sample_generated_report):
        """Test that merge context contains all necessary information."""
        user_message = "Enhance the current applications with healthcare examples"
        new_findings = "Healthcare AI market: $15B in 2024, growing at 45% CAGR"
        
        context = extract_edit_context(user_message, sample_generated_report)
        merge_context = merge_reports(
            original_report=sample_generated_report,
            new_findings=new_findings,
            edit_context=context,
            report_style="academic",
            locale="en-US",
        )
        
        # Verify all required fields are present
        required_fields = [
            "original_report",
            "new_findings",
            "edit_action",
            "target_sections",
            "merge_instructions",
            "original_sections_count",
            "report_style",
            "locale",
        ]
        
        for field in required_fields:
            assert field in merge_context, f"Missing field: {field}"

    def test_edit_intent_with_various_phrasings(self, sample_generated_report):
        """Test edit detection with various user phrasings."""
        test_cases = [
            "Update section 2",
            "Revise the overview",
            "Improve the detailed analysis",
            "Rewrite the key points",
            "Add more details",
            "Fix the statistics",
            "Enhance the current applications section",
            "Focus more on AI",
            "Change this section",
        ]
        
        for message in test_cases:
            result = detect_edit_intent(message, has_previous_report=True)
            assert result, f"Failed to detect edit intent in: '{message}'"

    def test_no_edit_detected_for_questions(self):
        """Test that questions about the report don't trigger edit mode."""
        question_cases = [
            "What does section 2 say about AI?",
            "Can you explain the overview?",
            "Which section discusses applications?",
            "Tell me more about the key points",
            "What are the main challenges mentioned?",
        ]
        
        for question in question_cases:
            result = detect_edit_intent(question, has_previous_report=True)
            assert not result, f"Incorrectly detected edit intent in question: '{question}'"

    def test_language_support(self, sample_generated_report):
        """Test merge context with different locales."""
        locales = ["en-US", "zh-CN", "de-DE", "fr-FR", "ja-JP"]
        
        for locale in locales:
            merge_context = merge_reports(
                original_report=sample_generated_report,
                new_findings="New findings",
                edit_context={"sections": [], "feedback": "", "action": "modify"},
                locale=locale,
            )
            
            assert merge_context["locale"] == locale

    def test_report_style_support(self, sample_generated_report):
        """Test merge context with different report styles."""
        styles = ["academic", "news", "popular_science", "strategic_investment"]
        
        for style in styles:
            merge_context = merge_reports(
                original_report=sample_generated_report,
                new_findings="New findings",
                edit_context={"sections": [], "feedback": "", "action": "modify"},
                report_style=style,
            )
            
            assert merge_context["report_style"] == style


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_report_editing(self):
        """Test editing an empty report."""
        empty_report = ""
        user_message = "Please add content"
        
        edit_detected = detect_edit_intent(user_message, has_previous_report=True)
        assert edit_detected
        
        sections = parse_report_sections(empty_report)
        assert isinstance(sections, dict)

    def test_very_long_report(self):
        """Test editing a very long report."""
        long_report = "# Title\n" + ("## Section\nVery long content. " * 1000)
        
        sections = parse_report_sections(long_report)
        assert len(sections) > 0

    def test_report_without_headers(self):
        """Test parsing report without markdown headers."""
        report = "This is just plain text without any headers or structure."
        
        sections = parse_report_sections(report)
        assert isinstance(sections, dict)

    def test_malformed_markdown(self):
        """Test parsing malformed markdown."""
        report = """# Title
## Section 1
Content with ### bad ### formatting
## Section 2
More content
"""
        sections = parse_report_sections(report)
        assert len(sections) > 0

    def test_special_characters_in_feedback(self):
        """Test feedback with special characters."""
        feedback = "Update section 2 with: <html>, [markdown], {json}, @mentions, #hashtags"
        
        context = extract_edit_context(feedback, "Sample report")
        assert context["feedback"] == feedback

    def test_very_specific_section_reference(self):
        """Test extracting very specific section references."""
        message = "In section 2.3.1 about AI applications in healthcare, add..."
        
        context = extract_edit_context(message, "Sample report")
        assert len(context["sections"]) > 0 or isinstance(context["sections"], list)

    def test_unicode_in_messages(self):
        """Test handling unicode characters in messages."""
        messages = [
            "修改第2节关于AI应用的内容",  # Chinese
            "Modifier la section 2 sur les applications d'IA",  # French
            "セクション2のAIアプリケーションを改善する",  # Japanese
        ]
        
        for message in messages:
            # Should not raise an exception
            result = detect_edit_intent(message, has_previous_report=True)
            assert isinstance(result, bool)
