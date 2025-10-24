# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock

from src.graph.nodes import validate_and_fix_plan


class TestValidateAndFixPlanStepTypeRepair:
    """Test step_type field repair logic (Issue #650 fix)."""

    def test_repair_missing_step_type_with_need_search_true(self):
        """Test that missing step_type is inferred as 'research' when need_search=true."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research Step",
                    "description": "Gather data",
                    # step_type is MISSING
                }
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "research"

    def test_repair_missing_step_type_with_need_search_false(self):
        """Test that missing step_type is inferred as 'processing' when need_search=false."""
        plan = {
            "steps": [
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze data",
                    # step_type is MISSING
                }
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "processing"

    def test_repair_missing_step_type_default_to_processing(self):
        """Test that missing step_type defaults to 'processing' when need_search is not specified."""
        plan = {
            "steps": [
                {
                    "title": "Unknown Step",
                    "description": "Do something",
                    # need_search is MISSING, step_type is MISSING
                }
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "processing"

    def test_repair_empty_step_type_field(self):
        """Test that empty step_type field is repaired."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research Step",
                    "description": "Gather data",
                    "step_type": "",  # Empty string
                }
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "research"

    def test_repair_null_step_type_field(self):
        """Test that null step_type field is repaired."""
        plan = {
            "steps": [
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze data",
                    "step_type": None,
                }
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "processing"

    def test_multiple_steps_with_mixed_missing_step_types(self):
        """Test repair of multiple steps with different missing step_type scenarios."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research 1",
                    "description": "Gather",
                    # MISSING step_type
                },
                {
                    "need_search": False,
                    "title": "Processing 1",
                    "description": "Analyze",
                    "step_type": "processing",  # Already has step_type
                },
                {
                    "need_search": True,
                    "title": "Research 2",
                    "description": "More gathering",
                    # MISSING step_type
                },
            ]
        }

        result = validate_and_fix_plan(plan)

        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][1]["step_type"] == "processing"  # Should remain unchanged
        assert result["steps"][2]["step_type"] == "research"

    def test_preserve_explicit_step_type(self):
        """Test that explicitly provided step_type values are preserved."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research Step",
                    "description": "Gather",
                    "step_type": "research",
                },
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze",
                    "step_type": "processing",
                },
            ]
        }

        result = validate_and_fix_plan(plan)

        # Should remain unchanged
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][1]["step_type"] == "processing"

    def test_repair_logs_warning(self):
        """Test that repair operations are logged."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Missing Type Step",
                    "description": "Gather",
                }
            ]
        }

        with patch("src.graph.nodes.logger") as mock_logger:
            validate_and_fix_plan(plan)
            # Should log repair operation
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            assert "Repaired missing step_type" in call_args

    def test_non_dict_plan_returns_unchanged(self):
        """Test that non-dict plans are returned unchanged."""
        plan = "not a dict"
        result = validate_and_fix_plan(plan)
        assert result == plan

    def test_plan_with_non_dict_step_skipped(self):
        """Test that non-dict step items are skipped without error."""
        plan = {
            "steps": [
                "not a dict step",  # This should be skipped
                {
                    "need_search": True,
                    "title": "Valid Step",
                    "description": "Gather",
                },
            ]
        }

        result = validate_and_fix_plan(plan)

        # Non-dict step should be unchanged, valid step should be fixed
        assert result["steps"][0] == "not a dict step"
        assert result["steps"][1]["step_type"] == "research"

    def test_empty_steps_list(self):
        """Test that plan with empty steps list is handled gracefully."""
        plan = {"steps": []}
        result = validate_and_fix_plan(plan)
        assert result["steps"] == []

    def test_missing_steps_key(self):
        """Test that plan without steps key is handled gracefully."""
        plan = {"locale": "en-US", "title": "Test"}
        result = validate_and_fix_plan(plan)
        assert "steps" not in result or result.get("steps") == []


class TestValidateAndFixPlanWebSearchEnforcement:
    """Test web search enforcement logic."""

    def test_enforce_web_search_sets_first_research_step(self):
        """Test that enforce_web_search=True sets need_search on first research step."""
        plan = {
            "steps": [
                {
                    "need_search": False,
                    "title": "Research Step",
                    "description": "Gather",
                    "step_type": "research",
                },
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze",
                    "step_type": "processing",
                },
            ]
        }

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        # First research step should have web search enabled
        assert result["steps"][0]["need_search"] is True
        assert result["steps"][1]["need_search"] is False

    def test_enforce_web_search_converts_first_step(self):
        """Test that enforce_web_search converts first step to research if needed."""
        plan = {
            "steps": [
                {
                    "need_search": False,
                    "title": "First Step",
                    "description": "Do something",
                    "step_type": "processing",
                },
            ]
        }

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        # First step should be converted to research with web search
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][0]["need_search"] is True

    def test_enforce_web_search_with_existing_search_step(self):
        """Test that enforce_web_search doesn't modify if search step already exists."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research Step",
                    "description": "Gather",
                    "step_type": "research",
                },
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze",
                    "step_type": "processing",
                },
            ]
        }

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        # Steps should remain unchanged
        assert result["steps"][0]["need_search"] is True
        assert result["steps"][1]["need_search"] is False

    def test_enforce_web_search_adds_default_step(self):
        """Test that enforce_web_search adds default research step if no steps exist."""
        plan = {"steps": []}

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        assert len(result["steps"]) == 1
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][0]["need_search"] is True
        assert "title" in result["steps"][0]
        assert "description" in result["steps"][0]

    def test_enforce_web_search_without_steps_key(self):
        """Test enforce_web_search when steps key is missing."""
        plan = {"locale": "en-US"}

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        assert len(result.get("steps", [])) > 0
        assert result["steps"][0]["step_type"] == "research"


