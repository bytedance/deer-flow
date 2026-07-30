"""Tests for SystemMessageCoalescingMiddleware.

Verifies that ``request.system_message`` and in-``messages`` SystemMessages are
merged into a single leading SystemMessage before the request reaches the LLM,
fixing the "System message must be at the beginning" error on strict
OpenAI-compatible backends (vLLM, SGLang, Qwen) and Anthropic.

On langchain >= 1.2.15 the static system prompt lives in the separate
``request.system_message`` field, not in ``request.messages``. The model-call
handler flattens them at the very last moment (``[system_message, *messages]``),
so tests must build requests with the same split to exercise the real code path.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.system_message_coalescing_middleware import (
    SystemMessageCoalescingMiddleware,
    _coalesce_request,
    _flatten_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(system_message: SystemMessage | None, messages: list[BaseMessage]):
    """Build a minimal ModelRequest stand-in matching langchain 1.2.15 shape.

    ``system_message`` and ``messages`` are separate fields — the handler
    flattens them into ``[system_message, *messages]`` only at call time.
    """
    request = MagicMock()
    request.system_message = system_message
    request.messages = list(messages)
    request.override = lambda **updates: _override_request(request, updates)
    return request


def _override_request(request, updates):
    """Mimic ModelRequest.override(): return a copy with fields replaced."""
    new = MagicMock()
    new.system_message = updates.get("system_message", request.system_message)
    new.messages = updates.get("messages", request.messages)
    new.override = lambda **kw: _override_request(new, kw)
    return new


def _capture_handler():
    """Return (captured_requests, handler) that records what was sent."""
    captured = []

    def handler(req):
        captured.append(req)
        return "response"

    return captured, handler


def _final_payload(request) -> list[BaseMessage]:
    """Simulate what the LLM receives: [system_message, *messages] (if set)."""
    if request.system_message is not None:
        return [request.system_message, *request.messages]
    return list(request.messages)


# ===========================================================================
# _coalesce_request (pure helper)
# ===========================================================================


class TestCoalesceRequest:
    def test_no_system_anywhere_returns_none(self):
        """Zero SystemMessages → passthrough."""
        request = _make_request(system_message=None, messages=[HumanMessage(content="hi")])
        assert _coalesce_request(request) is None

    def test_only_system_message_field_returns_none(self):
        """system_message set, no SystemMessages in messages → passthrough.

        The single system block is already in the right place; coalescing would
        just create a new object with the same content (zero drift).
        """
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        assert _coalesce_request(request) is None

    def test_system_message_plus_one_in_msg_system_coalesces(self):
        """system_message + 1 in-messages SystemMessage → merge into system_message."""
        prompt = SystemMessage(content="You are DeerFlow.", id="sys-1")
        reminder = SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1")
        user = HumanMessage(content="Hello", id="msg-1__user")
        request = _make_request(system_message=prompt, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message is not None
        assert "You are DeerFlow." in result.system_message.content
        assert "<system-reminder>date</system-reminder>" in result.system_message.content
        # messages no longer contain any SystemMessage
        assert not any(isinstance(m, SystemMessage) for m in result.messages)
        # user message preserved
        assert any(m.content == "Hello" for m in result.messages)

    def test_system_message_plus_two_in_msg_systems_coalesces(self):
        """system_message + 2 non-reminder SystemMessages → merge all (no dedup)."""
        prompt = SystemMessage(content="prompt")
        reminder = SystemMessage(content="<system-reminder>day1</system-reminder>")
        date_update = SystemMessage(content="<system-reminder>day2</system-reminder>")
        user = HumanMessage(content="next")
        request = _make_request(system_message=prompt, messages=[reminder, date_update, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "day1" in result.system_message.content
        assert "day2" in result.system_message.content

    def test_no_system_message_but_in_msg_systems_coalesces(self):
        """system_message is None, but messages has SystemMessages → move to system_message."""
        reminder = SystemMessage(content="reminder")
        user = HumanMessage(content="hi")
        request = _make_request(system_message=None, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message is not None
        assert "reminder" in result.system_message.content
        assert not any(isinstance(m, SystemMessage) for m in result.messages)

    def test_merged_content_uses_double_newline_separator(self):
        """System contents are joined with \\n\\n."""
        prompt = SystemMessage(content="PART_A")
        reminder = SystemMessage(content="PART_B")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.content == "PART_A\n\nPART_B"

    def test_merged_preserves_first_system_message_id(self):
        """The merged SystemMessage keeps the id of system_message (first in order)."""
        prompt = SystemMessage(content="prompt", id="sys-1")
        reminder = SystemMessage(content="reminder", id="msg-1")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.id == "sys-1"

    def test_merged_preserves_in_msg_id_when_no_system_message(self):
        """When system_message is None, merged id comes from the first in-msg system."""
        reminder = SystemMessage(content="reminder", id="msg-1")
        request = _make_request(system_message=None, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.id == "msg-1"

    def test_non_system_messages_keep_original_order(self):
        """HumanMessage/AIMessage order is preserved after coalescing."""
        prompt = SystemMessage(content="prompt")
        user1 = HumanMessage(content="u1", id="u1")
        ai = AIMessage(content="a1", id="a1")
        reminder = SystemMessage(content="reminder")
        user2 = HumanMessage(content="u2", id="u2")
        request = _make_request(system_message=prompt, messages=[user1, ai, reminder, user2])

        result = _coalesce_request(request)
        assert result is not None
        non_system = result.messages
        assert [m.id for m in non_system] == ["u1", "a1", "u2"]

    def test_merged_kwargs_combine_all_parts(self):
        """additional_kwargs from all parts are merged into the result."""
        prompt = SystemMessage(
            content="prompt",
            id="sys-1",
            additional_kwargs={"source": "prompt"},
        )
        reminder = SystemMessage(
            content="reminder",
            id="msg-1",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.additional_kwargs == {
            "source": "prompt",
            "hide_from_ui": True,
            "dynamic_context_reminder": True,
        }

    def test_merged_kwargs_later_parts_override(self):
        """When two parts share a key, the later part's value wins."""
        prompt = SystemMessage(
            content="prompt",
            id="sys-1",
            additional_kwargs={"priority": "low"},
        )
        reminder = SystemMessage(
            content="reminder",
            id="msg-1",
            additional_kwargs={"priority": "high"},
        )
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert result.system_message.additional_kwargs["priority"] == "high"

    def test_merged_handles_list_content(self):
        """List-type SystemMessage content is flattened before joining."""
        prompt = SystemMessage(
            content=[{"type": "text", "text": "You are DeerFlow."}],
            id="sys-1",
        )
        reminder = SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1")
        request = _make_request(system_message=prompt, messages=[reminder])

        result = _coalesce_request(request)
        assert result is not None
        assert "You are DeerFlow." in result.system_message.content
        assert "<system-reminder>date</system-reminder>" in result.system_message.content

    def test_reminder_dedup_keeps_only_last(self):
        """When multiple SystemMessages have dynamic_context_reminder=True,
        only the last one survives; earlier ones are dropped."""
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        day1 = SystemMessage(
            content="<system-reminder>day1</system-reminder>",
            id="msg-1",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        day2 = SystemMessage(
            content="<system-reminder>day2</system-reminder>",
            id="msg-2",
            additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[day1, day2, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "day2" in result.system_message.content
        assert "day1" not in result.system_message.content

    def test_reminder_dedup_does_not_affect_non_reminder_systems(self):
        """SystemMessages without dynamic_context_reminder are never deduplicated."""
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        other = SystemMessage(content="custom system block", id="msg-1")
        reminder = SystemMessage(
            content="<system-reminder>day2</system-reminder>",
            id="msg-2",
            additional_kwargs={"dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[other, reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "custom system block" in result.system_message.content
        assert "day2" in result.system_message.content

    def test_single_reminder_not_deduplicated(self):
        """A single reminder SystemMessage is kept — no dedup needed."""
        prompt = SystemMessage(content="prompt", id="sys-prompt")
        reminder = SystemMessage(
            content="<system-reminder>date</system-reminder>",
            id="msg-1",
            additional_kwargs={"dynamic_context_reminder": True},
        )
        user = HumanMessage(content="hi")
        request = _make_request(system_message=prompt, messages=[reminder, user])

        result = _coalesce_request(request)
        assert result is not None
        assert "prompt" in result.system_message.content
        assert "date" in result.system_message.content


# ===========================================================================
# _flatten_content (pure helper)
# ===========================================================================


class TestFlattenContent:
    def test_string_content_returns_same_string(self):
        assert _flatten_content("hello") == "hello"

    def test_list_of_strings(self):
        assert _flatten_content(["line1", "line2"]) == "line1\nline2"

    def test_list_of_text_dicts(self):
        content = [{"type": "text", "text": "paragraph1"}, {"type": "text", "text": "paragraph2"}]
        assert _flatten_content(content) == "paragraph1\nparagraph2"

    def test_mixed_list(self):
        content = ["plain", {"type": "text", "text": "dict"}, 42]
        assert _flatten_content(content) == "plain\ndict\n42"

    def test_non_string_non_list(self):
        assert _flatten_content(42) == "42"


# ===========================================================================
# SystemMessageCoalescingMiddleware.wrap_model_call
# ===========================================================================


class TestWrapModelCall:
    def test_passthrough_when_no_in_msg_systems(self):
        """No SystemMessages in messages → same request object passed through."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)
        assert captured[0] is request

    def test_override_called_when_in_msg_systems_present(self):
        """system_message + in-msg SystemMessage → override with coalesced request."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder"), HumanMessage(content="hi")],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        assert sent is not request  # overridden
        assert sent.system_message is not None
        assert "prompt" in sent.system_message.content
        assert "reminder" in sent.system_message.content
        assert not any(isinstance(m, SystemMessage) for m in sent.messages)

    def test_returns_handler_result(self):
        """wrap_model_call returns whatever the handler returns."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder")],
        )
        handler = MagicMock(return_value="llm-response")

        result = mw.wrap_model_call(request, handler)
        assert result == "llm-response"


# ===========================================================================
# SystemMessageCoalescingMiddleware.awrap_model_call
# ===========================================================================


class TestAwrapModelCall:
    @pytest.mark.asyncio
    async def test_async_passthrough_no_in_msg_systems(self):
        """Async path: no in-msg systems → passthrough."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[HumanMessage(content="hi")],
        )
        captured = []

        async def handler(req):
            captured.append(req)
            return "async-response"

        result = await mw.awrap_model_call(request, handler)
        assert result == "async-response"
        assert captured[0] is request

    @pytest.mark.asyncio
    async def test_async_coalesces_in_msg_systems(self):
        """Async path: system_message + in-msg system → coalesced."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt"),
            messages=[SystemMessage(content="reminder"), HumanMessage(content="hi")],
        )
        captured = []

        async def handler(req):
            captured.append(req)
            return "ok"

        result = await mw.awrap_model_call(request, handler)
        assert result == "ok"
        sent = captured[0]
        assert sent is not request
        assert "prompt" in sent.system_message.content
        assert "reminder" in sent.system_message.content


# ===========================================================================
# Realistic scenario: DynamicContextMiddleware ID-swap + create_agent prompt
# ===========================================================================


class TestRealisticScenario:
    def test_first_turn_single_system_message_in_final_payload(self):
        """Simulate the exact #3707 trigger with the real request shape.

        DynamicContextMiddleware injects the reminder into state["messages"]
        (which becomes request.messages). create_agent holds system_prompt in
        request.system_message. Without coalescing, the handler produces
        [system_prompt, reminder, __memory, __user] → 2 SystemMessages → 400.

        With coalescing, the final payload [system_message, *messages] has
        exactly 1 SystemMessage.
        """
        mw = SystemMessageCoalescingMiddleware()
        # Real shape: system_prompt in system_message field, reminder in messages
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow 2.0, an AI assistant...", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>\n<current_date>2026-06-22, Monday</current_date>\n</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="<memory>User prefers Python.</memory>", id="msg-1__memory"),
                HumanMessage(content="What is the capital of France?", id="msg-1__user"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        # Simulate what the LLM receives: [system_message, *messages]
        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1  # key assertion: only 1 SystemMessage
        assert "DeerFlow 2.0" in final[0].content
        assert "<current_date>2026-06-22, Monday</current_date>" in final[0].content
        # User-owned memory stays as HumanMessage (OWASP LLM01 preserved)
        assert any(isinstance(m, HumanMessage) and "User prefers Python." in m.content for m in final)
        assert any(isinstance(m, HumanMessage) and m.content == "What is the capital of France?" for m in final)

    def test_midnight_crossing_single_system_message_in_final_payload(self):
        """Midnight crossing: 3 SystemMessages total → coalesced to 1.

        DynamicContextMiddleware injects date reminders marked with
        ``dynamic_context_reminder=True``. On midnight crossings a second
        reminder (day2) appears after Human/AI turns. During coalescing the
        intervening turns that originally separated the two reminders are
        stripped from the merged block, so two contradictory <current_date>
        blocks would appear adjacent. The middleware keeps only the last
        reminder (day2) and drops earlier ones (day1) so the model sees a
        single unambiguous current date.
        """
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="system prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="<memory>...</memory>", id="msg-1__memory"),
                HumanMessage(content="first question", id="msg-1__user"),
                AIMessage(content="first answer", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True},
                ),
                HumanMessage(content="second question", id="msg-2__user"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1
        merged = final[0]
        assert "system prompt" in merged.content
        # Only the latest date survives; the stale day1 reminder is dropped.
        assert "day2" in merged.content
        assert "day1" not in merged.content
        # Non-system messages in order
        non_system = [m for m in final if not isinstance(m, SystemMessage)]
        assert [m.content for m in non_system] == [
            "<memory>...</memory>",
            "first question",
            "first answer",
            "second question",
        ]

    def test_no_system_message_field_but_in_msg_systems(self):
        """Edge case: system_message is None but messages has a SystemMessage.

        The coalesced SystemMessage moves to the system_message field so the
        handler still prepends it as a leading system block.
        """
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=None,
            messages=[
                SystemMessage(content="reminder", id="msg-1"),
                HumanMessage(content="hi"),
            ],
        )
        captured, handler = _capture_handler()

        mw.wrap_model_call(request, handler)

        sent = captured[0]
        final = _final_payload(sent)
        system_count = sum(1 for m in final if isinstance(m, SystemMessage))
        assert system_count == 1
        assert "reminder" in final[0].content


# ===========================================================================
# Strict-backend stub: end-to-end test against vLLM/SGLang/Qwen rejection
# ===========================================================================


class StrictBackendError(Exception):
    """Simulates the 400 Bad Request from strict OpenAI-compatible backends.

    Qwen, SGLang, and vLLM reject requests that contain more than one
    SystemMessage or where the sole SystemMessage is not at position 0.
    """


def _strict_backend_handler(request):
    """Simulate a strict OpenAI-compatible backend (Qwen / SGLang / vLLM).

    These backends accept exactly 0 or 1 SystemMessage, and if present it
    must be at position 0. They reject with "System message must be at the
    beginning" or "Received multiple system messages" otherwise.

    The handler flattens the request into ``[system_message, *messages]``
    (matching ``create_agent``'s ``_execute_model_sync``) then validates.
    """
    final = _final_payload(request)
    system_count = sum(1 for m in final if isinstance(m, SystemMessage))
    if system_count > 1:
        raise StrictBackendError("Received multiple system messages")
    if system_count == 1 and not isinstance(final[0], SystemMessage):
        raise StrictBackendError("System message must be at the beginning")
    return "ok"


async def _async_strict_backend_handler(request):
    """Async variant of ``_strict_backend_handler`` for awrap_model_call tests."""
    return _strict_backend_handler(request)


class TestStrictBackendStub:
    """End-to-end test against a strict-backend stub.

    Builds the request the way create_agent does (prompt in system_message,
    not messages) and asserts that:
    - Without middleware, the strict stub raises StrictBackendError (#3707 bug)
    - With middleware, the strict stub accepts the request (fix confirmed)
    """

    def test_first_turn_without_middleware_rejects(self):
        """Reproduce #3707: raw request → handler flattens to 2 SystemMessages → stub rejects."""
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow.", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        # Final payload: [sys-prompt, reminder, __user] → 2 SystemMessages
        # → strict backend rejects: multiple system messages
        with pytest.raises(StrictBackendError):
            _strict_backend_handler(request)

    def test_first_turn_with_middleware_accepts(self):
        """Fix confirmed: middleware coalesces → 1 SystemMessage → stub accepts."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="You are DeerFlow.", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        result = mw.wrap_model_call(request, _strict_backend_handler)
        assert result == "ok"

    def test_midnight_crossing_without_middleware_rejects(self):
        """3 SystemMessages without middleware → stub rejects."""
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q1", id="msg-1__user"),
                AIMessage(content="a1", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q2", id="msg-2__user"),
            ],
        )
        with pytest.raises(StrictBackendError):
            _strict_backend_handler(request)

    def test_midnight_crossing_with_middleware_accepts(self):
        """3 SystemMessages with middleware → coalesced to 1 → stub accepts.

        Only the latest reminder (day2) survives in the merged content;
        the stale day1 reminder is dropped.
        """
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(
                    content="<system-reminder>day1</system-reminder>",
                    id="msg-1",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q1", id="msg-1__user"),
                AIMessage(content="a1", id="ai-1"),
                SystemMessage(
                    content="<system-reminder>day2</system-reminder>",
                    id="msg-2",
                    additional_kwargs={"dynamic_context_reminder": True},
                ),
                HumanMessage(content="q2", id="msg-2__user"),
            ],
        )
        result = mw.wrap_model_call(request, _strict_backend_handler)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_async_path_with_middleware_accepts(self):
        """Async path: middleware + strict stub → accepts."""
        mw = SystemMessageCoalescingMiddleware()
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[
                SystemMessage(content="<system-reminder>date</system-reminder>", id="msg-1"),
                HumanMessage(content="Hello", id="msg-1__user"),
            ],
        )
        result = await mw.awrap_model_call(request, _async_strict_backend_handler)
        assert result == "ok"

    def test_clean_request_no_middleware_needed(self):
        """Only system_message field, no in-msg systems → stub accepts without middleware."""
        request = _make_request(
            system_message=SystemMessage(content="prompt", id="sys-prompt"),
            messages=[HumanMessage(content="hi")],
        )
        # No middleware needed — single SystemMessage at position 0
        result = _strict_backend_handler(request)
        assert result == "ok"
