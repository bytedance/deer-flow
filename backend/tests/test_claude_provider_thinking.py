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


def test_explicit_budget_is_left_unchanged():
    model = _make_model()
    payload = {"thinking": {"type": "enabled", "budget_tokens": 2048}, "max_tokens": 4096}

    model._apply_thinking_budget(payload)

    assert payload["thinking"]["budget_tokens"] == 2048


@pytest.mark.parametrize("budget_tokens", [512, 4096])
def test_explicit_budget_must_fit_anthropic_limits(budget_tokens):
    model = _make_model()
    payload = {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}, "max_tokens": 4096}

    with pytest.raises(ValueError, match="between 1024 and max_tokens"):
        model._apply_thinking_budget(payload)
