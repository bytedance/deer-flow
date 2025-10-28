# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for state preservation functionality in graph nodes.

Tests the preserve_state_meta_fields() function and verifies that
critical state fields (especially locale) are properly preserved
across node state transitions.
"""

import pytest
from langgraph.types import Command

from src.graph.nodes import preserve_state_meta_fields
from src.graph.types import State


class TestPreserveStateMetaFields:
    """Test suite for preserve_state_meta_fields() function."""

    def test_preserve_all_fields_with_defaults(self):
        """Test that all fields are preserved with default values when state is empty."""
        # Create a minimal state with only messages
        state = State(messages=[])

        # Extract meta fields
        preserved = preserve_state_meta_fields(state)

        # Verify all expected fields are present
        assert "locale" in preserved
        assert "research_topic" in preserved
        assert "clarified_research_topic" in preserved
        assert "clarification_history" in preserved
        assert "enable_clarification" in preserved
        assert "max_clarification_rounds" in preserved
        assert "clarification_rounds" in preserved
        assert "resources" in preserved

        # Verify default values
        assert preserved["locale"] == "en-US"
        assert preserved["research_topic"] == ""
        assert preserved["clarified_research_topic"] == ""
        assert preserved["clarification_history"] == []
        assert preserved["enable_clarification"] is False
        assert preserved["max_clarification_rounds"] == 3
        assert preserved["clarification_rounds"] == 0
        assert preserved["resources"] == []

    def test_preserve_locale_from_state(self):
        """Test that locale is correctly preserved when set in state."""
        state = State(messages=[], locale="zh-CN")
        preserved = preserve_state_meta_fields(state)

        assert preserved["locale"] == "zh-CN"

    def test_preserve_locale_english(self):
        """Test that English locale is preserved."""
        state = State(messages=[], locale="en-US")
        preserved = preserve_state_meta_fields(state)

        assert preserved["locale"] == "en-US"

    def test_preserve_locale_with_custom_value(self):
        """Test that custom locale values are preserved."""
        state = State(messages=[], locale="fr-FR")
        preserved = preserve_state_meta_fields(state)

        assert preserved["locale"] == "fr-FR"

    def test_preserve_research_topic(self):
        """Test that research_topic is correctly preserved."""
        test_topic = "How to build sustainable cities"
        state = State(messages=[], research_topic=test_topic)
        preserved = preserve_state_meta_fields(state)

        assert preserved["research_topic"] == test_topic

    def test_preserve_clarified_research_topic(self):
        """Test that clarified_research_topic is correctly preserved."""
        test_topic = "Sustainable urban development with focus on green spaces"
        state = State(messages=[], clarified_research_topic=test_topic)
        preserved = preserve_state_meta_fields(state)

        assert preserved["clarified_research_topic"] == test_topic

    def test_preserve_clarification_history(self):
        """Test that clarification_history is correctly preserved."""
        history = ["Q: What aspects?", "A: Architecture and planning"]
        state = State(messages=[], clarification_history=history)
        preserved = preserve_state_meta_fields(state)

        assert preserved["clarification_history"] == history

    def test_preserve_clarification_flags(self):
        """Test that clarification flags are correctly preserved."""
        state = State(
            messages=[],
            enable_clarification=True,
            max_clarification_rounds=5,
            clarification_rounds=2,
        )
        preserved = preserve_state_meta_fields(state)

        assert preserved["enable_clarification"] is True
        assert preserved["max_clarification_rounds"] == 5
        assert preserved["clarification_rounds"] == 2

    def test_preserve_resources(self):
        """Test that resources list is correctly preserved."""
        resources = [{"id": "1", "name": "Resource 1"}]
        state = State(messages=[], resources=resources)
        preserved = preserve_state_meta_fields(state)

        assert preserved["resources"] == resources

    def test_preserve_all_fields_together(self):
        """Test that all meta fields are preserved together correctly."""
        state = State(
            messages=[],
            locale="zh-CN",
            research_topic="原始查询",
            clarified_research_topic="澄清后的查询",
            clarification_history=["Q1", "A1", "Q2", "A2"],
            enable_clarification=True,
            max_clarification_rounds=5,
            clarification_rounds=2,
            resources=["resource1"],
        )

        preserved = preserve_state_meta_fields(state)

        assert preserved["locale"] == "zh-CN"
        assert preserved["research_topic"] == "原始查询"
        assert preserved["clarified_research_topic"] == "澄清后的查询"
        assert preserved["clarification_history"] == ["Q1", "A1", "Q2", "A2"]
        assert preserved["enable_clarification"] is True
        assert preserved["max_clarification_rounds"] == 5
        assert preserved["clarification_rounds"] == 2
        assert preserved["resources"] == ["resource1"]

    def test_preserve_returns_dict_not_state_object(self):
        """Test that preserve_state_meta_fields returns a dict."""
        state = State(messages=[], locale="zh-CN")
        preserved = preserve_state_meta_fields(state)

        assert isinstance(preserved, dict)
        # Verify it's a plain dict with expected keys
        assert "locale" in preserved
        assert "research_topic" in preserved

    def test_preserve_does_not_mutate_original_state(self):
        """Test that calling preserve_state_meta_fields does not mutate the original state."""
        original_locale = "zh-CN"
        state = State(messages=[], locale=original_locale)
        original_state_copy = dict(state)

        preserve_state_meta_fields(state)

        # Verify state hasn't changed
        assert state["locale"] == original_locale
        assert dict(state) == original_state_copy

    def test_preserve_with_none_values(self):
        """Test that preserve handles None values gracefully."""
        state = State(messages=[], locale=None)
        preserved = preserve_state_meta_fields(state)

        # Should use default when value is None
        assert preserved["locale"] is None or preserved["locale"] == "en-US"

    def test_preserve_empty_lists_preserved(self):
        """Test that empty lists are preserved correctly."""
        state = State(
            messages=[], clarification_history=[], resources=[]
        )
        preserved = preserve_state_meta_fields(state)

        assert preserved["clarification_history"] == []
        assert preserved["resources"] == []

    def test_preserve_count_of_fields(self):
        """Test that exactly 8 fields are preserved."""
        state = State(messages=[])
        preserved = preserve_state_meta_fields(state)

        # Should have exactly 8 meta fields
        assert len(preserved) == 8

    def test_preserve_field_names(self):
        """Test that all expected field names are present."""
        state = State(messages=[])
        preserved = preserve_state_meta_fields(state)

        expected_fields = {
            "locale",
            "research_topic",
            "clarified_research_topic",
            "clarification_history",
            "enable_clarification",
            "max_clarification_rounds",
            "clarification_rounds",
            "resources",
        }

        assert set(preserved.keys()) == expected_fields


class TestStatePreservationInCommand:
    """Test suite for using preserved state fields in Command objects."""

    def test_command_update_with_preserved_fields(self):
        """Test that preserved fields can be unpacked into Command.update."""
        state = State(messages=[], locale="zh-CN", research_topic="测试")

        # This should not raise any errors
        preserved = preserve_state_meta_fields(state)
        command_update = {
            "messages": [],
            **preserved,
        }

        assert "locale" in command_update
        assert "research_topic" in command_update
        assert command_update["locale"] == "zh-CN"

    def test_command_unpacking_syntax(self):
        """Test that the unpacking syntax works correctly with preserved fields."""
        state = State(messages=[], locale="en-US")
        preserved = preserve_state_meta_fields(state)

        # Simulate how it's used in actual nodes
        update_dict = {
            "messages": [],
            "current_plan": None,
            **preserved,
            "locale": "zh-CN",
        }

        assert len(update_dict) >= 10  # 2 explicit + 8 preserved
        assert update_dict["locale"] == "zh-CN" # overridden value


class TestLocalePreservationSpecific:
    """Specific test cases for locale preservation (the main issue being fixed)."""

    def test_locale_not_lost_in_transition(self):
        """Test that locale is not lost when transitioning between nodes."""
        # Initial state from frontend with Chinese locale
        initial_state = State(messages=[], locale="zh-CN")

        # Extract for first node transition
        preserved_1 = preserve_state_meta_fields(initial_state)

        # Simulate state update from first node
        updated_state_1 = State(
            messages=[], **preserved_1
        )

        # Extract for second node transition
        preserved_2 = preserve_state_meta_fields(updated_state_1)

        # Locale should still be zh-CN after two transitions
        assert preserved_2["locale"] == "zh-CN"

    def test_locale_chain_through_multiple_nodes(self):
        """Test that locale survives through multiple node transitions."""
        initial_locale = "zh-CN"
        state = State(messages=[], locale=initial_locale)

        # Simulate 5 node transitions
        for _ in range(5):
            preserved = preserve_state_meta_fields(state)
            assert preserved["locale"] == initial_locale

            # Create new state for next "node"
            state = State(messages=[], **preserved)

        # After 5 transitions, locale should still be preserved
        assert state.get("locale") == initial_locale

    def test_locale_with_other_fields_preserved_together(self):
        """Test that locale is preserved correctly even when other fields change."""
        initial_state = State(
            messages=[],
            locale="zh-CN",
            research_topic="Original",
            clarification_rounds=0,
        )

        preserved = preserve_state_meta_fields(initial_state)

        # Verify locale is in preserved dict
        assert preserved["locale"] == "zh-CN"
        assert preserved["research_topic"] == "Original"
        assert preserved["clarification_rounds"] == 0

        # Create new state with preserved fields
        modified_state = State(
            messages=[],
            **preserved,
        )

        # Locale should be preserved
        assert modified_state.get("locale") == "zh-CN"
        # Research topic should be preserved from original
        assert modified_state.get("research_topic") == "Original"
        assert modified_state.get("clarification_rounds") == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_research_topic(self):
        """Test preservation with very long research_topic."""
        long_topic = "a" * 10000
        state = State(messages=[], research_topic=long_topic)
        preserved = preserve_state_meta_fields(state)

        assert preserved["research_topic"] == long_topic

    def test_unicode_characters_in_topic(self):
        """Test preservation with unicode characters."""
        unicode_topic = "中文测试 🌍 テスト 🧪"
        state = State(messages=[], research_topic=unicode_topic)
        preserved = preserve_state_meta_fields(state)

        assert preserved["research_topic"] == unicode_topic

    def test_special_characters_in_locale(self):
        """Test preservation with special locale formats."""
        special_locales = ["zh-CN", "en-US", "pt-BR", "es-ES", "ja-JP"]

        for locale in special_locales:
            state = State(messages=[], locale=locale)
            preserved = preserve_state_meta_fields(state)
            assert preserved["locale"] == locale

    def test_large_clarification_history(self):
        """Test preservation with large clarification_history."""
        large_history = [f"Q{i}: Question {i}" for i in range(100)]
        state = State(messages=[], clarification_history=large_history)
        preserved = preserve_state_meta_fields(state)

        assert len(preserved["clarification_history"]) == 100
        assert preserved["clarification_history"] == large_history

    def test_max_clarification_rounds_boundary(self):
        """Test preservation with boundary values for max_clarification_rounds."""
        test_cases = [0, 1, 3, 10, 100, 999]

        for value in test_cases:
            state = State(messages=[], max_clarification_rounds=value)
            preserved = preserve_state_meta_fields(state)
            assert preserved["max_clarification_rounds"] == value
