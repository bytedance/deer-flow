"""Tests for PiiRedactionMiddleware (issue #3190).

Verifies deterministic detector coverage (including checksum gates), stable
placeholder numbering across a conversation, that the rewrite is request-scoped
without mutating the original request or messages, the tool-boundary allowlist,
and the pinned detector registry.
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command
from pydantic import Field

from deerflow.agents.middlewares.pii_redaction_middleware import (
    _DETECTORS,
    PiiRedactionMiddleware,
    redact_text,
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
        assert [d.name for d in _DETECTORS] == ["email", "api_key", "national_id", "credit_card", "phone"]

    def test_cn_resident_id_with_luhn_valid_digits_not_mislabeled_as_card(self):
        # 110105194912310150 passes both the GB 11643 checksum and Luhn; the
        # national-id detector must claim it before the credit-card detector
        # (review finding on #5527, reproduced at 0a2a9d0).
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage("id 110105194912310150")])
        assert "id [NATIONAL_ID_1]" in messages[0].content

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

    def test_willem_vector_numeric_check_digit_redacted(self):
        # Review vector on #5527: numeric-check-digit resident ID whose digits
        # also pass Luhn must render NATIONAL_ID, not CREDIT_CARD.
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage("id 110105197506150239")])
        assert "id [NATIONAL_ID_1]" in messages[0].content

    def test_cuit_valid_form_redacted(self):
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage("CUIT 20-12345678-6")])
        assert "CUIT [NATIONAL_ID_1]" in messages[0].content

    def test_cuit_wrong_digit_count_untouched(self):
        original = "CUIT 20-1234567890-6"
        messages, _ = _run_model_call(_make_middleware(), [HumanMessage(original)])
        assert messages[0].content == original

    def test_cjk_adjacent_identifiers_redacted(self):
        # Python \b treats CJK as word characters; the digit-aware lookarounds
        # must still catch identifiers glued to Chinese labels.
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("身份证11010519491231002X 手机号13800138000 信用卡4111 1111 1111 1111")],
        )
        content = messages[0].content
        assert "[NATIONAL_ID_1]" in content and "[PHONE_1]" in content and "[CREDIT_CARD_1]" in content
        assert "11010519491231002X" not in content and "13800138000" not in content and "4111" not in content

    def test_international_phone_does_not_consume_next_line(self):
        messages, _ = _run_model_call(
            _make_middleware(),
            [HumanMessage("Call +1 415 555 2671\n20260918")],
        )
        assert messages[0].content == "Call [PHONE_1]\n20260918"

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

    def test_command_wrapped_tool_result_redacted_and_stamped(self):
        tool_message = ToolMessage(content="page says alice@example.com", tool_call_id="c1", name="web_fetch")
        result = Command(update={"messages": [tool_message]})
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        assert isinstance(final, Command)
        new_message = final.update["messages"][0]
        assert new_message.content == "page says [EMAIL_1]"
        assert new_message.additional_kwargs["deerflow_tool_transforms"][-1]["kind"] == "pii_redaction"
        # The original Command and its message are untouched.
        assert tool_message.content == "page says alice@example.com"

    def test_command_without_tool_messages_passthrough(self):
        result = Command(update={"messages": [AIMessage("alice@example.com")]})
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        assert final is result

    def test_redacted_tool_message_preserves_artifact_and_metadata(self):
        result = ToolMessage(
            content="alice@example.com",
            tool_call_id="c1",
            name="web_fetch",
            artifact={"rows": 3},
            response_metadata={"latency_ms": 12},
        )
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        assert final.content == "[EMAIL_1]"
        assert final.artifact == {"rows": 3}
        assert final.response_metadata == {"latency_ms": 12}
        assert final.status == "success"

    def test_tool_message_not_mutated(self):
        result = ToolMessage(
            content="alice@example.com",
            tool_call_id="call_1",
            name="web_search",
        )
        _run_tool_call(_make_middleware(), "web_search", result)
        assert result.content == "alice@example.com"

    def test_command_placeholder_numbering_continues_across_messages(self):
        # One redactor spans the whole Command result, so placeholder numbers
        # stay continuous across the ToolMessages it carries (review follow-up).
        first = ToolMessage(content="alice@example.com", tool_call_id="c1", name="web_fetch")
        second = ToolMessage(content="then bob@example.org and alice@example.com", tool_call_id="c2", name="web_fetch")
        result = Command(update={"messages": [first, second]})
        final = _run_tool_call(_make_middleware(), "web_fetch", result)
        messages = final.update["messages"]
        assert messages[0].content == "[EMAIL_1]"
        assert messages[1].content == "then [EMAIL_2] and [EMAIL_1]"

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


# ---------------------------------------------------------------------------
# Shared seams: compaction input + durable-context reinjection (#3190 review)
# ---------------------------------------------------------------------------


class TestRedactTextSharedSeam:
    def test_none_config_returns_text_unchanged(self):
        assert redact_text("alice@example.com", None) == "alice@example.com"

    def test_disabled_config_returns_text_unchanged(self):
        assert redact_text("alice@example.com", PiiRedactionConfig(enabled=False)) == "alice@example.com"

    def test_enabled_config_redacts(self):
        assert redact_text("call alice@example.com", PiiRedactionConfig(enabled=True)) == "call [EMAIL_1]"

    def test_non_string_passthrough(self):
        assert redact_text(None, PiiRedactionConfig(enabled=True)) is None


class _StateRequest:
    """Duck-typed ModelRequest carrying .state, .messages and .override()."""

    def __init__(self, state, messages):
        self.state = state
        self.messages = list(messages)

    def override(self, **kwargs):
        copy = object.__new__(type(self))
        copy.state = kwargs.get("state", self.state)
        copy.messages = kwargs.get("messages", self.messages)
        return copy


class TestDurableContextReinjection:
    def _make_dc(self, config):
        from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

        return DurableContextMiddleware(pii_redaction_config=config)

    def test_reinjected_summary_redacted(self):
        mw = self._make_dc(PiiRedactionConfig(enabled=True))
        request = _StateRequest({"summary_text": "summary of alice@example.com"}, [HumanMessage("hi")])
        final = mw._inject(request)
        # insert_after_leading_system_messages puts the injected pair up front:
        # [authority SystemMessage, durable-context data block, original…].
        block = final.messages[1].content
        assert "[EMAIL_1]" in block and "alice@example.com" not in block

    def test_reinjected_summary_untouched_without_config(self):
        mw = self._make_dc(None)
        request = _StateRequest({"summary_text": "summary of alice@example.com"}, [HumanMessage("hi")])
        final = mw._inject(request)
        assert "alice@example.com" in final.messages[1].content

    def test_policy_declares_pii_gate(self):
        enabled = self._make_dc(PiiRedactionConfig(enabled=True)).release_policy_parameters()
        disabled = self._make_dc(None).release_policy_parameters()
        assert enabled["pii_redaction_enabled"] is True
        assert disabled["pii_redaction_enabled"] is False


class TestSummarizationCompactionInput:
    def _middleware(self, pii_config):
        from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

        model = MagicMock()
        model.invoke.return_value = SimpleNamespace(text="compressed")
        model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed"))
        model.with_config.return_value = model
        return DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=len,
            app_config=SimpleNamespace(pii_redaction=pii_config),
        )

    def test_compaction_input_redacted(self):
        mw = self._middleware(PiiRedactionConfig(enabled=True))
        prompt = mw._build_summary_prompt([HumanMessage("reach alice@example.com")], previous_summary=None)
        assert prompt is not None
        assert "[EMAIL_1]" in prompt and "alice@example.com" not in prompt

    def test_compaction_input_untouched_when_disabled(self):
        mw = self._middleware(PiiRedactionConfig(enabled=False))
        prompt = mw._build_summary_prompt([HumanMessage("reach alice@example.com")], previous_summary=None)
        assert "alice@example.com" in prompt


class _RecordingPiiModel(FakeToolCallingModel):
    seen: list[str] = Field(default_factory=list)
    echo_summary: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = get_buffer_string(messages)
        self.seen.append(text)
        if self.echo_summary:
            # Preserve the exact placeholder received, rather than inventing one.
            token = re.search(r"\[EMAIL_[0-9]+\]", text).group(0)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"Alice's email is {token}"))])
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_async_graph_redacts_configured_title_model_input(monkeypatch, enabled):
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.title_config import TitleConfig
    from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

    pii = PiiRedactionConfig(enabled=enabled)
    config = _wiring_app_config(pii_redaction=pii, title=TitleConfig(enabled=True, model_name="title-model"))
    primary = _RecordingPiiModel(responses=[AIMessage(content="Reply to charlie@example.net")])
    title = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="Contact records")))
    monkeypatch.setattr("deerflow.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: title)
    graph = create_agent(primary, tools=[], state_schema=ThreadState, middleware=[PiiRedactionMiddleware(pii), TitleMiddleware(app_config=config)])
    user = HumanMessage(content="Contact alice@example.com", additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "Contact alice@example.com"})

    result = await graph.ainvoke({"messages": [user]})

    prompt = title.ainvoke.await_args.args[0]
    assert result["title"] == "Contact records"
    assert result["messages"][0].content == user.content
    if enabled:
        assert "alice@example.com" not in primary.seen[0]
        assert "alice@example.com" not in prompt
        assert "charlie@example.net" not in prompt
        assert "[EMAIL_1]" in prompt and "[EMAIL_2]" in prompt
    else:
        assert "alice@example.com" in primary.seen[0]
        assert "alice@example.com" in prompt and "charlie@example.net" in prompt


@pytest.mark.parametrize("async_mode", [False, True])
def test_compiled_graph_keeps_summary_and_retained_pii_distinct(async_mode):
    import asyncio

    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
    from deerflow.agents.thread_state import ThreadState

    pii = PiiRedactionConfig(enabled=True)
    config = _wiring_app_config(pii_redaction=pii)
    summary = _RecordingPiiModel(responses=[AIMessage(content="unused")], echo_summary=True)
    primary = _RecordingPiiModel(responses=[AIMessage(content="done")])
    graph = create_agent(
        primary,
        tools=[],
        state_schema=ThreadState,
        middleware=[
            PiiRedactionMiddleware(pii),
            DurableContextMiddleware(pii_redaction_config=pii),
            DeerFlowSummarizationMiddleware(model=summary, trigger=("messages", 4), keep=("messages", 2), token_counter=len, app_config=config),
        ],
    )
    messages = [HumanMessage(content="Alice's email is alice@example.com"), AIMessage(content="Noted"), HumanMessage(content="Bob's email is bob@example.com; keep their records separate"), AIMessage(content="Noted")]
    state = {"messages": messages}
    result = asyncio.run(graph.ainvoke(state)) if async_mode else graph.invoke(state)

    assert summary.seen and "alice@example.com" not in summary.seen[0]
    assert result["summary_text"] == "Alice's email is [EMAIL_1]"
    assert "Alice's email is [EMAIL_1]" in primary.seen[0]
    assert "Bob's email is [EMAIL_2]" in primary.seen[0]
    assert "bob@example.com" not in primary.seen[0]
    assert any(message.content == messages[2].content for message in result["messages"])


def test_summary_redaction_reserves_existing_placeholders():
    config = PiiRedactionConfig(enabled=True)
    assert redact_text("Alice [EMAIL_1], Bob bob@example.com", config) == "Alice [EMAIL_1], Bob [EMAIL_2]"


def test_existing_placeholder_in_later_content_block_is_reserved_first():
    messages, _ = _run_model_call(_make_middleware(), [HumanMessage(content=["bob@example.com", {"type": "text", "text": "Alice [EMAIL_1]"}])])
    assert messages[0].content == ["[EMAIL_2]", {"type": "text", "text": "Alice [EMAIL_1]"}]


def test_raw_legacy_summary_and_retained_messages_share_request_allocation():
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    pii = PiiRedactionConfig(enabled=True)
    state = {"summary_text": "Alice alice@example.com"}
    request = _StateRequest(state, [HumanMessage(content="Alice alice@example.com; Bob bob@example.com")])
    redacted = PiiRedactionMiddleware(pii)._process_request(request)
    final = DurableContextMiddleware(pii_redaction_config=pii)._inject(redacted)
    text = get_buffer_string(final.messages)
    assert "Alice [EMAIL_1]" in text and "Bob [EMAIL_2]" in text
    assert "alice@example.com" not in text and "bob@example.com" not in text
    assert state == {"summary_text": "Alice alice@example.com"}
    assert request.messages[0].content == "Alice alice@example.com; Bob bob@example.com"


def test_repeated_compaction_reserves_prior_summary_tokens():
    middleware = TestSummarizationCompactionInput()._middleware(PiiRedactionConfig(enabled=True))
    prompt = middleware._build_summary_prompt([HumanMessage("Carol carol@example.com")], previous_summary="Alice [EMAIL_1], Bob [EMAIL_2]")
    assert "Alice [EMAIL_1], Bob [EMAIL_2]" in prompt
    assert "Carol [EMAIL_3]" in prompt


def test_title_redacts_identifiers_before_field_truncation():
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    config = _wiring_app_config(pii_redaction=PiiRedactionConfig(enabled=True))
    prompt, fallback = TitleMiddleware(app_config=config)._build_title_prompt({"messages": [HumanMessage(content="x " * 246 + "alice@example.com"), AIMessage(content="done")]})
    assert "alice" not in prompt
    assert fallback.endswith("alice@example.com")  # Local display fallback preserves the original user text.
