"""Tests for Claude extended-thinking request normalization."""

import json
from unittest import mock

import anthropic
import httpx
import pytest

from deerflow.models.claude_provider import ClaudeChatModel

INTERLEAVED_BETA = "interleaved-thinking-2025-05-14"
TOOLS = [{"name": "lookup", "description": "Look up a value", "input_schema": {"type": "object", "properties": {}}}]


def _make_model(**kwargs) -> ClaudeChatModel:
    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        model = ClaudeChatModel(model=kwargs.pop("model", "claude-sonnet-4-5"), anthropic_api_key="sk-ant-fake", enable_prompt_caching=False, **kwargs)
    model._is_oauth = False
    return model


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


def test_auto_budget_defaults_max_tokens():
    payload = {"thinking": {"type": "enabled"}}
    _make_model()._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 6553


@pytest.mark.parametrize("max_tokens", [1025, 1200])
def test_auto_budget_clamped_near_minimum(max_tokens):
    payload = {"thinking": {"type": "enabled"}, "max_tokens": max_tokens}
    _make_model()._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 1024


@pytest.mark.parametrize("max_tokens", [1024, 0, -1, True, False, "8192", 8192.5, None])
def test_auto_budget_rejects_invalid_max_tokens(max_tokens):
    payload = {"thinking": {"type": "enabled"}, "max_tokens": max_tokens}
    with pytest.raises(ValueError, match="max_tokens"):
        _make_model()._apply_thinking_budget(payload)


def test_explicit_minimum_budget_is_valid():
    payload = {"thinking": {"type": "enabled", "budget_tokens": 1024}, "max_tokens": 2048}
    _make_model()._apply_thinking_budget(payload)
    assert payload["thinking"]["budget_tokens"] == 1024


@pytest.mark.parametrize("budget_tokens", [1023, 9000, "2048", True, False, 0, "", 0.0])
def test_explicit_invalid_budgets_are_rejected(budget_tokens):
    payload = {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}, "max_tokens": 8192}
    with pytest.raises(ValueError, match="budget_tokens"):
        _make_model()._apply_thinking_budget(payload)


def test_no_thinking_block_is_untouched():
    payload = {"max_tokens": 512}
    _make_model()._apply_thinking_budget(payload)
    assert payload == {"max_tokens": 512}


def test_adaptive_thinking_is_untouched():
    payload = {"thinking": {"type": "adaptive"}, "max_tokens": 512}
    _make_model()._apply_thinking_budget(payload)
    assert payload == {"thinking": {"type": "adaptive"}, "max_tokens": 512}


def test_auto_budget_recomputed_for_each_request():
    model = _make_model(thinking={"type": "enabled"})
    first = model._get_request_payload("hello", max_tokens=16384)
    second = model._get_request_payload("hello", max_tokens=2048)
    assert first["thinking"]["budget_tokens"] == 13107
    assert second["thinking"]["budget_tokens"] == 1638
    assert model.thinking == {"type": "enabled"}


@pytest.mark.parametrize(
    "model_name", ["claude-sonnet-4-0", "claude-sonnet-4-20250514", "claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-sonnet-4-6", "claude-opus-4-0", "claude-opus-4-20250514", "claude-opus-4-1-20250805", "claude-opus-4-5-20251101"]
)
def test_interleaved_thinking_allows_budget_above_max_tokens(model_name):
    model = _make_model(model=model_name, thinking={"type": "enabled", "budget_tokens": 9000}, max_tokens=8192, betas=[INTERLEAVED_BETA])
    payload = model._get_request_payload("hello", tools=TOOLS)
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 9000}
    assert payload["max_tokens"] == 8192
    assert payload["betas"] == [INTERLEAVED_BETA]
    assert model.thinking == {"type": "enabled", "budget_tokens": 9000}


def test_interleaved_thinking_allows_budget_equal_to_max_tokens():
    model = _make_model(thinking={"type": "enabled", "budget_tokens": 8192}, max_tokens=8192, betas=[INTERLEAVED_BETA])
    payload = model._get_request_payload("hello", tools=TOOLS)
    assert payload["thinking"]["budget_tokens"] == 8192


