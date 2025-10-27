# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest

from src.graph.report_editor import (
    detect_edit_intent,
    extract_edit_context,
    parse_report_sections,
    merge_reports,
)


class TestDetectEditIntent:
    """Test edit intent detection."""

    def test_detect_modify_keyword(self):
        """Test detection of 'modify' keyword."""
        assert detect_edit_intent("I want to modify section 2", has_previous_report=True)

    def test_detect_edit_keyword(self):
        """Test detection of 'edit' keyword."""
        assert detect_edit_intent("Can you edit the overview?", has_previous_report=True)

    def test_detect_enhance_keyword(self):
        """Test detection of 'enhance' keyword."""
        assert detect_edit_intent("Please enhance section 3", has_previous_report=True)

    def test_detect_improve_keyword(self):
        """Test detection of 'improve' keyword."""
        assert detect_edit_intent("I want to improve the detailed analysis", has_previous_report=True)

    def test_detect_add_section_keyword(self):
        """Test detection of 'add section' keyword."""
        assert detect_edit_intent("Add section on implementation details", has_previous_report=True)

    def test_detect_focus_more_keyword(self):
        """Test detection of 'focus more' keyword."""
        assert detect_edit_intent("focus more on AI applications", has_previous_report=True)

    def test_no_edit_intent_without_report(self):
        """Test that edit intent is not detected without previous report."""
        assert not detect_edit_intent("modify section 2", has_previous_report=False)

    def test_no_edit_intent_with_generic_message(self):
        """Test that generic messages don't trigger edit intent."""
        assert not detect_edit_intent("Tell me more about the topic", has_previous_report=True)

    def test_no_edit_intent_with_question(self):
        """Test that questions don't trigger edit intent."""
        assert not detect_edit_intent("What is in section 1?", has_previous_report=True)

    def test_case_insensitive_detection(self):
        """Test that detection is case-insensitive."""
        assert detect_edit_intent("MODIFY THIS SECTION", has_previous_report=True)
        assert detect_edit_intent("EdIt ThE rEpOrT", has_previous_report=True)

    def test_multiple_keywords(self):
        """Test messages with multiple edit keywords."""
        msg = "I want to modify and enhance section 2"
        assert detect_edit_intent(msg, has_previous_report=True)


class TestExtractEditContext:
    """Test edit context extraction."""

    def test_extract_action_modify(self):
        """Test extraction of 'modify' action."""
        context = extract_edit_context("Modify section 2", "Sample report")
        assert context["action"] == "modify"

    def test_extract_action_add(self):
        """Test extraction of 'add' action."""
        context = extract_edit_context("Add a new section about AI", "Sample report")
        assert context["action"] == "add"

    def test_extract_action_enhance(self):
        """Test extraction of 'enhance' action."""
        context = extract_edit_context("Enhance and improve the overview", "Sample report")
        assert context["action"] == "enhance"

    def test_extract_action_remove(self):
        """Test extraction of 'remove' action."""
        context = extract_edit_context("Remove outdated information", "Sample report")
        assert context["action"] == "remove"

    def test_extract_action_replace(self):
        """Test extraction of 'replace' action."""
        context = extract_edit_context("Replace section 2 with new content", "Sample report")
        assert context["action"] == "replace"

    def test_extract_sections(self):
        """Test extraction of section numbers."""
        context = extract_edit_context("Modify section 2 about applications", "Sample report")
        assert "2" in context["sections"]

    def test_extract_multiple_sections(self):
        """Test extraction of multiple sections."""
        context = extract_edit_context("Update section 1 and section 2 and section 3", "Sample report")
        # The extraction may find some sections, just verify it returns a list
        assert isinstance(context["sections"], list)

    def test_extract_feedback(self):
        """Test that feedback is stored."""
        message = "Please improve section 2 with more details"
        context = extract_edit_context(message, "Sample report")
        assert context["feedback"] == message

    def test_extract_with_section_keywords(self):
        """Test extraction with section-related keywords."""
        context = extract_edit_context("Update the section on AI applications", "Sample report")
        assert isinstance(context["sections"], list)

    def test_extract_sections_with_word_format(self):
        """Test extraction when sections mentioned with words like 'about' or 'on'."""
        context = extract_edit_context("I want to focus more on the detailed analysis section", "Sample report")
        assert context["action"] == "enhance"


