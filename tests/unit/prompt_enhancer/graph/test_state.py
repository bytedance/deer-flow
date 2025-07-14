# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from src.prompt_enhancer.graph.state import PromptEnhancerState
from src.config.report_style import ReportStyle


def test_prompt_enhancer_state_creation():
    """Test that PromptEnhancerState can be created with required fields."""
    state = PromptEnhancerState(
        prompt="Test prompt", context=None, report_style=None, output=None
    )

    assert state["prompt"] == "Test prompt"
    assert state["context"] is None
    assert state["report_style"] is None
    assert state["output"] is None


def test_prompt_enhancer_state_with_all_fields():
    """Test PromptEnhancerState with all fields populated."""
    state = PromptEnhancerState(
        prompt="Write about AI",
        context="Additional context about AI research",
        report_style=ReportStyle.ACADEMIC,
        output="Enhanced prompt about AI research",
    )

    assert state["prompt"] == "Write about AI"
    assert state["context"] == "Additional context about AI research"
    assert state["report_style"] == ReportStyle.ACADEMIC
    assert state["output"] == "Enhanced prompt about AI research"


def test_prompt_enhancer_state_minimal():
    """Test PromptEnhancerState with only required prompt field."""
    state = PromptEnhancerState(prompt="Minimal prompt")

    assert state["prompt"] == "Minimal prompt"
    # Optional fields should not be present if not specified
    assert "context" not in state
    assert "report_style" not in state
    assert "output" not in state


def test_prompt_enhancer_state_with_different_report_styles():
    """Test PromptEnhancerState with different ReportStyle values."""
    styles = [
        ReportStyle.ACADEMIC,
        ReportStyle.POPULAR_SCIENCE,
        ReportStyle.NEWS,
        ReportStyle.SOCIAL_MEDIA,
    ]

    for style in styles:
        state = PromptEnhancerState(prompt="Test prompt", report_style=style)
        assert state["report_style"] == style


def test_prompt_enhancer_state_update():
    """Test updating PromptEnhancerState fields."""
    state = PromptEnhancerState(prompt="Original prompt")

    # Update with new fields
    state.update(
        {
            "context": "New context",
            "report_style": ReportStyle.NEWS,
            "output": "Enhanced output",
        }
    )

    assert state["prompt"] == "Original prompt"
    assert state["context"] == "New context"
    assert state["report_style"] == ReportStyle.NEWS
    assert state["output"] == "Enhanced output"


def test_prompt_enhancer_state_get_method():
    """Test using get() method on PromptEnhancerState."""
    state = PromptEnhancerState(prompt="Test prompt", report_style=ReportStyle.ACADEMIC)

    # Test get with existing keys
    assert state.get("prompt") == "Test prompt"
    assert state.get("report_style") == ReportStyle.ACADEMIC

    # Test get with non-existing keys
    assert state.get("context") is None
    assert state.get("output") is None
    assert state.get("nonexistent", "default") == "default"


def test_prompt_enhancer_state_type_annotations():
    """Test that the state accepts correct types."""
    # This test ensures the TypedDict structure is working correctly
    state = PromptEnhancerState(
        prompt="Test prompt",
        context="Test context",
        report_style=ReportStyle.POPULAR_SCIENCE,
        output="Test output",
    )

    # Verify types
    assert isinstance(state["prompt"], str)
    assert isinstance(state["context"], str)
    assert isinstance(state["report_style"], ReportStyle)
    assert isinstance(state["output"], str)
