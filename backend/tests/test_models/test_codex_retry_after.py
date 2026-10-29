"""Retry pacing for deerflow.models.openai_codex_provider.CodexChatModel.

The provider's retry loop used to pace every 429/500/529 on a hard-coded exponential
schedule, ignoring the server's hint. These tests pin the helper that now decides the
wait, and the loop that consumes it, without any network access.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.models.openai_codex_provider import _calc_backoff_ms
from deerflow.utils.retry_after import MAX_RETRY_AFTER_MS


def _status_error(status: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
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


@pytest.fixture
def fixed_clock(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr("deerflow.models.openai_codex_provider.time.time", lambda: now.timestamp())
    return now


@pytest.mark.parametrize(
    ("delta_seconds", "expected_ms"),
    [(-60, 0), (0, 0), (600, 600_000), (86400, MAX_RETRY_AFTER_MS), (86401, 2000)],
)
def test_http_date_retry_after_obeys_delay_boundaries(fixed_clock, delta_seconds, expected_ms):
    raw = format_datetime(fixed_clock + timedelta(seconds=delta_seconds), usegmt=True)
    error = _status_error(429, {"Retry-After": raw})
    assert _calc_backoff_ms(1, error) == expected_ms


@pytest.mark.parametrize(
    "raw",
    [
        "Thu, 01 Jan 2026 00:10:00 GMT",
        "Thursday, 01-Jan-26 00:10:00 GMT",
        "Thu Jan  1 00:10:00 2026",
    ],
)
def test_http_date_retry_after_accepts_http_date_formats_in_utc(fixed_clock, raw):
    error = _status_error(429, {"RETRY-AFTER": raw})
    assert _calc_backoff_ms(1, error) == 600_000


@pytest.mark.parametrize(
    "raw",
    ["Thu, 99 Jan 2026 00:10:00 GMT", "Thu, 01 Jan 2026 99:10:00 GMT", "Fri, 31 Dec 9999 23:59:59 GMT"],
)
def test_invalid_or_unbounded_http_dates_keep_local_backoff(fixed_clock, raw):
    error = _status_error(429, {"Retry-After": raw})
    assert _calc_backoff_ms(2, error) == 4000


@pytest.mark.parametrize(("milliseconds", "expected_ms"), [("1500", 1500), ("invalid", 600_000)])
def test_http_date_retry_after_preserves_millisecond_hint_precedence(fixed_clock, milliseconds, expected_ms):
    raw = format_datetime(fixed_clock + timedelta(minutes=10), usegmt=True)
    error = _status_error(429, {"retry-after-ms": milliseconds, "Retry-After": raw})
    assert _calc_backoff_ms(1, error) == expected_ms


def test_http_dates_are_not_accepted_as_millisecond_hints(fixed_clock):
    raw = format_datetime(fixed_clock + timedelta(minutes=10), usegmt=True)
    error = _status_error(429, {"retry-after-ms": raw})
    assert _calc_backoff_ms(1, error) == 2000


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [429, 500, 529])
async def test_public_invocation_waits_for_http_date_retry_after(monkeypatch, fixed_clock, mode, status):
    from deerflow.models import openai_codex_provider as provider

    model = _make_model(retry_max_attempts=2)
    calls = []
    sleeps = []
    raw = format_datetime(fixed_clock + timedelta(minutes=10), usegmt=True)

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"Retry-After": raw}, json={"error": "synthetic throttle"})
        event = {
            "type": "response.completed",
            "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "recovered"}]}]},
        }
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {json.dumps(event)}\n\n")

    client_class = httpx.Client
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(respond), trust_env=False, **kwargs))
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)

    result = model.invoke("hi") if mode == "sync" else await model.ainvoke("hi")

    assert result.content == "recovered"
    assert len(calls) == 2
    assert sleeps == [600.0]


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
