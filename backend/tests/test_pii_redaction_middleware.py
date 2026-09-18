"""Tests for PiiRedactionMiddleware (issue #3190).

Verifies deterministic detector coverage (including checksum gates), stable
placeholder numbering across a conversation, that the rewrite is request-scoped
without mutating the original request or messages, the tool-boundary allowlist,
and the pinned detector registry.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.pii_redaction_middleware import (
    _DETECTORS,
    PiiRedactionMiddleware,
)
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.tools.mcp_metadata import MCP_TOOL_METADATA_KEY


def _make_middleware(**config_overrides) -> PiiRedactionMiddleware:
    return PiiRedactionMiddleware(PiiRedactionConfig(enabled=True, **config_overrides))


class _FakeRequest:
    """Minimal stand-in for ModelRequest — duck-typed to .messages + .override()."""

    def __init__(self, messages):
        self.messages = list(messages)

    def override(self, **kwargs):
        return _FakeRequest(kwargs.get("messages", self.messages))


def _run_model_call(middleware, messages):
    """Run wrap_model_call; return (final_messages, original_request)."""
    request = _FakeRequest(messages)
    captured = {}
    middleware.wrap_model_call(request, lambda req: captured.update(messages=req.messages) or "response")
    return captured["messages"], request


def _run_tool_call(middleware, tool_name, result, *, tool=None):
    request = Mock()
    request.tool_call = {"name": tool_name}
    request.tool = tool if tool is not None else SimpleNamespace(metadata=None)
    return middleware.wrap_tool_call(request, lambda _request: result)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


class TestDetectors:
    def test_pinned_detector_count(self):
        """New detectors must extend this pin and the config toggles together."""
        assert len(_DETECTORS) == 5
        assert [d.name for d in _DETECTORS] == ["email", "api_key", "credit_card", "phone", "national_id"]

    def test_email_redacted(self):
        result = _make_middleware()._detectors[0].pattern.sub("X", "ping me at alice@example.com today")
        assert result == "ping me at X today"

    def test_distinct_emails_get_distinct_placeholders(self):
        middleware = _make_middleware()
        messages, _ = _run_model_call(
            middleware,
            [HumanMessage("from alice@example.com to bob@example.org")],
        )
        assert "from [EMAIL_1] to [EMAIL_2]" in messages[0].content

    def test_same_email_shares_placeholder(self):
        middleware = _make_middleware()
        messages, _ = _run_model_call(
            middleware,
            [
                HumanMessage("alice@example.com here"),
                HumanMessage("reply to alice@example.com"),
            ],
        )
        assert messages[0].content == "[EMAIL_1] here"
        assert messages[1].content == "reply to [EMAIL_1]"

    def test_openai_style_api_key_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("key: sk-proj4aaaaaaaaaaaaaaaaaaaaaaaaaaaa")],
        )
        assert "[API_KEY_1]" in messages[0].content

    def test_aws_access_key_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("use AKIAIOSFODNN7EXAMPLE please")],
        )
        assert "[API_KEY_1]" in messages[0].content

    def test_credit_card_luhn_valid_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("card 4111 1111 1111 1111 on file")],
        )
        assert "card [CREDIT_CARD_1] on file" in messages[0].content

    def test_credit_card_luhn_invalid_untouched(self):
        original = "card 1234 5678 9012 3456 on file"
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage(original)])
        assert messages[0].content == original

    def test_long_digit_run_non_card_untouched(self):
        original = "order 1234567890123 shipped"
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage(original)])
        assert messages[0].content == original

    def test_international_phone_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("call +86 138 0013 8000 now")],
        )
        assert "call [PHONE_1] now" in messages[0].content

    def test_cn_mobile_redacted(self):
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage("phone 13800138000")])
        assert "phone [PHONE_1]" in messages[0].content

    def test_us_phone_redacted(self):
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage("dial (212) 555-0123")])
        assert "dial [PHONE_1]" in messages[0].content

    def test_cn_resident_id_valid_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("id 11010519491231002X")],
        )
        assert "id [NATIONAL_ID_1]" in messages[0].content

    def test_cn_resident_id_invalid_checksum_untouched(self):
        original = "id 110105194912310020"
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage(original)])
        assert messages[0].content == original

    def test_cpf_valid_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("cpf 529.982.247-25")],
        )
        assert "cpf [NATIONAL_ID_1]" in messages[0].content

    def test_cpf_invalid_untouched(self):
        original = "cpf 529.982.247-11"
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage(original)])
        assert messages[0].content == original


# ---------------------------------------------------------------------------
# Model-call boundary
# ---------------------------------------------------------------------------


class TestModelCallBoundary:
    def test_genuine_user_message_redacted(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("my email is alice@example.com")],
        )
        assert messages[0].content == "my email is [EMAIL_1]"

    def test_original_request_not_mutated(self):
        original = HumanMessage("my email is alice@example.com")
        messages, request = _run_model_call(_make_middleware(), [original])
        assert messages[0].content == "my email is [EMAIL_1]"
        assert request.messages[0].content == "my email is alice@example.com"

    def test_additional_kwargs_preserved(self):
        original = HumanMessage("alice@example.com", additional_kwargs={"hide_from_ui": False, "custom": "v"})
        messages, _ = _run_model_call(_make_middleware(), [original])
        assert messages[0].additional_kwargs["custom"] == "v"

    def test_ai_message_untouched(self):
        ai = AIMessage("contact alice@example.com")
        messages, _ = _run_model_call(_make_middleware(), [ai])
        assert messages[0].content == "contact alice@example.com"

    def test_clean_message_not_rebuilt(self):
        original = HumanMessage("no secrets here")
        messages, _ = _run_model_call(_make_middleware(), [original])
        assert messages[0] is original

    def test_placeholder_numbering_spans_conversation(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [
                HumanMessage("first alice@example.com"),
                AIMessage("noted"),
                HumanMessage("then bob@example.org"),
            ],
        )
        assert "first [EMAIL_1]" in messages[0].content
        assert "then [EMAIL_2]" in messages[2].content

    def test_redaction_deterministic_across_calls(self):
        middleware = _make_middleware()
        messages_a, _ = _run_model_call(middleware, [HumanMessage("alice@example.com")])
        messages_b, _ = _run_model_call(middleware, [HumanMessage("alice@example.com")])
        assert messages_a[0].content == messages_b[0].content == "[EMAIL_1]"

    def test_disabled_detector_untouched(self):
        messages, _ = _run_model_call(
            _make_middleware(redact_email=False),
            [HumanMessage("alice@example.com")],
        )
        assert messages[0].content == "alice@example.com"

    def test_multimodal_text_blocks_redacted_and_non_text_kept(self):
        image_block = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
        original = HumanMessage(
            [
                "reach me at alice@example.com",
                image_block,
                "or bob@example.org",
            ]
        )
        messages, _ = _run_model_call(_make_middleware(), [original])
        assert messages[0].content[0] == "reach me at [EMAIL_1]"
        # LangChain rebuilds content blocks on construction, so compare by value.
        assert messages[0].content[1] == image_block
        assert messages[0].content[2] == "or [EMAIL_2]"
        # The original message object is untouched.
        assert original.content[0] == "reach me at alice@example.com"


# ---------------------------------------------------------------------------
# Tool boundary
# ---------------------------------------------------------------------------


class TestToolBoundary:
    def test_web_fetch_result_redacted_and_stamped(self):
        result = ToolMessage(
            content="page says contact alice@example.com",
            tool_call_id="call_1",
            name="web_fetch",
        )
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        assert final.content == "page says contact [EMAIL_1]"
        transforms = final.additional_kwargs["deerflow_tool_transforms"]
        assert transforms[-1]["kind"] == "pii_redaction"
        assert transforms[-1]["by"] == "PiiRedactionMiddleware"

    def test_local_tool_result_untouched(self):
        result = ToolMessage(
            content="user row: alice@example.com",
            tool_call_id="call_1",
            name="bash",
        )
        final = _run_tool_call(_make_middleware(), "bash", result)
        assert final is result

    def test_mcp_tagged_tool_redacted(self):
        result = ToolMessage(
            content="alice@example.com",
            tool_call_id="call_1",
            name="fetch_url",
        )
        tool = SimpleNamespace(metadata={MCP_TOOL_METADATA_KEY: True})
        final = _run_tool_call(_make_middleware(), "fetch_url", result, tool=tool)
        assert final.content == "[EMAIL_1]"

    def test_command_result_passthrough(self):
        result = Command(update={"events": ["alice@example.com"]})
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        assert final is result

    def test_tool_message_not_mutated(self):
        result = ToolMessage(
            content="alice@example.com",
            tool_call_id="call_1",
            name="web_search",
        )
        _run_tool_call(_make_middleware(), "web_search", result)
        assert result.content == "alice@example.com"

    def test_placeholder_restarts_per_result(self):
        middleware = _make_middleware()
        first = _run_tool_call(
            middleware,
            "web_fetch",
            ToolMessage(content="alice@example.com", tool_call_id="c1", name="web_fetch"),
        )
        second = _run_tool_call(
            middleware,
            "web_fetch",
            ToolMessage(content="bob@example.com", tool_call_id="c2", name="web_fetch"),
        )
        assert first.content == "[EMAIL_1]"
        assert second.content == "[EMAIL_1]"


# ---------------------------------------------------------------------------
# release policy declaration
# ---------------------------------------------------------------------------


class TestReleasePolicy:
    def test_declares_enabled_detectors(self):
        policy = _make_middleware(redact_phone=False, redact_national_id=False).release_policy_parameters()
        assert policy == {"enabled": True, "detectors": ["api_key", "credit_card", "email"]}

    def test_all_detectors_enabled_by_default_config(self):
        policy = _make_middleware().release_policy_parameters()
        assert policy["detectors"] == ["api_key", "credit_card", "email", "national_id", "phone"]


@pytest.mark.parametrize(
    "config",
    [
        PiiRedactionConfig(enabled=False),
        PiiRedactionConfig(enabled=True),
    ],
)
def test_config_defaults_are_consistent(config):
    """The middleware constructor must accept the shipped default configs."""
    PiiRedactionMiddleware(config)


# ---------------------------------------------------------------------------
# Chain wiring
# ---------------------------------------------------------------------------


def _wiring_app_config(**overrides):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return AppConfig(sandbox=SandboxConfig(use="test"), **overrides)


class TestChainWiring:
    def test_disabled_by_default_not_in_chain(self):
        from deerflow.agents.middlewares.pii_redaction_middleware import PiiRedactionMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

        middlewares = build_lead_runtime_middlewares(app_config=_wiring_app_config())
        assert PiiRedactionMiddleware not in [type(m) for m in middlewares]

    def test_enabled_sits_inner_of_the_structural_guardrails(self):
        from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
        from deerflow.agents.middlewares.pii_redaction_middleware import PiiRedactionMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
        from deerflow.agents.middlewares.tool_result_sanitization_middleware import ToolResultSanitizationMiddleware

        middlewares = build_lead_runtime_middlewares(
            app_config=_wiring_app_config(pii_redaction=PiiRedactionConfig(enabled=True)),
        )
        types = [type(m) for m in middlewares]
        assert PiiRedactionMiddleware in types
        assert types.index(InputSanitizationMiddleware) < types.index(ToolResultSanitizationMiddleware) < types.index(PiiRedactionMiddleware)

    def test_enabled_reaches_subagent_chain(self):
        from deerflow.agents.middlewares.pii_redaction_middleware import PiiRedactionMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        middlewares = build_subagent_runtime_middlewares(
            app_config=_wiring_app_config(pii_redaction=PiiRedactionConfig(enabled=True)),
        )
        assert PiiRedactionMiddleware in [type(m) for m in middlewares]
