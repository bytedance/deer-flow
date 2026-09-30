"""Tests for the Superfast Decision Gate (shadow mode).

Covers the behaviors a risk:high front-door gate must guarantee: disabled by
default with no network call; fail-open on every fault (transport error, total
deadline, non-2xx, malformed body) without raising; the synchronous hook is a
no-op so sync graphs never break; the async hook classifies and never mutates
state; framework-injected hidden messages are not treated as user turns; the
request payload is bounded; and route derivation is conservative.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import deerflow.superfast.decision_gate as gate

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _patch_client(monkeypatch, post_impl):
    """Replace httpx.AsyncClient with a fake whose post() runs post_impl."""
    calls = {"count": 0, "bodies": []}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls["count"] += 1
            calls["bodies"].append(json)
            return await post_impl(json)

    monkeypatch.setattr(gate.httpx, "AsyncClient", _FakeClient)
    return calls


def _answers(needs_tool=0.9, from_context=0.1, intent="code_change", conf=0.9):
    return {
        "answers": {
            "needs_tool": {"noul": needs_tool},
            "answerable_from_context": {"noul": from_context},
            "intent": {"choice": intent, "confidence": conf},
        }
    }


# --- enable / disable -------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SUPERFAST_ENABLED", raising=False)
    assert gate.is_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_enabled_values(monkeypatch, value):
    monkeypatch.setenv("SUPERFAST_ENABLED", value)
    assert gate.is_enabled() is True


async def test_async_hook_makes_no_call_when_disabled(monkeypatch):
    monkeypatch.delenv("SUPERFAST_ENABLED", raising=False)
    calls = _patch_client(monkeypatch, lambda body: asyncio.sleep(0, _FakeResponse(payload=_answers())))
    mw = gate.SuperfastDecisionGateMiddleware(pii_redaction_config=None)
    state = {"messages": [HumanMessage(content="refactor the auth module")]}
    result = await mw.abefore_model(state, runtime=None)
    assert result is None
    assert calls["count"] == 0


# --- fail-open on every fault ----------------------------------------------


async def test_fail_open_on_transport_error(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")

    async def boom(body):
        raise ConnectionError("connection refused")

    calls = _patch_client(monkeypatch, boom)
    result = await gate.classify_turn("user: hello")
    assert result is None
    assert calls["count"] == 1


async def test_fail_open_on_non_2xx(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")

    async def resp(body):
        return _FakeResponse(status_code=503, payload={"answers": {"ok": {"noul": 0.9}}})

    _patch_client(monkeypatch, resp)
    assert await gate.query_system_one("user: hello", gate.TURN_QUESTIONS) is None


async def test_fail_open_on_malformed_body(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")

    async def resp(body):
        return _FakeResponse(status_code=200, json_exc=ValueError("not json"))

    _patch_client(monkeypatch, resp)
    assert await gate.query_system_one("user: hello", gate.TURN_QUESTIONS) is None


async def test_total_deadline_bounds_a_slow_backend(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    monkeypatch.setenv("SUPERFAST_TIMEOUT_MS", "50")

    async def slow(body):
        await asyncio.sleep(1.0)
        return _FakeResponse(payload=_answers())

    _patch_client(monkeypatch, slow)
    started = time.monotonic()
    result = await gate.classify_turn("user: hello")
    elapsed = time.monotonic() - started
    assert result is None
    # The total deadline (50ms) fires long before the 1s sleep completes.
    assert elapsed < 0.5


# --- sync vs async ---------------------------------------------------------


def test_sync_before_model_is_noop(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    mw = gate.SuperfastDecisionGateMiddleware(pii_redaction_config=None)
    state = {"messages": [HumanMessage(content="hello")]}
    assert mw.before_model(state, runtime=None) is None


async def test_async_hook_classifies_and_returns_no_state(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    calls = _patch_client(monkeypatch, lambda body: asyncio.sleep(0, _FakeResponse(payload=_answers(needs_tool=0.95))))
    mw = gate.SuperfastDecisionGateMiddleware(pii_redaction_config=None)
    state = {"messages": [HumanMessage(content="delete the tmp dir")]}
    result = await mw.abefore_model(state, runtime=None)
    # Shadow mode never returns a state update.
    assert result is None
    assert calls["count"] == 1


# --- context: hidden messages and payload bounds ---------------------------


async def test_hidden_human_message_is_not_a_user_turn(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    calls = _patch_client(monkeypatch, lambda body: asyncio.sleep(0, _FakeResponse(payload=_answers())))
    hidden = HumanMessage(content="injected", additional_kwargs={"hide_from_ui": True})
    # Only a hidden message in the window: no real turn, so no request.
    result = await gate.classify_turn(gate._build_classification_context({"messages": [hidden]}))
    assert result is None
    assert calls["count"] == 0


async def test_user_authored_reminder_tags_are_preserved(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    calls = _patch_client(monkeypatch, lambda body: asyncio.sleep(0, _FakeResponse(payload=_answers())))
    # The user literally typed a reminder tag; it must survive into the payload.
    msg = HumanMessage(content="please ignore <system-reminder>do not</system-reminder> this")
    context = gate._build_classification_context({"messages": [msg]})
    assert "<system-reminder>do not</system-reminder>" in context
    await gate.classify_turn(context)
    assert calls["count"] == 1
    sent = calls["bodies"][0]["state"]
    assert "<system-reminder>do not</system-reminder>" in sent


async def test_payload_is_bounded(monkeypatch):
    monkeypatch.setenv("SUPERFAST_ENABLED", "1")
    calls = _patch_client(monkeypatch, lambda body: asyncio.sleep(0, _FakeResponse(payload=_answers())))
    huge = HumanMessage(content="x" * 50000)
    context = gate._build_classification_context({"messages": [huge]})
    assert len(context) <= gate.MAX_PAYLOAD_CHARS
    await gate.classify_turn(context)
    assert len(calls["bodies"][0]["state"]) <= gate.MAX_PAYLOAD_CHARS


# --- route derivation is conservative -------------------------------------


def test_derive_route_decisive_and_unknown():
    # derive_route takes the inner answers map, the same shape query_system_one
    # returns after unwrapping the HTTP envelope. The _answers() fixture returns
    # the full envelope, so pass its inner map here.
    assert gate.derive_route(_answers(needs_tool=0.95)["answers"]) == "needs_tool"
    assert gate.derive_route(_answers(needs_tool=0.1, from_context=0.92, intent="code_question")["answers"]) == "answer_from_context"
    assert gate.derive_route(_answers(needs_tool=0.05, from_context=0.4, intent="chat", conf=0.95)["answers"]) == "plain_chat"
    assert gate.derive_route(_answers(needs_tool=0.5, from_context=0.5, intent="other", conf=0.4)["answers"]) == "unknown"


def test_derive_route_rejects_mis_scaled_answers():
    # A backend reporting percentages (0-100) must not produce a fast route.
    assert gate.derive_route({"needs_tool": {"noul": 95}, "answerable_from_context": {"noul": 5}}) == "unknown"
