"""Tests for ClaudeChatModel._apply_thinking_budget.

Anthropic rejects extended-thinking requests whose budget_tokens is below
1024 or not smaller than max_tokens with an HTTP 400. The provider must fail
those payloads locally with an actionable error instead of forwarding a
request the API is guaranteed to reject, and must clamp the automatic 80%
budget up to the provider minimum when max_tokens leaves room for it.
"""

from unittest import mock

import pytest

from deerflow.models.claude_provider import ClaudeChatModel


def _make_model() -> ClaudeChatModel:
    """Return a minimal ClaudeChatModel instance without network calls."""
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(
            model="claude-sonnet-4-6",
            anthropic_api_key="sk-ant-fake",  # type: ignore[call-arg]
        )
    m._is_oauth = False
    return m


@pytest.fixture()
def model() -> ClaudeChatModel:
    return _make_model()


# ---------------------------------------------------------------------------
# Automatic budget (80% of max_tokens)
# ---------------------------------------------------------------------------


def test_auto_budget_above_minimum_unchanged(model):
    payload: dict = {"thinking": {"type": "enabled"}, "max_tokens": 8192}
    model._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == int(8192 * 0.8)


def test_auto_budget_defaults_max_tokens(model):
    payload: dict = {"thinking": {"type": "enabled"}}
    model._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == int(8192 * 0.8)


def test_auto_budget_clamped_to_provider_minimum(model):
    # 0.8 * 1200 = 960 < 1024, but max_tokens leaves room for the floor.
    payload: dict = {"thinking": {"type": "enabled"}, "max_tokens": 1200}
    model._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 1024


def test_auto_budget_clamped_just_above_floor(model):
    payload: dict = {"thinking": {"type": "enabled"}, "max_tokens": 1025}
    model._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 1024


def test_auto_budget_rejects_max_tokens_at_floor(model):
    # No valid budget exists when max_tokens == 1024 (1024 <= budget < 1024).
    payload: dict = {"thinking": {"type": "enabled"}, "max_tokens": 1024}
    with pytest.raises(ValueError, match="max_tokens"):
        model._apply_thinking_budget(payload)


def test_auto_budget_rejects_tiny_max_tokens(model):
    # The issue repro: 0.8 * 512 = 409 used to be forwarded and HTTP 400'd.
    payload: dict = {"thinking": {"type": "enabled"}, "max_tokens": 512}
    with pytest.raises(ValueError, match="max_tokens"):
        model._apply_thinking_budget(payload)


# ---------------------------------------------------------------------------
# Explicit budget passthrough
# ---------------------------------------------------------------------------


def test_explicit_valid_budget_untouched(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": 1024}, "max_tokens": 2048}
    model._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 1024


def test_explicit_budget_below_minimum_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": 409}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


def test_explicit_budget_one_below_minimum_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": 1023}, "max_tokens": 2048}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


def test_explicit_budget_equal_max_tokens_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": 8192}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


def test_explicit_budget_above_max_tokens_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": 9000}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


def test_explicit_non_integer_budget_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": "2048"}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


def test_explicit_boolean_budget_rejected(model):
    payload: dict = {"thinking": {"type": "enabled", "budget_tokens": True}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        model._apply_thinking_budget(payload)


# ---------------------------------------------------------------------------
# Untouched shapes
# ---------------------------------------------------------------------------


def test_thinking_disabled_untouched(model):
    payload: dict = {"thinking": {"type": "disabled"}, "max_tokens": 512}
    model._apply_thinking_budget(payload)
    assert payload["thinking"] == {"type": "disabled"}


def test_no_thinking_block_untouched(model):
    payload: dict = {"max_tokens": 512}
    model._apply_thinking_budget(payload)
    assert "thinking" not in payload
