"""Tests for Claude extended-thinking request normalization."""

from unittest import mock

import pytest

from deerflow.models.claude_provider import ClaudeChatModel


def _make_model() -> ClaudeChatModel:
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        return ClaudeChatModel(
            model="claude-sonnet-4-5",
            anthropic_api_key="sk-ant-fake",  # type: ignore[call-arg]
        )


def test_auto_budget_rejects_impossible_max_tokens():
    model = _make_model()
    payload = {"thinking": {"type": "enabled"}, "max_tokens": 512}

    with pytest.raises(ValueError, match="max_tokens > 1024"):
        model._apply_thinking_budget(payload)


def test_auto_budget_clamps_to_minimum_when_max_tokens_allows_it():
    model = _make_model()
    payload = {"thinking": {"type": "enabled"}, "max_tokens": 1100}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 1024


def test_auto_budget_uses_eighty_percent_for_large_max_tokens():
    model = _make_model()
    payload = {"thinking": {"type": "enabled"}, "max_tokens": 8192}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 6553


def test_null_budget_is_treated_as_unset():
    model = _make_model()
    payload = {"thinking": {"type": "enabled", "budget_tokens": None}, "max_tokens": 8192}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 6553


def test_disabled_thinking_does_not_validate_small_max_tokens():
    model = _make_model()
    payload = {"thinking": {"type": "disabled"}, "max_tokens": 100}

    model._apply_thinking_budget(payload)

    assert payload == {"thinking": {"type": "disabled"}, "max_tokens": 100}


def test_explicit_budget_is_left_unchanged():
    model = _make_model()
    payload = {"thinking": {"type": "enabled", "budget_tokens": 2048}, "max_tokens": 4096}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 2048


@pytest.mark.parametrize("budget_tokens", [512, 4096])
def test_explicit_budget_must_fit_anthropic_limits(budget_tokens):
    model = _make_model()
    payload = {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}, "max_tokens": 4096}

    with pytest.raises(ValueError, match="at least 1024 and strictly less than max_tokens"):
        model._apply_thinking_budget(payload)


def test_auto_budget_does_not_mutate_shared_thinking_config():
    model = _make_model()
    thinking = {"type": "enabled"}
    payload = {"thinking": thinking, "max_tokens": 8192}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 6553
    assert thinking == {"type": "enabled"}
