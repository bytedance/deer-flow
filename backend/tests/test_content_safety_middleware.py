"""Tests for InputGuardMiddleware and OutputGuardMiddleware."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.content_safety.builtin import RegexPIIProvider
from deerflow.content_safety.input_guard_middleware import InputGuardMiddleware
from deerflow.content_safety.output_guard_middleware import OutputGuardMiddleware


class TestInputGuardMiddleware:
    def test_allows_clean_message(self):
        provider = RegexPIIProvider()
        mw = InputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="Hello world")]}
        result = mw.before_agent(state, None)
        assert result is None

    def test_masks_pii_in_message(self):
        provider = RegexPIIProvider(action="mask", detect_credit_cards=True)
        mw = InputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="My card is 4111111111111111")]}
        result = mw.before_agent(state, None)
        assert result is not None
        new_content = result["messages"][0].content
        assert "[CREDIT_CARD]" in new_content

    def test_block_action_denies(self):
        provider = RegexPIIProvider(action="block", detect_credit_cards=True)
        mw = InputGuardMiddleware(provider, block_on_harmful=True)
        state = {"messages": [HumanMessage(content="My card is 4111111111111111")]}
        result = mw.before_agent(state, None)
        assert result is not None
        assert "blocked by safety policy" in result["messages"][0].content

    def test_passes_when_block_on_harmful_disabled(self):
        provider = RegexPIIProvider(action="block", detect_credit_cards=True)
        mw = InputGuardMiddleware(provider, block_on_harmful=False)
        state = {"messages": [HumanMessage(content="My card is 4111111111111111")]}
        result = mw.before_agent(state, None)
        assert result is None

    def test_skips_when_no_user_message(self):
        provider = RegexPIIProvider()
        mw = InputGuardMiddleware(provider)
        state = {"messages": [AIMessage(content="Hello")]}
        result = mw.before_agent(state, None)
        assert result is None

    def test_handles_list_content(self):
        provider = RegexPIIProvider(action="mask", detect_phones=True)
        mw = InputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content=[{"type": "text", "text": "Call 13812345678"}])]}
        result = mw.before_agent(state, None)
        assert result is not None
        assert "[PHONE]" in result["messages"][0].content


class TestOutputGuardMiddleware:
    def test_allows_clean_response(self):
        provider = RegexPIIProvider()
        mw = OutputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="Hello!")]}
        result = mw.after_agent(state, None)
        assert result is None

    def test_masks_pii_in_response(self):
        provider = RegexPIIProvider(action="mask", detect_credit_cards=True)
        mw = OutputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="Your card 4111111111111111 is valid")]}
        result = mw.after_agent(state, None)
        assert result is not None
        assert "[CREDIT_CARD]" in result["messages"][0].content

    def test_blocks_harmful_response(self):
        provider = RegexPIIProvider(action="block", detect_credit_cards=True)
        mw = OutputGuardMiddleware(provider, block_on_harmful=True)
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="Your card 4111111111111111")]}
        result = mw.after_agent(state, None)
        assert result is not None
        assert "blocked by safety policy" in result["messages"][0].content

    def test_skips_when_no_ai_message(self):
        provider = RegexPIIProvider()
        mw = OutputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="hi")]}
        result = mw.after_agent(state, None)
        assert result is None

    def test_skips_empty_ai_content(self):
        provider = RegexPIIProvider()
        mw = OutputGuardMiddleware(provider)
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="")]}
        result = mw.after_agent(state, None)
        assert result is None
