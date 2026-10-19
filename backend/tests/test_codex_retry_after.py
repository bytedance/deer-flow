"""Retry pacing for deerflow.models.openai_codex_provider.CodexChatModel.

The provider's retry loop used to pace every 429/500/529 on a hard-coded exponential
schedule, ignoring the server's hint. These tests pin the helper that now decides the
wait, and the loop that consumes it, without any network access.
"""

from __future__ import annotations

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.models.openai_codex_provider import _calc_backoff_ms
from deerflow.utils.retry_after import MAX_RETRY_AFTER_MS


def _status_error(
    status: int, headers: dict[str, str] | None = None
) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid/responses")
    return httpx.HTTPStatusError(
        "boom",
        request=request,
        response=httpx.Response(status, headers=headers or {}, request=request),
    )


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_without_a_response_it_keeps_the_local_schedule():
    error = RuntimeError("no response here")
    assert _calc_backoff_ms(1, error) == 2000
    assert _calc_backoff_ms(3, error) == 8000


def test_without_an_error_it_keeps_the_local_schedule():
    assert _calc_backoff_ms(1) == 2000
    assert _calc_backoff_ms(2) == 4000


def test_retry_after_seconds_is_honoured():
    error = _status_error(429, {"Retry-After": "45"})
    assert _calc_backoff_ms(1, error) == 45_000


def test_retry_after_ms_is_preferred_over_seconds():
    error = _status_error(429, {"retry-after-ms": "1500", "Retry-After": "45"})
    assert _calc_backoff_ms(1, error) == 1500


def test_header_lookup_is_case_insensitive():
    error = _status_error(429, {"RETRY-AFTER": "7"})
    assert _calc_backoff_ms(1, error) == 7000


@pytest.mark.parametrize("value", ["not-a-number", "", "nan", "inf"])
def test_unusable_hints_fall_back_to_the_local_schedule(value: str):
    error = _status_error(429, {"Retry-After": value})
    assert _calc_backoff_ms(2, error) == 4000


def test_a_negative_hint_clamps_to_zero_like_the_claude_provider():
    # utils.retry_after treats a finite negative value as 0 rather than dropping the hint;
    # the Codex provider now shares that contract instead of inventing its own.
    error = _status_error(429, {"Retry-After": "-3"})
    assert _calc_backoff_ms(2, error) == 0


def test_a_hint_beyond_the_bound_falls_back_to_the_local_schedule():
    # 25 hours, one past the 24h bound.
    error = _status_error(429, {"Retry-After": str(25 * 60 * 60)})
    assert _calc_backoff_ms(1, error) == 2000


def test_the_bound_itself_is_accepted():
    seconds = MAX_RETRY_AFTER_MS // 1000
    error = _status_error(429, {"Retry-After": str(seconds)})
    assert _calc_backoff_ms(1, error) == MAX_RETRY_AFTER_MS


def test_a_zero_hint_means_retry_immediately():
    error = _status_error(429, {"Retry-After": "0"})
    assert _calc_backoff_ms(1, error) == 0


# ---------------------------------------------------------------------------
# The loop, through the public model surface
# ---------------------------------------------------------------------------


def _make_model(**kwargs):
    from unittest.mock import patch

    from deerflow.models.credential_loader import CodexCliCredential
    from deerflow.models.openai_codex_provider import CodexChatModel

    cred = CodexCliCredential(access_token="tok-test", account_id="acc-test")
    with patch(
        "deerflow.models.openai_codex_provider.load_codex_cli_credential",
        return_value=cred,
    ):
        return CodexChatModel(model="gpt-5.4", reasoning_effort="medium", **kwargs)


def test_loop_sleeps_for_the_server_hint(monkeypatch):
    model = _make_model(retry_max_attempts=2)
    sleeps: list[float] = []
    errors = [_status_error(429, {"Retry-After": "45"})]

    def fake_stream(headers, payload):
        if errors:
            raise errors.pop()
        return {"ok": True}

    monkeypatch.setattr(model, "_stream_response", fake_stream)
    monkeypatch.setattr(
        "deerflow.models.openai_codex_provider.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    assert model._call_codex_api([HumanMessage(content="hi")]) == {"ok": True}
    assert sleeps == [45.0]


def test_loop_uses_local_backoff_without_a_hint(monkeypatch):
    model = _make_model(retry_max_attempts=2)
    sleeps: list[float] = []
    errors = [_status_error(429)]

    def fake_stream(headers, payload):
        if errors:
            raise errors.pop()
        return {"ok": True}

    monkeypatch.setattr(model, "_stream_response", fake_stream)
    monkeypatch.setattr(
        "deerflow.models.openai_codex_provider.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    assert model._call_codex_api([HumanMessage(content="hi")]) == {"ok": True}
    assert sleeps == [2.0]


def test_loop_does_not_retry_a_400(monkeypatch):
    model = _make_model(retry_max_attempts=3)
    sleeps: list[float] = []

    def fake_stream(headers, payload):
        raise _status_error(400)

    monkeypatch.setattr(model, "_stream_response", fake_stream)
    monkeypatch.setattr(
        "deerflow.models.openai_codex_provider.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    with pytest.raises(httpx.HTTPStatusError):
        model._call_codex_api([HumanMessage(content="hi")])
    assert sleeps == []