@pytest.mark.parametrize(
    "kwargs", [{"betas": []}, {"betas": ["unrelated-beta"]}, {"betas": [INTERLEAVED_BETA + "-other"]}, {"tools": []}, {"tools": None}, {"model": "claude-haiku-4-5"}, {"model": "claude-opus-4-6"}, {"model": "claude-sonnet-4-7"}]
)
def test_upper_bound_still_applies_without_supported_interleaving(kwargs):
    model = _make_model(thinking={"type": "enabled", "budget_tokens": 9000}, max_tokens=8192, betas=[INTERLEAVED_BETA])
    request_kwargs = {"tools": TOOLS, **kwargs}
    with pytest.raises(ValueError, match="strictly less than max_tokens"):
        model._get_request_payload("hello", **request_kwargs)


@pytest.mark.parametrize("budget_tokens", [None, 1024])
def test_interleaved_thinking_allows_small_output_limit(budget_tokens):
    thinking = {"type": "enabled", "budget_tokens": budget_tokens}
    model = _make_model(thinking=thinking, max_tokens=512, betas=[INTERLEAVED_BETA])
    payload = model._get_request_payload("hello", tools=TOOLS)
    assert payload["thinking"]["budget_tokens"] == 1024
    assert model.thinking == thinking


@pytest.mark.parametrize("max_tokens", [0, -1, True, "8192", 8192.5])
def test_interleaving_still_requires_positive_integer_max_tokens(max_tokens):
    model = _make_model(thinking={"type": "enabled", "budget_tokens": 9000}, betas=[INTERLEAVED_BETA])
    with pytest.raises(ValueError, match="max_tokens"):
        model._get_request_payload("hello", tools=TOOLS, max_tokens=max_tokens)


@pytest.mark.parametrize("budget_tokens", [1023, True, "9000"])
def test_interleaving_still_requires_integer_budget_at_least_minimum(budget_tokens):
    model = _make_model(thinking={"type": "enabled", "budget_tokens": budget_tokens}, max_tokens=8192, betas=[INTERLEAVED_BETA])
    with pytest.raises(ValueError, match="budget_tokens"):
        model._get_request_payload("hello", tools=TOOLS)


@pytest.mark.parametrize(
    ("model_kwargs", "request_kwargs", "expected_beta", "allowed"),
    [
        ({"betas": [INTERLEAVED_BETA]}, {}, INTERLEAVED_BETA, True),
        ({"default_headers": {"anthropic-beta": "oauth-2025-04-20, " + INTERLEAVED_BETA}}, {}, "oauth-2025-04-20, " + INTERLEAVED_BETA, True),
        ({}, {"extra_headers": {"Anthropic-Beta": INTERLEAVED_BETA}}, INTERLEAVED_BETA, True),
        ({"default_headers": {"anthropic-beta": INTERLEAVED_BETA}, "betas": []}, {}, "", False),
        ({"betas": [INTERLEAVED_BETA]}, {"extra_headers": {"anthropic-beta": "unrelated-beta"}}, "unrelated-beta", False),
        ({"default_headers": {"anthropic-beta": INTERLEAVED_BETA}}, {"extra_headers": {"anthropic-beta": anthropic.Omit()}}, None, False),
    ],
)
def test_interleaved_beta_matches_sdk_header_precedence(model_kwargs, request_kwargs, expected_beta, allowed):
    captured = []

    def respond(request):
        captured.append((json.loads(request.content), request.headers.get("anthropic-beta")))
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = _make_model(max_tokens=8192, thinking={"type": "enabled", "budget_tokens": 9000}, **model_kwargs)
        model.__dict__["_client"] = anthropic.Anthropic(api_key="sk-ant-fake", http_client=client, default_headers=model.default_headers)
        if allowed:
            payload = model._get_request_payload("hello", tools=TOOLS, **request_kwargs)
            assert model._create(payload).content[0].text == "ok"
            body, beta = captured[0]
            assert body["thinking"]["budget_tokens"] == 9000
            assert beta == expected_beta
        else:
            with pytest.raises(ValueError, match="strictly less than max_tokens"):
                model._get_request_payload("hello", tools=TOOLS, **request_kwargs)
            assert captured == []


def test_manual_budget_opt_out_is_unchanged():
    model = _make_model(thinking={"type": "enabled", "budget_tokens": 409}, max_tokens=512, auto_thinking_budget=False)
    payload = model._get_request_payload("hello")
    assert payload["thinking"]["budget_tokens"] == 409
