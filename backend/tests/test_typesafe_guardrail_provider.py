"""Tests for the TypeSafe (Jev) guardrail provider.

Every network assertion goes through ``httpx.MockTransport`` injected as a
transport *factory*: the provider owns the client for exactly one evaluation,
and httpx closes an injected transport when its client closes, so a shared
instance would be dead on the second call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.guardrails.provider import GuardrailRequest
from deerflow.guardrails.typesafe import TypeSafeGuardrailError, TypeSafeGuardrailProvider

_API_KEY = "typesafe-test-key"
_QUESTION_ID = "risky_tool_call"


def _noul(probability: float = 0.9, model: str = "jev-1.13.0") -> dict:
    return {"model": model, "answers": {_QUESTION_ID: {"type": "noul", "noul": probability}}, "usage": {"input_tokens": 12, "output_tokens": 2}}


class _Server:
    """Fake TypeSafe endpoint that records every request it receives."""

    def __init__(self, responder=None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder or (lambda request: httpx.Response(200, json=_noul()))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def count(self) -> int:
        return len(self.requests)

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


class _SlowSyncStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], delay: float) -> None:
        self._chunks = chunks
        self._delay = delay

    def __iter__(self):
        for chunk in self._chunks:
            yield chunk
            time.sleep(self._delay)


class _SlowAsyncStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], delay: float) -> None:
        self._chunks = chunks
        self._delay = delay

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk
            await asyncio.sleep(self._delay)


def _slow_body_chunks(delay: float) -> tuple[list[bytes], float]:
    payload = json.dumps(_noul()).encode()
    return [payload[: len(payload) // 2], payload[len(payload) // 2 :]], delay


def _provider(server: _Server | None = None, **kwargs) -> TypeSafeGuardrailProvider:
    kwargs.setdefault("api_key", _API_KEY)
    kwargs.setdefault("transport_factory", (server or _Server()).transport)
    return TypeSafeGuardrailProvider(**kwargs)


def _request(tool_name: str = "bash", tool_input: dict | None = None) -> GuardrailRequest:
    if tool_input is None:
        tool_input = {"command": "rm -rf /tmp/scratch"}
    return GuardrailRequest(tool_name=tool_name, tool_input=tool_input)


def _expected_digest(tool_name: str, arguments: dict) -> str:
    arguments_text = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    state_text = json.dumps({"tool_call": {"name": tool_name, "arguments": arguments_text}}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(state_text.encode("utf-8")).hexdigest()[:16]


class _FakeRuntime:
    def __init__(self, context: dict | None = None) -> None:
        self.context = context or {}


class _FakeJournal:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record_middleware(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _tool_call_request(tool_name: str = "bash", args: dict | None = None, context: dict | None = None):
    request = MagicMock()
    request.tool_call = {"name": tool_name, "args": args if args is not None else {"command": "rm -rf /tmp/scratch"}, "id": "call_1"}
    request.runtime = _FakeRuntime(context)
    return request


# --- verdicts -------------------------------------------------------------


class TestVerdict:
    def test_probability_at_threshold_denies(self):
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.5)))
        decision = _provider(server, threshold=0.5).evaluate(_request())
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.tool_call_risky"
        assert server.count == 1

    def test_probability_below_threshold_allows(self):
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.4999999)))
        decision = _provider(server, threshold=0.5).evaluate(_request())
        assert decision.allow is True
        assert decision.reasons[0].code == "typesafe.allowed"

    def test_reason_message_carries_the_replay_fields(self):
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.982147216796875)))
        decision = _provider(server, threshold=0.5).evaluate(_request())
        message = decision.reasons[0].message
        # repr(): the recorded threshold must replay the recorded probability to
        # the same verdict, so neither value may be rounded for display.
        assert message.startswith("typesafe.tool_call_risky: p=0.982147216796875 >= t=0.5 model=jev-1.13.0 cached=false digest=")
        assert message.endswith("policy=deerflow.guardrails.typesafe@1.1.0")
        assert decision.metadata == {"probability": 0.982147216796875, "threshold": 0.5, "model": "jev-1.13.0", "cached": False, "state_digest": decision.metadata["state_digest"]}
        assert decision.policy_id == "deerflow.guardrails.typesafe"

    def test_request_shape_and_state_digest(self):
        server = _Server()
        decision = _provider(server).evaluate(_request("write_file", {"path": "a.txt", "content": "héllo"}))
        body = server.bodies()[0]
        assert body["model"] == "jev-latest"
        assert body["state"] == {"tool_call": {"name": "write_file", "arguments": '{"content":"héllo","path":"a.txt"}'}}
        assert body["questions"][_QUESTION_ID]["type"] == "noul"
        assert body["questions"][_QUESTION_ID]["criteria"].keys() == {"true", "false"}
        assert server.requests[0].headers["authorization"] == f"Bearer {_API_KEY}"
        assert decision.metadata["state_digest"] == _expected_digest("write_file", {"path": "a.txt", "content": "héllo"})


# --- local decisions (no network) -----------------------------------------


class TestLocalDecisions:
    def test_tools_allowlist_skips_unprobed_tools(self):
        server = _Server()
        provider = _provider(server, tools=["bash"])
        for _ in range(2):
            decision = provider.evaluate(_request("read_file", {"path": "/etc/shadow"}))
            assert decision.allow is True
            assert decision.reasons[0].code == "typesafe.tool_not_probed"
        assert server.count == 0

    def test_tools_allowlist_still_probes_listed_tools(self):
        server = _Server()
        decision = _provider(server, tools=["bash"]).evaluate(_request("bash"))
        assert decision.allow is False
        assert server.count == 1

    def test_over_limit_arguments_are_denied_without_a_request(self):
        server = _Server()
        arguments = {"path": "a.txt", "content": "x" * 500}
        decision = _provider(server, max_state_chars=64).evaluate(_request("write_file", arguments))
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.state_unusable"
        assert "cause=too_large" in decision.reasons[0].message
        assert "limit=64" in decision.reasons[0].message
        assert decision.metadata["limit"] == 64 and decision.metadata["length"] > 64
        # The digest identifies the state that would have been sent, so a replay
        # can confirm which call was refused even though nothing left the process.
        assert decision.metadata["digest"] == _expected_digest("write_file", arguments)
        assert server.count == 0

    def test_write_file_content_sorted_past_the_limit_is_denied(self):
        """Sorted keys put ``content`` before ``path``: a truncated state would
        hide the very argument that makes the call dangerous."""
        server = _Server()
        decision = _provider(server, max_state_chars=120).evaluate(_request("write_file", {"path": "important.txt", "content": "y" * 400}))
        assert decision.allow is False
        assert "cause=too_large" in decision.reasons[0].message
        assert server.count == 0

    @pytest.mark.parametrize(
        ("arguments", "reason"),
        [
            ({"data": b"raw-bytes"}, "TypeError"),
            ({1: "int-key"}, "TypeError"),
            ({"n": float("nan")}, "ValueError"),
            ({"n": float("inf")}, "ValueError"),
        ],
    )
    def test_unserializable_arguments_are_denied_locally(self, arguments, reason):
        server = _Server()
        decision = _provider(server).evaluate(_request("bash", arguments))
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.state_unusable"
        assert f"cause=unserializable reason={reason} digest=unavailable" in decision.reasons[0].message
        assert server.count == 0

    def test_non_dict_arguments_are_denied_locally(self):
        server = _Server()
        decision = _provider(server).evaluate(_request("bash", ["rm", "-rf"]))
        assert decision.allow is False
        assert "cause=unserializable reason=TypeError" in decision.reasons[0].message
        assert server.count == 0

    def test_lone_surrogate_arguments_are_denied_locally(self):
        """A lone surrogate — what ``json.loads`` yields for ``"\\ud800"`` — is a str
        that ``json.dumps`` happily emits but UTF-8 cannot encode."""
        server = _Server()
        decision = _provider(server).evaluate(_request("bash", {"script": chr(0xD800)}))
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.state_unusable"
        assert "cause=unserializable reason=UnicodeEncodeError digest=unavailable" in decision.reasons[0].message
        assert server.count == 0

    def test_lone_surrogate_tool_name_is_denied_locally(self):
        server = _Server()
        decision = _provider(server).evaluate(_request(f"bash{chr(0xD800)}"))
        assert decision.allow is False
        assert "cause=unserializable reason=UnicodeEncodeError" in decision.reasons[0].message
        assert server.count == 0

    def test_local_denials_are_not_cached(self):
        server = _Server()
        provider = _provider(server, max_state_chars=64)
        arguments = {"path": "a.txt", "content": "x" * 500}
        for _ in range(2):
            assert provider.evaluate(_request("write_file", arguments)).allow is False
        assert server.count == 0

    def test_allowed_tools_refuses_unlisted_tools_without_a_request(self):
        server = _Server()
        provider = _provider(server, allowed_tools=["bash"])
        for _ in range(2):
            decision = provider.evaluate(_request("read_file", {"path": "/etc/shadow"}))
            assert decision.allow is False
            assert decision.reasons[0].code == "typesafe.tool_not_allowed"
            assert decision.metadata == {"tool_not_allowed": True}
            assert decision.policy_id == "deerflow.guardrails.typesafe"
        assert server.count == 0

    def test_empty_allowed_tools_refuses_every_tool(self):
        """``[]`` is a configured, empty set — not "no allowed_tools configured".

        A truthiness check would treat the two the same and let every tool run.
        """
        server = _Server()
        decision = _provider(server, allowed_tools=[]).evaluate(_request("bash"))
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.tool_not_allowed"
        assert server.count == 0

    def test_allowed_tools_still_face_the_risk_gate(self):
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.9)))
        decision = _provider(server, allowed_tools=["bash"]).evaluate(_request("bash"))
        assert decision.allow is False
        assert decision.reasons[0].code == "typesafe.tool_call_risky"
        assert server.count == 1

    def test_allowed_tools_and_probe_scope_are_independent_gates(self):
        """A allowed tool outside the probe scope is allowed; a tool outside
        the allowed_tools is refused even though the probe scope would have skipped it."""
        server = _Server()
        provider = _provider(server, tools=["bash"], allowed_tools=["bash", "read_file"])
        skipped = provider.evaluate(_request("read_file", {"path": "a.txt"}))
        refused = provider.evaluate(_request("write_file", {"path": "a.txt", "content": "hi"}))
        assert (skipped.allow, skipped.reasons[0].code) == (True, "typesafe.tool_not_probed")
        assert (refused.allow, refused.reasons[0].code) == (False, "typesafe.tool_not_allowed")
        assert server.count == 0

    def test_allowed_tools_refusal_precedes_state_validation(self):
        """Arguments that could not be validated must not decide the answer for a
        tool the allowed_tools already refuses: no state is built, nothing is sent."""
        server = _Server()
        decision = _provider(server, allowed_tools=["read_file"], max_state_chars=64).evaluate(_request("write_file", {"path": "a.txt", "content": "x" * 500}))
        assert decision.reasons[0].code == "typesafe.tool_not_allowed"
        assert server.count == 0


# --- response validation --------------------------------------------------


class TestResponseValidation:
    @pytest.mark.parametrize(
        "content",
        [
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": NaN}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": Infinity}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": -0.1}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": 1.5}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": "0.9"}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": true}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul"}}}',
            b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "choice", "choice": "allow"}}}',
            b'{"model": "jev-1.13.0", "answers": {}}',
            b'{"model": "jev-1.13.0"}',
            b'{"model": "", "answers": {"risky_tool_call": {"type": "noul", "noul": 0.1}}}',
            b'{"answers": {"risky_tool_call": {"type": "noul", "noul": 0.1}}}',
            b'[{"model": "jev-1.13.0"}]',
            b"not json at all",
        ],
    )
    def test_invalid_responses_raise_instead_of_deciding(self, content):
        provider = _provider(_Server(lambda request: httpx.Response(200, content=content)))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            provider.evaluate(_request())
        assert excinfo.value.cause == "invalid_response"

    def test_nan_never_reaches_the_threshold_comparison(self):
        """json.loads parses the NaN literal, so the guard has to be in the parser."""
        provider = _provider(_Server(lambda request: httpx.Response(200, content=b'{"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": NaN}}}')))
        with pytest.raises(TypeSafeGuardrailError):
            provider.evaluate(_request())

    def test_malformed_response_values_are_not_echoed(self):
        """A response that echoes tool arguments must not put them in the exception.

        GuardrailMiddleware logs provider exceptions and the evaluation script
        persists their text, so echoing a malformed ``noul`` (or answer ``type``)
        would undo the no-response-body policy the HTTP error path keeps.
        """
        secret = "rm -rf /tmp/secret AKIA-EXAMPLE-KEY"
        answers = [
            {"type": "noul", "noul": secret},
            {"type": "noul", "noul": {"echo": secret}},
            {"type": "noul", "noul": [secret]},
            {"type": secret, "noul": 0.5},
        ]
        for answer in answers:
            provider = _provider(_Server(lambda request, answer=answer: httpx.Response(200, content=json.dumps({"model": "jev-1.13.0", "answers": {_QUESTION_ID: answer}}))))
            with pytest.raises(TypeSafeGuardrailError) as excinfo:
                provider.evaluate(_request())
            assert excinfo.value.cause == "invalid_response"
            assert secret not in str(excinfo.value), answer

    @pytest.mark.parametrize("model", ["rm -rf /tmp/secret AKIA-EXAMPLE-KEY", "jev 1.13.0", "\ud800", "x" * 5000])
    def test_an_unrecordable_served_model_is_digested_instead_of_echoed(self, model):
        """``model`` is response content that reaches the journal, the logs and the report.

        It is the one value the decision message interpolates verbatim, so a value
        outside a conservative token shape is recorded as a digest -- including one
        the cache would otherwise retain and replay. Rejecting the response instead
        would deny every call the endpoint answers, which is too much to charge for
        an odd version string; the digest keeps the verdict and the provenance.
        """
        # Built here, not with httpx's ``json=``: that encoder is ensure_ascii=False
        # and cannot represent the lone surrogate case at all.
        body = json.dumps({"model": model, "answers": {_QUESTION_ID: {"type": "noul", "noul": 0.9}}})
        server = _Server(lambda request: httpx.Response(200, content=body))
        provider = _provider(server)

        decision = provider.evaluate(_request())

        assert decision.allow is False
        assert server.count == 1
        recorded = decision.metadata["model"]
        assert recorded == f"unrecorded:sha256:{hashlib.sha256(model.encode('utf-8', 'surrogatepass')).hexdigest()[:16]}"
        assert len(recorded) == len("unrecorded:sha256:") + 16, "the record must stay bounded"
        assert model not in decision.reasons[0].message

        replay = provider.evaluate(_request())

        assert replay.metadata["cached"] is True
        assert replay.metadata["model"] == recorded, "the cache must hold the bounded value, not the raw response"
        assert model not in replay.reasons[0].message

    def test_non_numeric_noul_reports_only_its_type(self):
        provider = _provider(_Server(lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_QUESTION_ID: {"type": "noul", "noul": "0.9"}}})))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            provider.evaluate(_request())
        assert "type=str" in str(excinfo.value)
        assert "0.9" not in str(excinfo.value)


# --- failures -------------------------------------------------------------


class TestFailures:
    @pytest.mark.parametrize("status", [401, 422])
    def test_client_errors_are_not_retried(self, status):
        server = _Server(lambda request: httpx.Response(status, json={"error": "nope"}))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server, max_attempts=3).evaluate(_request())
        assert excinfo.value.cause == "http_status"
        assert server.count == 1

    @pytest.mark.parametrize("status", [429, 529])
    def test_retryable_statuses_exhaust_the_attempt_budget(self, status):
        server = _Server(lambda request: httpx.Response(status, json={}))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server, max_attempts=3, retry_backoff=0).evaluate(_request())
        assert excinfo.value.cause == "http_status"
        assert server.count == 3

    def test_transport_errors_are_retried_then_raise(self):
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        server = _Server(explode)
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server, retry_backoff=0).evaluate(_request())
        assert excinfo.value.cause == "transport"
        assert server.count == 2

    def test_error_messages_never_echo_the_response_body(self):
        server = _Server(lambda request: httpx.Response(401, json={"echo": "rm -rf /tmp/scratch"}))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server).evaluate(_request())
        assert "rm -rf /tmp/scratch" not in str(excinfo.value)
        assert "HTTP 401" in str(excinfo.value)
        assert "api_key" in str(excinfo.value)

    def test_status_errors_report_only_the_numeric_status(self):
        """The HTTP status line is server-controlled, so a hostile or malformed
        endpoint can put echoed tool arguments there — only the number may be
        reported into middleware logs and the evaluation report."""
        server = _Server(lambda request: httpx.Response(429, extensions={"reason_phrase": b"rm -rf /tmp/scratch"}))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server, retry_backoff=0).evaluate(_request())
        assert excinfo.value.cause == "http_status"
        assert "HTTP 429" in str(excinfo.value)
        assert "rm -rf" not in str(excinfo.value)

    def test_failures_are_not_cached(self):
        server = _Server(lambda request: httpx.Response(500, json={}))
        provider = _provider(server, retry_backoff=0)
        for _ in range(2):
            with pytest.raises(TypeSafeGuardrailError):
                provider.evaluate(_request())
        assert server.count == 2


# --- cache ----------------------------------------------------------------


class _RacingExpiryCache(OrderedDict):
    """Cache where a second caller removes the entry between our read and ours.

    Sync evaluation runs on executor threads, so two callers can both find the
    same expired entry; this double replays exactly that interleaving.
    """

    def get(self, key, default=None):
        entry = super().get(key, default)
        if entry is not None:
            super().pop(key, None)
        return entry


class TestCache:
    def test_hit_reuses_the_recorded_decision(self):
        probabilities = iter([0.9, 0.1])
        server = _Server(lambda request: httpx.Response(200, json=_noul(next(probabilities))))
        provider = _provider(server)
        first = provider.evaluate(_request())
        second = provider.evaluate(_request())
        assert (first.allow, first.metadata["cached"]) == (False, False)
        assert (second.allow, second.metadata["cached"]) == (False, True)
        assert "cached=true" in second.reasons[0].message
        assert second.metadata["probability"] == 0.9
        assert server.count == 1

    def test_hit_survives_a_failing_service(self):
        calls = {"count": 0}

        def responder(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(200, json=_noul(0.1))
            return httpx.Response(503, json={})

        provider = _provider(_Server(responder))
        assert provider.evaluate(_request()).allow is True
        assert provider.evaluate(_request()).allow is True
        assert calls["count"] == 1

    def test_expired_entries_are_re_requested(self):
        server = _Server()
        provider = _provider(server, cache_ttl_seconds=0.02)
        provider.evaluate(_request())
        time.sleep(0.05)
        provider.evaluate(_request())
        assert server.count == 2

    def test_expired_entry_removed_by_another_caller_is_not_an_error(self):
        """A KeyError here would surface as a provider error and, with the default
        fail_closed, deny a call the gate never judged."""
        server = _Server()
        provider = _provider(server)
        provider.evaluate(_request())
        key = ("bash", json.dumps({"command": "rm -rf /tmp/scratch"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        assert key in provider._cache
        provider._cache[key] = replace(provider._cache[key], expires_at=0.0)
        provider._cache = _RacingExpiryCache(provider._cache)

        assert provider.evaluate(_request()).allow is False
        assert server.count == 2, "the expired entry must be re-evaluated rather than become an error"

    def test_cache_key_includes_the_arguments(self):
        server = _Server()
        provider = _provider(server)
        provider.evaluate(_request("bash", {"command": "ls"}))
        provider.evaluate(_request("bash", {"command": "ls -la"}))
        provider.evaluate(_request("write_file", {"command": "ls"}))
        assert server.count == 3

    def test_full_cache_evicts_the_oldest_entry(self):
        server = _Server()
        provider = _provider(server, cache_size=1)
        provider.evaluate(_request("bash", {"command": "first"}))
        provider.evaluate(_request("bash", {"command": "second"}))
        provider.evaluate(_request("bash", {"command": "first"}))
        assert server.count == 3

    def test_cache_can_be_disabled(self):
        server = _Server()
        provider = _provider(server, cache_size=0)
        provider.evaluate(_request())
        provider.evaluate(_request())
        assert server.count == 2


# --- deadline -------------------------------------------------------------


class TestDeadline:
    def test_sync_deadline_rejects_a_slow_response_header(self):
        def sleepy(request: httpx.Request) -> httpx.Response:
            time.sleep(0.3)
            return httpx.Response(200, json=_noul())

        server = _Server(sleepy)
        provider = _provider(server, deadline_seconds=0.1)
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            provider.evaluate(_request())
        assert excinfo.value.cause == "deadline"
        # A late result must not be adopted, and must not be cached either.
        with pytest.raises(TypeSafeGuardrailError):
            provider.evaluate(_request())

    def test_sync_deadline_rejects_a_slow_body(self):
        chunks, delay = _slow_body_chunks(0.2)
        server = _Server(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, stream=_SlowSyncStream(chunks, delay)))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(server, deadline_seconds=0.1).evaluate(_request())
        assert excinfo.value.cause == "deadline"
        assert server.count == 1

    @pytest.mark.asyncio
    async def test_async_deadline_cancels_a_slow_response(self):
        async def sleepy(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.5)
            return httpx.Response(200, json=_noul())

        server = _Server(sleepy)
        provider = _provider(server, deadline_seconds=0.1)
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            await provider.aevaluate(_request())
        assert excinfo.value.cause == "deadline"
        # The late result is discarded, not cached: the next call must retry.
        with pytest.raises(TypeSafeGuardrailError):
            await provider.aevaluate(_request())
        assert server.count == 2

    @pytest.mark.asyncio
    async def test_async_deadline_cancels_a_slow_body(self):
        chunks, delay = _slow_body_chunks(0.2)
        server = _Server(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, stream=_SlowAsyncStream(chunks, delay)))
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            await _provider(server, deadline_seconds=0.1).aevaluate(_request())
        assert excinfo.value.cause == "deadline"


# --- client lifecycle -----------------------------------------------------


class _ClosingTransport(httpx.BaseTransport):
    """Transport that refuses requests once closed, like httpx's own transports."""

    def __init__(self) -> None:
        self.closed = False
        self.requests = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.closed:
            raise httpx.TransportError("transport is closed", request=request)
        self.requests += 1
        return httpx.Response(200, json=_noul(0.1))

    def close(self) -> None:
        self.closed = True


