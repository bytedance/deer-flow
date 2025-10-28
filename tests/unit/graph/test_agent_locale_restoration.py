# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for agent locale restoration after create_react_agent execution.

Tests that meta fields (especially locale) are properly restored after
agent.ainvoke() returns, since create_react_agent creates a MessagesState
subgraph that filters out custom fields.
"""

import pytest

from src.graph.nodes import preserve_state_meta_fields
from src.graph.types import State


class TestAgentLocaleRestoration:
    """Test suite for locale restoration after agent execution."""

    def test_locale_lost_in_agent_subgraph(self):
        """
        Demonstrate the problem: agent subgraph filters out locale.
        
        When create_react_agent creates a subgraph with MessagesState,
        it only returns messages, not custom fields.
        """
        # Simulate agent behavior: only returns messages
        initial_state = State(messages=[], locale="zh-CN")
        
        # Agent subgraph returns (like MessagesState would)
        agent_result = {
            "messages": ["agent response"],
        }
        
        # Problem: locale is missing
        assert "locale" not in agent_result
        assert agent_result.get("locale") is None

    def test_locale_restoration_after_agent(self):
        """Test that locale can be restored after agent.ainvoke() returns."""
        initial_state = State(
            messages=[],
            locale="zh-CN",
            research_topic="test",
        )
        
        # Simulate agent returning (MessagesState only)
        agent_result = {
            "messages": ["agent response"],
        }
        
        # Apply restoration
        preserved = preserve_state_meta_fields(initial_state)
        agent_result.update(preserved)
        
        # Verify restoration worked
        assert agent_result["locale"] == "zh-CN"
        assert agent_result["research_topic"] == "test"
        assert "messages" in agent_result

    def test_all_meta_fields_restored(self):
        """Test that all meta fields are restored, not just locale."""
        initial_state = State(
            messages=[],
            locale="en-US",
            research_topic="Original Topic",
            clarified_research_topic="Clarified Topic",
            clarification_history=["Q1", "A1"],
            enable_clarification=True,
            max_clarification_rounds=5,
            clarification_rounds=2,
            resources=["resource1"],
        )
        
        # Agent result
        agent_result = {"messages": ["response"]}
        agent_result.update(preserve_state_meta_fields(initial_state))
        
        # All fields should be restored
        assert agent_result["locale"] == "en-US"
        assert agent_result["research_topic"] == "Original Topic"
        assert agent_result["clarified_research_topic"] == "Clarified Topic"
        assert agent_result["clarification_history"] == ["Q1", "A1"]
        assert agent_result["enable_clarification"] is True
        assert agent_result["max_clarification_rounds"] == 5
        assert agent_result["clarification_rounds"] == 2
        assert agent_result["resources"] == ["resource1"]

    def test_locale_preservation_through_agent_cycle(self):
        """Test the complete cycle: state in → agent → state out."""
        # Initial state with zh-CN locale
        initial_state = State(messages=[], locale="zh-CN")
        
        # Step 1: Extract meta fields
        preserved = preserve_state_meta_fields(initial_state)
        assert preserved["locale"] == "zh-CN"
        
        # Step 2: Agent runs and returns only messages
        agent_result = {"messages": ["agent output"]}
        assert "locale" not in agent_result  # Missing!
        
        # Step 3: Restore meta fields
        agent_result.update(preserved)
        
        # Step 4: Verify locale is restored
        assert agent_result["locale"] == "zh-CN"
        
        # Step 5: Create new state with restored fields
        final_state = State(messages=agent_result["messages"], **preserved)
        assert final_state.get("locale") == "zh-CN"

    def test_locale_not_auto_after_restoration(self):
        """
        Test that locale is NOT "auto" after restoration.
        
        This tests the specific bug: locale was becoming "auto"
        instead of the preserved "zh-CN" value.
        """
        state = State(messages=[], locale="zh-CN")
        
        # Agent returns without locale
        agent_result = {"messages": []}
        
        # Before fix: locale would be "auto" (default behavior)
        # After fix: locale is preserved
        agent_result.update(preserve_state_meta_fields(state))
        
        assert agent_result.get("locale") == "zh-CN"
        assert agent_result.get("locale") != "auto"
        assert agent_result.get("locale") is not None

    def test_chinese_locale_preserved(self):
        """Test that Chinese locale specifically is preserved."""
        locales_to_test = ["zh-CN", "zh", "zh-Hans", "zh-Hant"]
        
        for locale_value in locales_to_test:
            state = State(messages=[], locale=locale_value)
            agent_result = {"messages": []}
            
            agent_result.update(preserve_state_meta_fields(state))
            
            assert agent_result["locale"] == locale_value, f"Failed for locale: {locale_value}"

    def test_restoration_with_new_messages(self):
        """Test that restoration works even when agent adds new messages."""
        state = State(messages=[], locale="zh-CN", research_topic="research")
        
        # Agent processes and returns new messages
        agent_result = {
            "messages": ["message1", "message2", "message3"],
        }
        
        # Restore meta fields
        agent_result.update(preserve_state_meta_fields(state))
        
        # Should have both new messages AND preserved meta fields
        assert len(agent_result["messages"]) == 3
        assert agent_result["locale"] == "zh-CN"
        assert agent_result["research_topic"] == "research"

    def test_restoration_idempotent(self):
        """Test that restoring meta fields multiple times doesn't cause issues."""
        state = State(messages=[], locale="en-US")
        preserved = preserve_state_meta_fields(state)
        
        agent_result = {"messages": []}
        
        # Apply restoration multiple times
        agent_result.update(preserved)
        agent_result.update(preserved)
        agent_result.update(preserved)
        
        # Should still have correct locale (not corrupted)
        assert agent_result["locale"] == "en-US"
        assert len(agent_result) == 9  # messages + 8 meta fields