class TestValidateAndFixPlanIntegration:
    """Integration tests for step_type repair and web search enforcement together."""

    def test_repair_and_enforce_together(self):
        """Test that step_type repair and web search enforcement work together."""
        plan = {
            "steps": [
                {
                    "need_search": True,
                    "title": "Research Step",
                    "description": "Gather",
                    # MISSING step_type
                },
                {
                    "need_search": False,
                    "title": "Processing Step",
                    "description": "Analyze",
                    # MISSING step_type, but enforce_web_search won't change it
                },
            ]
        }

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        # step_type should be repaired
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][1]["step_type"] == "processing"

        # First research step should have web search (already has it)
        assert result["steps"][0]["need_search"] is True

    def test_repair_then_enforce_cascade(self):
        """Test complex scenario with repair and enforcement cascading."""
        plan = {
            "steps": [
                {
                    "need_search": False,
                    "title": "Step 1",
                    "description": "Do something",
                    # MISSING step_type
                },
                {
                    "need_search": False,
                    "title": "Step 2",
                    "description": "Do something else",
                    # MISSING step_type
                },
            ]
        }

        result = validate_and_fix_plan(plan, enforce_web_search=True)

        # Step 1: Originally processing but converted to research with web search enforcement
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][0]["need_search"] is True

        # Step 2: Should remain as processing since enforcement already satisfied by step 1
        assert result["steps"][1]["step_type"] == "processing"
        assert result["steps"][1]["need_search"] is False


class TestValidateAndFixPlanIssue650:
    """Specific tests for Issue #650 scenarios."""

    def test_issue_650_water_footprint_scenario_fixed(self):
        """Test the exact scenario from issue #650 - water footprint query with missing step_type."""
        # This is a simplified version of the actual error from issue #650
        plan = {
            "locale": "en-US",
            "has_enough_context": False,
            "title": "Research Plan — Water Footprint of 1 kg of Beef",
            "thought": "You asked: 'How many liters of water are required to produce 1 kg of beef?'",
            "steps": [
                {
                    "need_search": True,
                    "title": "Authoritative estimates",
                    "description": "Collect peer-reviewed estimates",
                    # MISSING step_type - this caused the error in issue #650
                },
                {
                    "need_search": True,
                    "title": "System-specific data",
                    "description": "Gather system-level data",
                    # MISSING step_type
                },
                {
                    "need_search": False,
                    "title": "Processing and analysis",
                    "description": "Compute scenario-based estimates",
                    # MISSING step_type
                },
            ],
        }

        result = validate_and_fix_plan(plan)

        # All steps should now have step_type
        assert result["steps"][0]["step_type"] == "research"
        assert result["steps"][1]["step_type"] == "research"
        assert result["steps"][2]["step_type"] == "processing"

    def test_issue_650_scenario_passes_pydantic_validation(self):
        """Test that fixed plan can be validated by Pydantic schema."""
        from src.prompts.planner_model import Plan as PlanModel

        plan = {
            "locale": "en-US",
            "has_enough_context": False,
            "title": "Research Plan",
            "thought": "Test thought",
            "steps": [
                {
                    "need_search": True,
                    "title": "Research",
                    "description": "Gather data",
                    # MISSING step_type
                },
            ],
        }

        # First validate and fix
        fixed_plan = validate_and_fix_plan(plan)

        # Then try Pydantic validation (should not raise)
        validated = PlanModel.model_validate(fixed_plan)

        assert validated.steps[0].step_type == "research"
        assert validated.steps[0].need_search is True

    def test_issue_650_multiple_validation_errors_fixed(self):
        """Test that plan with multiple missing step_types (like in issue #650) all get fixed."""
        plan = {
            "locale": "en-US",
            "has_enough_context": False,
            "title": "Complex Plan",
            "thought": "Research plan",
            "steps": [
                {
                    "need_search": True,
                    "title": "Step 0",
                    "description": "Data gathering",
                },
                {
                    "need_search": True,
                    "title": "Step 1",
                    "description": "More gathering",
                },
                {
                    "need_search": False,
                    "title": "Step 2",
                    "description": "Processing",
                },
            ],
        }

        result = validate_and_fix_plan(plan)

        # All steps should have step_type now
        for step in result["steps"]:
            assert "step_type" in step
            assert step["step_type"] in ["research", "processing"]

    def test_issue_650_no_exceptions_raised(self):
        """Test that validate_and_fix_plan handles all edge cases without raising exceptions."""
        test_cases = [
            {"steps": []},
            {"steps": [{"need_search": True}]},
            {"steps": [None, {}]},
            {"steps": ["invalid"]},
            {"steps": [{"need_search": True, "step_type": ""}]},
            "not a dict",
        ]

        for plan in test_cases:
            try:
                result = validate_and_fix_plan(plan)
                # Should succeed without exception - result may be returned as-is for non-dict
                # but the function should not raise
                # No assertion needed; test passes if no exception is raised
            except Exception as e:
                pytest.fail(f"validate_and_fix_plan raised exception for {plan}: {e}")