class TestClientLifecycle:
    def test_factory_runs_once_per_network_evaluation_and_products_are_closed(self):
        created: list[_ClosingTransport] = []

        def factory() -> _ClosingTransport:
            transport = _ClosingTransport()
            created.append(transport)
            return transport

        provider = _provider(transport_factory=factory)
        provider.evaluate(_request("bash", {"command": "ls"}))
        provider.evaluate(_request("bash", {"command": "ls -la"}))
        assert [transport.requests for transport in created] == [1, 1]
        assert all(transport.closed for transport in created), "each evaluation must close the transport it created"

    def test_local_decisions_create_no_transport(self):
        created: list[_ClosingTransport] = []

        def factory() -> _ClosingTransport:
            created.append(_ClosingTransport())
            return created[-1]

        provider = _provider(transport_factory=factory, tools=["bash"], allowed_tools=["bash", "read_file", "write_file"], max_state_chars=64)
        provider.evaluate(_request("read_file"))  # allowed, not probed
        provider.evaluate(_request("str_replace"))  # refused by the allowed_tools
        provider.evaluate(_request("write_file", {"path": "a", "content": "x" * 200}))  # allowed, over limit
        provider.evaluate(_request("bash", {"command": "ls"}))  # network
        provider.evaluate(_request("bash", {"command": "ls"}))  # cache hit
        assert len(created) == 1

    def test_a_closed_transport_rejects_requests(self):
        """Teeth for the closure assertion above: a reused instance really dies."""
        transport = _ClosingTransport()
        transport.close()
        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _provider(transport_factory=lambda: transport, retry_backoff=0).evaluate(_request())
        assert excinfo.value.cause == "transport"

    def test_async_path_does_not_construct_a_sync_client(self, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("the async path must not build a sync client")

        monkeypatch.setattr(httpx, "Client", boom)
        decision = asyncio.run(_provider(_Server(lambda request: httpx.Response(200, json=_noul(0.1)))).aevaluate(_request("bash", {"command": "ls"})))
        assert decision.allow is True

    def test_sync_path_does_not_construct_an_async_client(self, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError("the sync path must not build an async client")

        monkeypatch.setattr(httpx, "AsyncClient", boom)
        assert _provider(_Server(lambda request: httpx.Response(200, json=_noul(0.1)))).evaluate(_request("bash", {"command": "ls"})).allow is True


# --- configuration --------------------------------------------------------


class TestConfiguration:
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"threshold": float("nan")}, "threshold"),
            ({"threshold": float("inf")}, "threshold"),
            ({"threshold": True}, "threshold"),
            ({"threshold": -0.1}, "threshold"),
            ({"threshold": 1.1}, "threshold"),
            ({"timeout": 0}, "timeout"),
            ({"timeout": "5"}, "timeout"),
            ({"deadline_seconds": 0}, "deadline_seconds"),
            ({"retry_backoff": -1}, "retry_backoff"),
            ({"cache_ttl_seconds": -1}, "cache_ttl_seconds"),
            ({"max_attempts": 1.5}, "max_attempts"),
            ({"max_attempts": 0}, "max_attempts"),
            ({"max_state_chars": 0}, "max_state_chars"),
            ({"cache_size": -1}, "cache_size"),
            ({"criteria": {"true": ""}}, "criteria.true"),
            ({"tools": ["bash", 7]}, "tools"),
            ({"allowed_tools": "bash"}, "allowed_tools"),
            ({"allowed_tools": ["bash", ""]}, "allowed_tools"),
        ],
    )
    def test_invalid_configuration_fails_at_construction(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            TypeSafeGuardrailProvider(api_key=_API_KEY, **kwargs)

    def test_missing_api_key_names_both_configuration_paths(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        with pytest.raises(ValueError) as excinfo:
            TypeSafeGuardrailProvider()
        assert "api_key" in str(excinfo.value)
        assert "TYPESAFE_API_KEY" in str(excinfo.value)

    def test_api_key_env_is_honoured(self, monkeypatch):
        monkeypatch.setenv("MY_TYPESAFE_KEY", "from-env")
        provider = TypeSafeGuardrailProvider(api_key_env="MY_TYPESAFE_KEY", transport_factory=_Server(lambda request: httpx.Response(200, json=_noul(0.1))).transport)
        assert provider.evaluate(_request("bash", {"command": "ls"})).allow is True

    def test_yaml_boolean_criteria_keys_are_accepted(self):
        """YAML parses ``criteria: {true: ...}`` keys as booleans, not strings."""
        provider = _provider(criteria={True: "custom true", False: "custom false"})
        assert provider.release_policy_parameters()["criteria"] == {"true": "custom true", "false": "custom false"}

    def test_overrides_reach_the_request(self):
        server = _Server()
        _provider(server, threshold=0.2, instructions="custom instructions", criteria={"true": "yes means bad", "false": "no means fine"}).evaluate(_request("bash", {"command": "ls"}))
        question = server.bodies()[0]["questions"][_QUESTION_ID]
        assert question["instructions"] == "custom instructions"
        assert question["criteria"] == {"true": "yes means bad", "false": "no means fine"}

    def test_release_policy_parameters_declares_behaviour_without_the_key(self):
        declared = _provider(tools=["bash"], allowed_tools=["read_file", "bash"], deadline_seconds=3.0).release_policy_parameters()
        assert _API_KEY not in json.dumps(declared)
        assert declared["threshold"] == 0.5
        assert declared["tools"] == ["bash"]
        assert declared["allowed_tools"] == ["bash", "read_file"]
        assert declared["deadline_seconds"] == 3.0
        assert declared["retry_backoff"] == 0.5
        assert declared["max_state_chars"] == 4000
        assert declared["instructions_hash"]
        # "no allowed_tools configured" and "nothing allowed" are different policies.
        assert _provider().release_policy_parameters()["allowed_tools"] is None


# --- middleware integration ----------------------------------------------


class TestMiddlewareIntegration:
    def test_denial_returns_an_error_message_and_a_replayable_journal_record(self):
        journal = _FakeJournal()
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.93)))
        middleware = GuardrailMiddleware(_provider(server))
        handler = MagicMock()
        result = middleware.wrap_tool_call(_tool_call_request(context={"__run_journal": journal}), handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "typesafe.tool_call_risky" in result.content
        assert "p=0.93" in result.content and "model=jev-1.13.0" in result.content

        record = journal.calls[0]["changes"]
        assert record["allow"] is False
        assert record["reason_codes"] == ["typesafe.tool_call_risky"]
        assert "p=0.93" in record["reason_messages"][0]
        assert "digest=" in record["reason_messages"][0]

    def test_allowed_call_reaches_the_handler(self):
        middleware = GuardrailMiddleware(_provider(_Server(lambda request: httpx.Response(200, json=_noul(0.01)))))
        expected = MagicMock()
        handler = MagicMock(return_value=expected)
        assert middleware.wrap_tool_call(_tool_call_request(), handler) is expected

    def test_fail_closed_blocks_when_the_provider_errors(self):
        middleware = GuardrailMiddleware(_provider(_Server(lambda request: httpx.Response(503, json={})), retry_backoff=0), fail_closed=True)
        handler = MagicMock()
        result = middleware.wrap_tool_call(_tool_call_request(), handler)
        handler.assert_not_called()
        assert result.status == "error"
        assert "oap.evaluator_error" in result.content

    def test_fail_open_allows_when_the_provider_errors(self):
        middleware = GuardrailMiddleware(_provider(_Server(lambda request: httpx.Response(503, json={})), retry_backoff=0), fail_closed=False)
        expected = MagicMock()
        handler = MagicMock(return_value=expected)
        assert middleware.wrap_tool_call(_tool_call_request(), handler) is expected

    def test_lone_surrogates_are_denied_even_when_fail_open(self):
        """A local validation failure must never become an unevaluated execution:
        fail_closed=false only governs provider *errors*, not refusals."""
        middleware = GuardrailMiddleware(_provider(_Server()), fail_closed=False)
        handler = MagicMock()
        result = middleware.wrap_tool_call(_tool_call_request(args={"script": chr(0xD800)}), handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "typesafe.state_unusable" in result.content

    def test_allowed_tools_refusal_is_not_governed_by_fail_open(self):
        """The allowed_tools is a permission rule, not a provider error: fail_open only
        covers evaluator failures, so a refused tool must never run unevaluated."""
        journal = _FakeJournal()
        middleware = GuardrailMiddleware(_provider(_Server(), allowed_tools=["bash"]), fail_closed=False)
        handler = MagicMock()
        result = middleware.wrap_tool_call(_tool_call_request(tool_name="read_file", args={"path": "/etc/shadow"}, context={"__run_journal": journal}), handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "typesafe.tool_not_allowed" in result.content
        assert journal.calls[0]["changes"]["reason_codes"] == ["typesafe.tool_not_allowed"]

    def test_async_allowed_tools_refusal_returns_an_error_message(self):
        middleware = GuardrailMiddleware(_provider(_Server(), allowed_tools=["bash"]), fail_closed=False)

        async def run():
            handler = AsyncMock()
            result = await middleware.awrap_tool_call(_tool_call_request(tool_name="read_file", args={"path": "/etc/shadow"}), handler)
            handler.assert_not_called()
            return result

        result = asyncio.run(run())
        assert result.status == "error"
        assert "typesafe.tool_not_allowed" in result.content

    def test_async_denial_returns_an_error_message(self):
        server = _Server(lambda request: httpx.Response(200, json=_noul(0.97)))
        middleware = GuardrailMiddleware(_provider(server))

        async def run():
            handler = AsyncMock()
            result = await middleware.awrap_tool_call(_tool_call_request(), handler)
            handler.assert_not_called()
            return result

        result = asyncio.run(run())
        assert result.status == "error"
        assert "typesafe.tool_call_risky" in result.content
        assert server.count == 1