class TestAgentLocaleRestorationScenarios:
    """Real-world scenario tests for agent locale restoration."""

    def test_researcher_agent_preserves_locale(self):
        """
        Simulate researcher agent execution preserving locale.
        
        Scenario:
        1. Researcher node receives state with locale="zh-CN"
        2. Calls agent.ainvoke() which returns only messages
        3. Restores locale before returning
        """
        # State coming into researcher node
        state = State(
            messages=[],
            locale="zh-CN",
            research_topic="生产1公斤牛肉需要多少升水？",
        )
        
        # Agent executes and returns
        agent_result = {
            "messages": ["Researcher analysis of water usage..."],
        }
        
        # Apply restoration (what the fix does)
        agent_result.update(preserve_state_meta_fields(state))
        
        # Verify for next node
        assert agent_result["locale"] == "zh-CN"  # ✓ Preserved!
        assert agent_result.get("locale") != "auto"  # ✓ Not "auto"

    def test_coder_agent_preserves_locale(self):
        """Coder agent should also preserve locale."""
        state = State(messages=[], locale="en-US")
        
        agent_result = {"messages": ["Code generation result"]}
        agent_result.update(preserve_state_meta_fields(state))
        
        assert agent_result["locale"] == "en-US"

    def test_locale_persists_across_multiple_agents(self):
        """Test that locale persists through multiple agent calls."""
        locales = ["zh-CN", "en-US", "fr-FR"]
        
        for locale in locales:
            # Initial state
            state = State(messages=[], locale=locale)
            preserved_1 = preserve_state_meta_fields(state)
            
            # First agent
            result_1 = {"messages": ["agent1"]}
            result_1.update(preserved_1)
            
            # Create state for second agent
            state_2 = State(messages=result_1["messages"], **preserved_1)
            preserved_2 = preserve_state_meta_fields(state_2)
            
            # Second agent
            result_2 = {"messages": result_1["messages"] + ["agent2"]}
            result_2.update(preserved_2)
            
            # Locale should persist
            assert result_2["locale"] == locale
