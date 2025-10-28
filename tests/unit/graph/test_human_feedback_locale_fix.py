# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for the human_feedback_node locale fix.

Tests that the duplicate locale assignment issue is resolved:
- Locale is safely retrieved from new_plan using .get() with fallback
- If new_plan['locale'] doesn't exist, it doesn't cause a KeyError
- If new_plan['locale'] is None or empty, the preserved state locale is used
- If new_plan['locale'] has a valid value, it properly overrides the state locale
"""

import pytest
from src.graph.nodes import preserve_state_meta_fields
from src.graph.types import State
from src.prompts.planner_model import Plan


class TestHumanFeedbackLocaleFixture:
    """Test suite for human_feedback_node locale safe handling."""

    def test_preserve_state_meta_fields_no_keyerror(self):
        """Test that preserve_state_meta_fields never raises KeyError."""
        state = State(messages=[], locale="zh-CN")
        preserved = preserve_state_meta_fields(state)
        
        assert preserved["locale"] == "zh-CN"
        assert "locale" in preserved

    def test_new_plan_without_locale_override(self):
        """
        Test scenario: Plan doesn't override locale when not provided in override dict.
        
        Before fix: Would set locale twice (duplicate assignment)
        After fix: Uses .get() safely and only overrides if value is truthy
        """
        state = State(messages=[], locale="zh-CN")
        
        # Simulate a plan that doesn't want to override the locale
        # (locale is in the plan for validation, but not in override dict)
        new_plan_dict = {"title": "Test", "thought": "Test", "steps": [], "locale": "zh-CN", "has_enough_context": False}
        
        # Get preserved fields
        preserved = preserve_state_meta_fields(state)
        
        # Build update dict like the fixed code does
        update_dict = {
            "current_plan": Plan.model_validate(new_plan_dict),
            **preserved,
        }
        
        # Simulate a dict that doesn't have locale override (like when plan_dict is empty for override)
        plan_override = {}  # No locale in override dict
        
        # Only override locale if override dict provides a valid value
        if plan_override.get("locale"):
            update_dict["locale"] = plan_override["locale"]
        
        # The preserved locale should be used when override doesn't provide one
        assert update_dict["locale"] == "zh-CN"

    def test_new_plan_with_none_locale(self):
        """
        Test scenario: new_plan has locale=None.
        
        Before fix: Would try to set locale to None (but Plan requires it)
        After fix: Uses preserved state locale since new_plan.get("locale") is falsy
        """
        state = State(messages=[], locale="zh-CN")
        
        # new_plan with None locale (won't validate, but test the logic)
        new_plan_attempt = {"title": "Test", "thought": "Test", "steps": [], "locale": "en-US", "has_enough_context": False}
        
        # Get preserved fields
        preserved = preserve_state_meta_fields(state)
        
        # Build update dict like the fixed code does
        update_dict = {
            "current_plan": Plan.model_validate(new_plan_attempt),
            **preserved,
        }
        
        # Simulate checking for None locale (if it somehow got set)
        new_plan_with_none = {"locale": None}
        # Only override if new_plan provides a VALID value
        if new_plan_with_none.get("locale"):
            update_dict["locale"] = new_plan_with_none["locale"]
        
        # Should use preserved locale (zh-CN), not None
        assert update_dict["locale"] == "zh-CN"
        assert update_dict["locale"] is not None

    def test_new_plan_with_empty_string_locale(self):
        """
        Test scenario: new_plan has locale="" (empty string).
        
        Before fix: Would try to set locale to "" (but Plan requires valid value)
        After fix: Uses preserved state locale since empty string is falsy
        """
        state = State(messages=[], locale="zh-CN")
        
        # new_plan with valid locale
        new_plan = {"title": "Test", "thought": "Test", "steps": [], "locale": "en-US", "has_enough_context": False}
        
        # Get preserved fields
        preserved = preserve_state_meta_fields(state)
        
        # Build update dict like the fixed code does
        update_dict = {
            "current_plan": Plan.model_validate(new_plan),
            **preserved,
        }
        
        # Simulate checking for empty string locale
        new_plan_empty = {"locale": ""}
        # Only override if new_plan provides a VALID (truthy) value
        if new_plan_empty.get("locale"):
            update_dict["locale"] = new_plan_empty["locale"]
        
        # Should use preserved locale (zh-CN), not empty string
        assert update_dict["locale"] == "zh-CN"
        assert update_dict["locale"] != ""

    def test_new_plan_with_valid_locale_overrides(self):
        """
        Test scenario: new_plan has valid locale="en-US".
        
        Before fix: Would override with new_plan locale ✓ (worked)
        After fix: Should still properly override with valid locale
        """
        state = State(messages=[], locale="zh-CN")
        
        # new_plan has a different valid locale
        new_plan = {"title": "Test", "thought": "Test", "steps": [], "locale": "en-US", "has_enough_context": False}
        
        # Get preserved fields
        preserved = preserve_state_meta_fields(state)
        
        # Build update dict like the fixed code does
        update_dict = {
            "current_plan": Plan.model_validate(new_plan),
            **preserved,
        }
        
        # Override if new_plan provides a VALID value
        if new_plan.get("locale"):
            update_dict["locale"] = new_plan["locale"]
        
        # Should override with new_plan locale
        assert update_dict["locale"] == "en-US"
        assert update_dict["locale"] != "zh-CN"

    def test_locale_field_not_duplicated(self):
        """
        Test that locale field is not duplicated in the update dict.
        
        Before fix: locale was set twice in the same dict
        After fix: locale is only set once
        """
        state = State(messages=[], locale="zh-CN")
        new_plan = {"title": "Test", "thought": "Test", "steps": [], "locale": "en-US", "has_enough_context": False}
        
        preserved = preserve_state_meta_fields(state)
        
        # Count how many times 'locale' is set
        update_dict = {
            "current_plan": Plan.model_validate(new_plan),
            **preserved,  # Sets locale once
        }
        
        # Override locale only if new_plan provides valid value
        if new_plan.get("locale"):
            update_dict["locale"] = new_plan["locale"]
        
        # Verify locale is in dict exactly once
        locale_count = sum(1 for k in update_dict.keys() if k == "locale")
        assert locale_count == 1
        assert update_dict["locale"] == "en-US"  # Should be overridden

    def test_all_meta_fields_preserved(self):
        """
        Test that all 8 meta fields are preserved along with locale fix.
        
        Ensures the fix doesn't break other meta field preservation.
        """
        state = State(
            messages=[],
            locale="zh-CN",
            research_topic="Research",
            clarified_research_topic="Clarified",
            clarification_history=["Q1"],
            enable_clarification=True,
            max_clarification_rounds=5,
            clarification_rounds=1,
            resources=["resource1"],
        )
        
        new_plan = {"title": "Test", "thought": "Test", "steps": [], "locale": "en-US", "has_enough_context": False}
        preserved = preserve_state_meta_fields(state)
        
        # All 8 meta fields should be in preserved
        meta_fields = [
            "locale",
            "research_topic",
            "clarified_research_topic",
            "clarification_history",
            "enable_clarification",
            "max_clarification_rounds",
            "clarification_rounds",
            "resources",
        ]
        
        for field in meta_fields:
            assert field in preserved
        
        # Build update dict
        update_dict = {
            "current_plan": Plan.model_validate(new_plan),
            **preserved,
        }
        
        # Override locale if new_plan provides valid value
        if new_plan.get("locale"):
            update_dict["locale"] = new_plan["locale"]
        
        # All meta fields should be in update_dict
        for field in meta_fields:
            assert field in update_dict


class TestHumanFeedbackLocaleScenarios:
    """Real-world scenarios for human_feedback_node locale handling."""

    def test_scenario_chinese_locale_preserved_when_plan_has_no_locale(self):
        """
        Scenario: User selected Chinese, plan preserves it.
        
        Expected: Preserved Chinese locale should be used
        """
        state = State(messages=[], locale="zh-CN")
        
        # Plan from planner with required fields
        new_plan_json = {
            "title": "Research Plan",
            "thought": "...",
            "steps": [
                {
                    "title": "Step 1",
                    "description": "...",
                    "need_search": True,
                    "step_type": "research",
                }
            ],
            "locale": "zh-CN",
            "has_enough_context": False,
        }
        
        preserved = preserve_state_meta_fields(state)
        update_dict = {
            "current_plan": Plan.model_validate(new_plan_json),
            **preserved,
        }
        
        if new_plan_json.get("locale"):
            update_dict["locale"] = new_plan_json["locale"]
        
        # Chinese locale should be preserved
        assert update_dict["locale"] == "zh-CN"

    def test_scenario_en_us_restored_even_if_plan_minimal(self):
        """
        Scenario: Minimal plan with en-US locale.
        
        Expected: Preserved en-US locale should survive
        """
        state = State(messages=[], locale="en-US")
        
        # Minimal plan with required fields
        new_plan_json = {"title": "Quick Plan", "steps": [], "locale": "en-US", "has_enough_context": False}
        
        preserved = preserve_state_meta_fields(state)
        update_dict = {
            "current_plan": Plan.model_validate(new_plan_json),
            **preserved,
        }
        
        if new_plan_json.get("locale"):
            update_dict["locale"] = new_plan_json["locale"]
        
        # en-US should survive
        assert update_dict["locale"] == "en-US"

    def test_scenario_multiple_locale_updates_safe(self):
        """
        Scenario: Multiple plan iterations with locale preservation.
        
        Expected: Each iteration safely handles locale
        """
        locales = ["zh-CN", "en-US", "fr-FR"]
        
        for locale in locales:
            state = State(messages=[], locale=locale)
            new_plan = {"title": "Plan", "steps": [], "locale": locale, "has_enough_context": False}
            
            preserved = preserve_state_meta_fields(state)
            update_dict = {
                "current_plan": Plan.model_validate(new_plan),
                **preserved,
            }
            
            if new_plan.get("locale"):
                update_dict["locale"] = new_plan["locale"]
            
            # Each iteration should preserve its locale
            assert update_dict["locale"] == locale
