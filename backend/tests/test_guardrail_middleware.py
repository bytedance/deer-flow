"""Tests for the guardrail middleware and built-in providers."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from langgraph.errors import GraphBubbleUp

from deerflow.guardrails.builtin import AllowlistProvider
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest

# --- Helpers ---


class _FakeRuntime:
    def __init__(self, context: dict | None = None):
        self.context = context or {}


class _FakeJournal:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def record_middleware(self, **kwargs):
        if self.fail:
            raise RuntimeError("journal unavailable")
        self.calls.append(kwargs)


def _make_tool_call_request(
    name: str = "bash",
    args: dict | None = None,
    call_id: str = "call_1",
    *,
    context: dict | None = None,
):
    """Create a mock ToolCallRequest."""
    req = MagicMock()
    req.tool_call = {"name": name, "args": args or {}, "id": call_id}
    req.runtime = _FakeRuntime(context)
    return req


class _AllowAllProvider:
    name = "allow-all"

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return self.evaluate(request)


class _DenyAllProvider:
    name = "deny-all"

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(
            allow=False,
            reasons=[GuardrailReason(code="oap.denied", message="all tools blocked")],
            policy_id="test.deny.v1",
        )

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return self.evaluate(request)


class _ExplodingProvider:
    name = "exploding"

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        raise RuntimeError("provider crashed")

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        raise RuntimeError("provider crashed")


# --- AllowlistProvider tests ---


class TestAllowlistProvider:
    def test_no_restrictions_allows_all(self):
        provider = AllowlistProvider()
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is True

    def test_denied_tools(self):
        provider = AllowlistProvider(denied_tools=["bash", "write_file"])
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is False
        assert decision.reasons[0].code == "oap.tool_not_allowed"

    def test_denied_tools_allows_unlisted(self):
        provider = AllowlistProvider(denied_tools=["bash"])
        req = GuardrailRequest(tool_name="web_search", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is True

    def test_allowed_tools_blocks_unlisted(self):
        provider = AllowlistProvider(allowed_tools=["web_search", "read_file"])
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is False

    def test_allowed_tools_allows_listed(self):
        provider = AllowlistProvider(allowed_tools=["web_search"])
        req = GuardrailRequest(tool_name="web_search", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is True

    def test_both_allowed_and_denied(self):
        provider = AllowlistProvider(allowed_tools=["bash", "web_search"], denied_tools=["bash"])
        # bash is in both: allowlist passes, denylist blocks
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is False

    def test_async_delegates_to_sync(self):
        provider = AllowlistProvider(denied_tools=["bash"])
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = asyncio.run(provider.aevaluate(req))
        assert decision.allow is False


# --- GuardrailMiddleware tests ---


class TestGuardrailMiddleware:
    def test_allowed_tool_passes_through(self):
        mw = GuardrailMiddleware(_AllowAllProvider())
        req = _make_tool_call_request("web_search")
        expected = MagicMock()
        handler = MagicMock(return_value=expected)
        result = mw.wrap_tool_call(req, handler)
        handler.assert_called_once_with(req)
        assert result is expected

    def test_denied_tool_returns_error_message(self):
        mw = GuardrailMiddleware(_DenyAllProvider())
        req = _make_tool_call_request("bash")
        handler = MagicMock()
        result = mw.wrap_tool_call(req, handler)
        handler.assert_not_called()
        assert result.status == "error"
        assert "oap.denied" in result.content
        assert result.name == "bash"

    def test_fail_closed_on_provider_error(self):
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=True)
        req = _make_tool_call_request("bash")
        handler = MagicMock()
        result = mw.wrap_tool_call(req, handler)
        handler.assert_not_called()
        assert result.status == "error"
        assert "oap.evaluator_error" in result.content

    def test_fail_open_on_provider_error(self):
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=False)
        req = _make_tool_call_request("bash")
        expected = MagicMock()
        handler = MagicMock(return_value=expected)
        result = mw.wrap_tool_call(req, handler)
        handler.assert_called_once_with(req)
        assert result is expected

    def test_passport_passed_as_agent_id(self):
        captured = {}

        class CapturingProvider:
            name = "capture"

            def evaluate(self, request):
                captured["agent_id"] = request.agent_id
                return GuardrailDecision(allow=True)

            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CapturingProvider(), passport="./guardrails/passport.json")
        req = _make_tool_call_request("bash")
        mw.wrap_tool_call(req, MagicMock())
        assert captured["agent_id"] == "./guardrails/passport.json"

    def test_decision_contains_oap_reason_codes(self):
        mw = GuardrailMiddleware(_DenyAllProvider())
        req = _make_tool_call_request("bash")
        result = mw.wrap_tool_call(req, MagicMock())
        assert "oap.denied" in result.content
        assert "all tools blocked" in result.content

    def test_deny_with_empty_reasons_uses_fallback(self):
        """Provider returns deny with empty reasons list -- middleware uses fallback text."""

        class EmptyReasonProvider:
            name = "empty-reason"

            def evaluate(self, request):
                return GuardrailDecision(allow=False, reasons=[])

            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(EmptyReasonProvider())
        req = _make_tool_call_request("bash")
        result = mw.wrap_tool_call(req, MagicMock())
        assert result.status == "error"
        assert "blocked by guardrail policy" in result.content

    def test_empty_tool_name(self):
        """Tool call with empty name is handled gracefully."""
        mw = GuardrailMiddleware(_AllowAllProvider())
        req = _make_tool_call_request("")
        expected = MagicMock()
        handler = MagicMock(return_value=expected)
        result = mw.wrap_tool_call(req, handler)
        assert result is expected

    def test_protocol_isinstance_check(self):
        """AllowlistProvider satisfies GuardrailProvider protocol at runtime."""
        from deerflow.guardrails.provider import GuardrailProvider

        assert isinstance(AllowlistProvider(), GuardrailProvider)

    def test_async_allowed(self):
        mw = GuardrailMiddleware(_AllowAllProvider())
        req = _make_tool_call_request("web_search")
        expected = MagicMock()

        async def handler(r):
            return expected

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())
        assert result is expected

    def test_async_denied(self):
        mw = GuardrailMiddleware(_DenyAllProvider())
        req = _make_tool_call_request("bash")

        async def handler(r):
            return MagicMock()

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())
        assert result.status == "error"

    def test_async_fail_closed(self):
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=True)
        req = _make_tool_call_request("bash")

        async def handler(r):
            return MagicMock()

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())
        assert result.status == "error"

    def test_async_fail_open(self):
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=False)
        req = _make_tool_call_request("bash")
        expected = MagicMock()

        async def handler(r):
            return expected

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())
        assert result is expected

    def test_graph_bubble_up_not_swallowed(self):
        """GraphBubbleUp (LangGraph interrupt/pause) must propagate, not be caught."""

        class BubbleProvider:
            name = "bubble"

            def evaluate(self, request):
                raise GraphBubbleUp()

            async def aevaluate(self, request):
                raise GraphBubbleUp()

        mw = GuardrailMiddleware(BubbleProvider(), fail_closed=True)
        req = _make_tool_call_request("bash")
        with pytest.raises(GraphBubbleUp):
            mw.wrap_tool_call(req, MagicMock())

    def test_async_graph_bubble_up_not_swallowed(self):
        """Async: GraphBubbleUp must propagate."""

        class BubbleProvider:
            name = "bubble"

            def evaluate(self, request):
                raise GraphBubbleUp()

            async def aevaluate(self, request):
                raise GraphBubbleUp()

        mw = GuardrailMiddleware(BubbleProvider(), fail_closed=True)
        req = _make_tool_call_request("bash")

        async def handler(r):
            return MagicMock()

        async def run():
            return await mw.awrap_tool_call(req, handler)

        with pytest.raises(GraphBubbleUp):
            asyncio.run(run())

    # Journal: a denied tool call records the complete guardrail audit event.
    def test_denied_tool_records_guardrail_event(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_DenyAllProvider(), passport="agent_id")
        req = _make_tool_call_request(
            "bash",
            args={"command": "cat secret.txt"},
            call_id="tool_call_1",
            context={
                "__run_journal": journal,
                "user_role": "user",
            },
        )
        result = mw.wrap_tool_call(req, MagicMock())

        assert result.status == "error"
        assert len(journal.calls) == 1
        event = journal.calls[0]
        assert event["tag"] == "guardrail"
        assert event["name"] == "GuardrailMiddleware"
        assert event["hook"] == "wrap_tool_call"
        assert event["action"] == "deny_tool_call"
        changes = event["changes"]
        assert changes["tool_name"] == "bash"
        assert changes["tool_call_id"] == "tool_call_1"
        assert changes["agent_id"] == "agent_id"
        assert changes["is_subagent"] is False
        assert changes["user_role"] == "user"
        assert changes["allow"] is False
        assert changes["policy_id"] == "test.deny.v1"
        assert changes["reason_codes"] == ["oap.denied"]
        assert changes["reason_messages"] == ["all tools blocked"]
        assert changes["fail_closed"] is True
        assert changes["provider_error"] is False
        assert "tool_input" not in changes
        assert "args" not in changes
        assert "command" not in changes
        assert "user_id" not in changes
        assert "oauth_provider" not in changes
        assert "oauth_id" not in changes

    # Journal: a fail-closed provider error is recorded as a denied tool call.
    def test_fail_closed_provider_error_records_guardrail_event(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=True)
        req = _make_tool_call_request("bash", context={"__run_journal": journal})
        handler = MagicMock()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert len(journal.calls) == 1
        event = journal.calls[0]
        assert event["action"] == "deny_tool_call"
        changes = event["changes"]
        assert changes["allow"] is False
        assert changes["reason_codes"] == ["oap.evaluator_error"]
        assert changes["provider_error"] is True
        assert changes["fail_closed"] is True

    # Journal: a fail-open provider error is recorded without blocking the tool.
    def test_fail_open_provider_error_records_guardrail_event_and_allows_handler(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=False)
        req = _make_tool_call_request("bash", context={"__run_journal": journal})
        expected = MagicMock()
        handler = MagicMock(return_value=expected)

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once_with(req)
        assert result is expected
        assert len(journal.calls) == 1
        event = journal.calls[0]
        assert event["action"] == "allow_tool_call_after_provider_error"
        changes = event["changes"]
        assert changes["allow"] is True
        assert changes["reason_codes"] == ["oap.evaluator_error"]
        assert changes["provider_error"] is True
        assert changes["fail_closed"] is False

    # Journal: ordinary allowed decisions do not create guardrail audit events.
    def test_allowed_tool_does_not_record_guardrail_event(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_AllowAllProvider())
        req = _make_tool_call_request("web_search", context={"__run_journal": journal})
        expected = MagicMock()
        handler = MagicMock(return_value=expected)

        result = mw.wrap_tool_call(req, handler)

        assert result is expected
        assert journal.calls == []

    # Journal: a recording failure must not alter the guardrail denial outcome.
    def test_guardrail_event_recording_failure_does_not_change_denial(self):
        journal = _FakeJournal(fail=True)
        mw = GuardrailMiddleware(_DenyAllProvider())
        req = _make_tool_call_request("bash", context={"__run_journal": journal})
        handler = MagicMock()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "oap.denied" in result.content

    # Journal: the async denial path records the same guardrail audit event.
    def test_async_denied_tool_records_guardrail_event(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_DenyAllProvider(), passport="agent_id")
        req = _make_tool_call_request(
            "bash",
            call_id="async_call_1",
            context={"__run_journal": journal},
        )

        async def handler(r):
            return MagicMock()

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())

        assert result.status == "error"
        assert len(journal.calls) == 1
        event = journal.calls[0]
        assert event["tag"] == "guardrail"
        assert event["hook"] == "wrap_tool_call"
        assert event["action"] == "deny_tool_call"
        changes = event["changes"]
        assert changes["tool_name"] == "bash"
        assert changes["tool_call_id"] == "async_call_1"
        assert changes["agent_id"] == "agent_id"
        assert changes["is_subagent"] is False
        assert changes["allow"] is False
        assert changes["provider_error"] is False

    # Journal: the async fail-open path records the error and still runs the tool.
    def test_async_fail_open_provider_error_records_guardrail_event_and_allows_handler(self):
        journal = _FakeJournal()
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=False)
        req = _make_tool_call_request("bash", context={"__run_journal": journal})
        expected = MagicMock()

        async def handler(r):
            return expected

        async def run():
            return await mw.awrap_tool_call(req, handler)

        result = asyncio.run(run())

        assert result is expected
        assert len(journal.calls) == 1
        event = journal.calls[0]
        assert event["action"] == "allow_tool_call_after_provider_error"
        changes = event["changes"]
        assert changes["allow"] is True
        assert changes["provider_error"] is True
        assert changes["fail_closed"] is False


class TestGuardrailRequestAttribution:
    """Tests for GuardrailRequest runtime attribution fields."""

    def _make_runtime_mock(self, context: dict | None = None):
        runtime = MagicMock()
        runtime.context = context
        return runtime

    def _make_request(self, runtime=None, tool_call: dict | None = None):
        req = MagicMock()
        req.runtime = runtime
        req.tool_call = tool_call or {"name": "bash", "args": {}}
        req.tool = None
        req.state = {}
        return req

    def _capture_guardrail_request(self, req):
        captured = {}

        class CaptureProvider:
            name = "capture"

            def evaluate(self, request):
                captured["request"] = request
                return GuardrailDecision(allow=True)

            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        return captured["request"]

    def test_no_attribution_fields_are_none(self):
        req = self._make_request(runtime=None, tool_call={"name": "bash", "args": {}})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id is None
        assert guardrail_request.user_role is None
        assert guardrail_request.oauth_provider is None
        assert guardrail_request.oauth_id is None
        assert guardrail_request.run_id is None
        assert guardrail_request.tool_call_id is None

    def test_only_user_id_present(self):
        runtime = self._make_runtime_mock(context={"user_id": "user_abc"})
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id == "user_abc"
        assert guardrail_request.user_role is None
        assert guardrail_request.oauth_provider is None
        assert guardrail_request.oauth_id is None
        assert guardrail_request.run_id is None
        assert guardrail_request.tool_call_id is None

    def test_authenticated_user_context_present(self):
        runtime = self._make_runtime_mock(
            context={
                "user_id": "user_abc",
                "user_role": "admin",
                "oauth_provider": "github",
                "oauth_id": "gh_123",
            }
        )
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id == "user_abc"
        assert guardrail_request.user_role == "admin"
        assert guardrail_request.oauth_provider == "github"
        assert guardrail_request.oauth_id == "gh_123"

    def test_only_run_id_present(self):
        runtime = self._make_runtime_mock(context={"run_id": "run_xyz"})
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id is None
        assert guardrail_request.run_id == "run_xyz"
        assert guardrail_request.tool_call_id is None

    def test_only_tool_call_id_present(self):
        req = self._make_request(runtime=None, tool_call={"name": "web_search", "args": {"query": "test"}, "id": "call_42"})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id is None
        assert guardrail_request.run_id is None
        assert guardrail_request.tool_call_id == "call_42"

    def test_all_attribution_fields_present(self):
        runtime = self._make_runtime_mock(
            context={
                "user_id": "user_abc",
                "user_role": "user",
                "oauth_provider": "google",
                "oauth_id": "google_123",
                "run_id": "run_xyz",
                "is_subagent": True,
            }
        )
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}, "id": "call_all"})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id == "user_abc"
        assert guardrail_request.user_role == "user"
        assert guardrail_request.oauth_provider == "google"
        assert guardrail_request.oauth_id == "google_123"
        assert guardrail_request.run_id == "run_xyz"
        assert guardrail_request.tool_call_id == "call_all"
        assert guardrail_request.is_subagent is True

    def test_partial_attribution_fields_present(self):
        runtime = self._make_runtime_mock(context={"user_id": "user_partial"})
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}, "id": "call_partial"})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id == "user_partial"
        assert guardrail_request.run_id is None
        assert guardrail_request.tool_call_id == "call_partial"

    def test_empty_context_with_tool_call(self):
        runtime = self._make_runtime_mock(context={})
        req = self._make_request(runtime=runtime, tool_call={"name": "bash", "args": {}, "id": "call_empty_context"})

        guardrail_request = self._capture_guardrail_request(req)

        assert guardrail_request.user_id is None
        assert guardrail_request.run_id is None
        assert guardrail_request.tool_call_id == "call_empty_context"


# --- Config tests ---


class TestGuardrailsConfig:
    def test_config_defaults(self):
        from deerflow.config.guardrails_config import GuardrailsConfig

        config = GuardrailsConfig()
        assert config.enabled is False
        assert config.fail_closed is True
        assert config.passport is None
        assert config.provider is None

    def test_config_from_dict(self):
        from deerflow.config.guardrails_config import GuardrailsConfig

        config = GuardrailsConfig.model_validate(
            {
                "enabled": True,
                "fail_closed": False,
                "passport": "./guardrails/passport.json",
                "provider": {
                    "use": "deerflow.guardrails.builtin:AllowlistProvider",
                    "config": {"denied_tools": ["bash"]},
                },
            }
        )
        assert config.enabled is True
        assert config.fail_closed is False
        assert config.passport == "./guardrails/passport.json"
        assert config.provider.use == "deerflow.guardrails.builtin:AllowlistProvider"
        assert config.provider.config == {"denied_tools": ["bash"]}

    def test_singleton_load_and_get(self):
        from deerflow.config.guardrails_config import get_guardrails_config, load_guardrails_config_from_dict, reset_guardrails_config

        try:
            load_guardrails_config_from_dict({"enabled": True, "provider": {"use": "test:Foo"}})
            config = get_guardrails_config()
            assert config.enabled is True
        finally:
            reset_guardrails_config()
