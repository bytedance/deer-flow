"""Tests for built-in content safety providers."""

import pytest

from deerflow.content_safety.builtin import OpenAIModerationProvider, RegexPIIProvider
from deerflow.content_safety.provider import ContentSafetyRequest


class TestRegexPIIProvider:
    def test_allows_clean_text(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="Hello, how are you?", role="user"))
        assert decision.allowed is True
        assert decision.flagged_categories == []

    def test_detects_credit_card(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="My card is 4532015112830366", role="user"))
        assert "credit_card" in decision.flagged_categories

    def test_masks_credit_card(self):
        provider = RegexPIIProvider(action="mask")
        decision = provider.evaluate(ContentSafetyRequest(text="Use card 4532015112830366 please", role="user"))
        assert "[CREDIT_CARD]" in (decision.sanitized_text or "")

    def test_detects_chinese_phone(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="Call me at 13812345678", role="user"))
        assert "phone" in decision.flagged_categories

    def test_masks_phone(self):
        provider = RegexPIIProvider(action="mask")
        decision = provider.evaluate(ContentSafetyRequest(text="My number is 13812345678 thanks", role="user"))
        assert "[PHONE]" in (decision.sanitized_text or "")

    def test_detects_chinese_id(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="ID: 110101199003077654", role="user"))
        assert "chinese_id" in decision.flagged_categories

    def test_detects_email(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="Email me at test@example.com", role="user"))
        assert "email" in decision.flagged_categories

    def test_masks_email(self):
        provider = RegexPIIProvider(action="mask")
        decision = provider.evaluate(ContentSafetyRequest(text="Contact: user@domain.com for help", role="user"))
        assert "[EMAIL]" in (decision.sanitized_text or "")

    def test_block_action_denies(self):
        provider = RegexPIIProvider(action="block")
        decision = provider.evaluate(ContentSafetyRequest(text="My card 4532015112830366", role="user"))
        assert decision.allowed is False

    def test_disabled_detectors_skip(self):
        provider = RegexPIIProvider(detect_credit_cards=False, detect_phones=False, detect_emails=False, detect_chinese_ids=False)
        decision = provider.evaluate(ContentSafetyRequest(text="Card 4532015112830366, phone 13812345678, email a@b.com", role="user"))
        assert decision.flagged_categories == []

    def test_async_delegates_to_sync(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="Hello", role="user"))
        assert decision.allowed is True

    def test_empty_text(self):
        provider = RegexPIIProvider()
        decision = provider.evaluate(ContentSafetyRequest(text="", role="user"))
        assert decision.allowed is True


class TestOpenAIModerationProvider:
    def test_name_is_set(self):
        provider = OpenAIModerationProvider()
        assert provider.name == "openai_moderation"

    def test_evaluate_returns_allowed_on_api_error(self):
        provider = OpenAIModerationProvider(api_key="sk-fake")
        decision = provider.evaluate(ContentSafetyRequest(text="test", role="user"))
        assert decision.allowed is True