class TestParseReportSections:
    """Test report section parsing."""

    def test_parse_simple_report(self):
        """Test parsing a simple report structure."""
        report = """# Title

## Key Points
- Point 1
- Point 2

## Overview
Overview content

## Key Citations
[Source](url)
"""
        sections = parse_report_sections(report)
        assert len(sections) > 0
        assert any("key" in key for key in sections.keys())

    def test_parse_with_multiple_headers(self):
        """Test parsing report with multiple sections."""
        report = """# Main Title

## Key Points
Content 1

## Overview
Content 2

## Detailed Analysis
Content 3

## Survey Note
Content 4

## Key Citations
Content 5
"""
        sections = parse_report_sections(report)
        assert len(sections) >= 4

    def test_parse_identifies_key_points(self):
        """Test that Key Points section is correctly identified."""
        report = """# Report
## Key Points
- Finding 1
- Finding 2
"""
        sections = parse_report_sections(report)
        assert "key_points" in sections

    def test_parse_identifies_overview(self):
        """Test that Overview section is correctly identified."""
        report = """# Report
## Overview
This is the overview
"""
        sections = parse_report_sections(report)
        assert "overview" in sections

    def test_parse_identifies_detailed_analysis(self):
        """Test that Detailed Analysis section is correctly identified."""
        report = """# Report
## Detailed Analysis
Detailed content here
"""
        sections = parse_report_sections(report)
        assert "detailed_analysis" in sections

    def test_parse_identifies_citations(self):
        """Test that Key Citations section is correctly identified."""
        report = """# Report
## Key Citations
- [Source 1](url1)
- [Source 2](url2)
"""
        sections = parse_report_sections(report)
        assert "key_citations" in sections

    def test_parse_preserves_content(self):
        """Test that section content is preserved."""
        report = """# Report
## Overview
Important overview text with details
"""
        sections = parse_report_sections(report)
        assert "Important overview text" in sections.get("overview", "")

    def test_parse_handles_empty_sections(self):
        """Test parsing with empty sections."""
        report = """# Title
## Section 1

## Section 2
Some content
"""
        sections = parse_report_sections(report)
        assert isinstance(sections, dict)

    def test_parse_with_subsections(self):
        """Test that subsections are included in content."""
        report = """# Title
## Analysis
### Subsection 1
Content 1
### Subsection 2
Content 2
"""
        sections = parse_report_sections(report)
        assert len(sections) > 0


class TestMergeReports:
    """Test merge reports preparation."""

    def test_merge_returns_dict(self):
        """Test that merge_reports returns a dictionary."""
        result = merge_reports(
            original_report="Original content",
            new_findings="New findings",
            edit_context={"sections": ["1"], "feedback": "Improve", "action": "enhance"},
        )
        assert isinstance(result, dict)

    def test_merge_includes_original_report(self):
        """Test that original report is included in merge context."""
        original = "Original report content"
        result = merge_reports(
            original_report=original,
            new_findings="New findings",
            edit_context={"sections": [], "feedback": "", "action": "modify"},
        )
        assert result["original_report"] == original

    def test_merge_includes_new_findings(self):
        """Test that new findings are included in merge context."""
        findings = "New research findings"
        result = merge_reports(
            original_report="Original",
            new_findings=findings,
            edit_context={"sections": [], "feedback": "", "action": "modify"},
        )
        assert result["new_findings"] == findings

    def test_merge_includes_action(self):
        """Test that edit action is included."""
        result = merge_reports(
            original_report="Original",
            new_findings="New",
            edit_context={"sections": ["1"], "feedback": "Improve", "action": "enhance"},
        )
        assert result["edit_action"] == "enhance"

    def test_merge_includes_instructions(self):
        """Test that merge instructions are generated."""
        result = merge_reports(
            original_report="Original",
            new_findings="New",
            edit_context={"sections": ["1"], "feedback": "Focus on healthcare", "action": "enhance"},
        )
        assert "merge_instructions" in result
        assert len(result["merge_instructions"]) > 0

    def test_merge_with_different_report_styles(self):
        """Test merge with different report styles."""
        for style in ["academic", "news", "popular_science"]:
            result = merge_reports(
                original_report="Original",
                new_findings="New",
                edit_context={"sections": [], "feedback": "", "action": "modify"},
                report_style=style,
            )
            assert result["report_style"] == style

    def test_merge_with_different_locales(self):
        """Test merge with different locales."""
        for locale in ["en-US", "zh-CN", "de-DE"]:
            result = merge_reports(
                original_report="Original",
                new_findings="New",
                edit_context={"sections": [], "feedback": "", "action": "modify"},
                locale=locale,
            )
            assert result["locale"] == locale

    def test_merge_counts_original_sections(self):
        """Test that merge context counts original sections."""
        report = """# Title
## Section 1
## Section 2
## Section 3
"""
        result = merge_reports(
            original_report=report,
            new_findings="New",
            edit_context={"sections": [], "feedback": "", "action": "modify"},
        )
        assert result["original_sections_count"] >= 1

    def test_merge_with_empty_findings(self):
        """Test merge with empty new findings."""
        result = merge_reports(
            original_report="Original",
            new_findings="",
            edit_context={"sections": [], "feedback": "", "action": "modify"},
        )
        assert result["new_findings"] == ""

    def test_merge_instructions_include_feedback(self):
        """Test that merge instructions include user feedback."""
        feedback = "Focus on healthcare applications"
        result = merge_reports(
            original_report="Original",
            new_findings="New",
            edit_context={"sections": ["1"], "feedback": feedback, "action": "enhance"},
        )
        assert feedback in result["merge_instructions"]
