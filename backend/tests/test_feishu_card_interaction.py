"""Tests for the Feishu interactive-card clarification module (outbound half).

Boundary tests only: what the module emits (card payloads, registry state
transitions), never its internals.
"""

from __future__ import annotations

import json
import time

import pytest

from app.channels.feishu_card_interaction import (
    MAX_CARD_OPTIONS,
    ClarificationCardRequest,
    PendingCardRegistry,
    build_button_card,
)


def _metadata(payload: dict | None) -> dict:
    return {} if payload is None else {"human_input_request": payload}


def _payload(**overrides) -> dict:
    base = {
        "version": 1,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": "clarification:call_1",
        "question": "Pick one",
        "input_mode": "choice_with_other",
        "options": [
            {"id": "option-1", "label": "Alpha", "value": "Alpha"},
            {"id": "option-2", "label": "Beta", "value": "Beta"},
        ],
    }
    base.update(overrides)
    return base


class TestClarificationCardRequestExtraction:
    def test_absent_payload_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata(None)) is None

    def test_free_text_mode_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata(_payload(input_mode="free_text", options=[]))) is None

    def test_form_mode_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata(_payload(version=2, input_mode="form", fields=[{"key": "x"}]))) is None

    def test_empty_options_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata(_payload(options=[]))) is None

    def test_overflow_options_returns_none(self):
        options = [{"id": f"option-{i}", "label": f"L{i}", "value": f"L{i}"} for i in range(1, MAX_CARD_OPTIONS + 2)]
        assert ClarificationCardRequest.from_metadata(_metadata(_payload(options=options))) is None

    def test_choice_with_options_extracts(self):
        req = ClarificationCardRequest.from_metadata(_metadata(_payload()))
        assert req is not None
        assert req.request_id == "clarification:call_1"
        assert req.question == "Pick one"
        assert req.options == ("Alpha", "Beta")

    def test_malformed_payload_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata({"kind": "other"})) is None
        assert ClarificationCardRequest.from_metadata({"human_input_request": "not-a-dict"}) is None


class TestBuildButtonCard:
    def test_card_structure_binds_buttons_to_request(self):
        req = ClarificationCardRequest.from_metadata(_metadata(_payload()))
        card = json.loads(build_button_card(req))

        assert card["header"]["title"]["content"]
        elements = card["elements"]
        markdown = next(e for e in elements if e["tag"] == "markdown")
        assert "Pick one" in markdown["content"]

        actions = next(e for e in elements if e["tag"] == "action")["actions"]
        assert len(actions) == 2
        for i, (action, label) in enumerate(zip(actions, ("Alpha", "Beta")), start=1):
            assert action["tag"] == "button"
            assert action["text"]["content"] == label
            assert action["value"]["request_id"] == "clarification:call_1"
            assert action["value"]["option_id"] == f"option-{i}"
            assert action["value"]["option_value"] == label
        assert actions[0]["type"] == "primary"
        assert actions[1]["type"] == "default"


class TestPendingCardRegistry:
    def _entry(self, request_id: str = "clarification:call_1", **overrides) -> dict:
        entry = {
            "request_id": request_id,
            "thread_id": "thread-1",
            "chat_id": "chat-1",
            "originator_open_id": "ou_originator",
            "options": ("Alpha", "Beta"),
        }
        entry.update(overrides)
        return entry

    def test_register_then_consume_returns_entry_once(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        entry = registry.consume("clarification:call_1")
        assert entry is not None
        assert entry["originator_open_id"] == "ou_originator"
        assert registry.consume("clarification:call_1") is None  # one-time

    def test_unknown_request_id_consumes_to_none(self):
        registry = PendingCardRegistry()
        assert registry.consume("clarification:nope") is None

    def test_expired_entry_consumes_to_none(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        future = time.time() + 31 * 60
        assert registry.consume("clarification:call_1", now=future) is None

    def test_mark_sent_backfills_card_message_id(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        registry.mark_sent("clarification:call_1", "om_card_1")
        entry = registry.consume("clarification:call_1")
        assert entry is not None
        assert entry["card_message_id"] == "om_card_1"

    def test_reregister_same_request_id_replaces(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        registry.register(**self._entry(originator_open_id="ou_new"))
        entry = registry.consume("clarification:call_1")
        assert entry["originator_open_id"] == "ou_new"
        assert registry.consume("clarification:call_1") is None


class TestFeishuChannelButtonCardWiring:
    """Channel-level wiring: when the flag and payload line up, final
    clarification outbounds go out as button cards; everything else is
    byte-identical to today's plain-text path."""

    def _channel(self, *, enabled: bool):
        from unittest.mock import AsyncMock

        from app.channels.feishu import FeishuChannel
        from app.channels.message_bus import MessageBus

        channel = FeishuChannel(MessageBus(), {"app_id": "test", "app_secret": "test", "card_interaction_enabled": enabled})
        channel._reply_card = AsyncMock(return_value="om_card_final")
        channel._update_card = AsyncMock()
        channel._add_reaction = AsyncMock()
        channel._remember_thread_mapping = AsyncMock()
        return channel

    def _clarification_outbound(self, *, with_options: bool = True):
        from app.channels.message_bus import (
            HUMAN_INPUT_REQUEST_METADATA_KEY,
            PENDING_CLARIFICATION_METADATA_KEY,
            OutboundMessage,
        )

        metadata = {
            PENDING_CLARIFICATION_METADATA_KEY: True,
            "user_id": "ou_originator",
            "topic_id": "topic-1",
            "message_id": "om_src",
        }
        if with_options:
            metadata[HUMAN_INPUT_REQUEST_METADATA_KEY] = {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": "clarification:call_1",
                "question": "Pick one",
                "input_mode": "choice_with_other",
                "options": [
                    {"id": "option-1", "label": "Alpha", "value": "Alpha"},
                    {"id": "option-2", "label": "Beta", "value": "Beta"},
                ],
            }
        else:
            metadata[HUMAN_INPUT_REQUEST_METADATA_KEY] = {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": "clarification:call_2",
                "question": "Say anything",
                "input_mode": "free_text",
            }
        return OutboundMessage(
            channel_name="feishu",
            chat_id="chat-1",
            thread_id="thread-1",
            text="Pick one",
            is_final=True,
            thread_ts="om_src",
            metadata=metadata,
        )

    @pytest.mark.asyncio
    async def test_flag_on_options_renders_button_card_and_registers(self):
        channel = self._channel(enabled=True)
        await channel._send_card_message(self._clarification_outbound())

        card_json = channel._reply_card.call_args.args[1]
        card = json.loads(card_json)
        assert any(e.get("tag") == "action" for e in card["elements"])

        entry = channel._card_registry.consume("clarification:call_1")
        assert entry is not None
        assert entry["originator_open_id"] == "ou_originator"
        assert entry["thread_id"] == "thread-1"
        assert entry["card_message_id"] == "om_card_final"

    @pytest.mark.asyncio
    async def test_flag_off_falls_back_to_plain_card(self):
        channel = self._channel(enabled=False)
        await channel._send_card_message(self._clarification_outbound())

        # Plain-text path: markdown text, no raw-card bypass, nothing registered.
        text_arg = channel._reply_card.call_args.args[1]
        assert "Pick one" in text_arg
        assert '"action"' not in text_arg
        assert channel._reply_card.call_args.kwargs.get("raw_card_content") is not True
        assert channel._card_registry.consume("clarification:call_1") is None

    @pytest.mark.asyncio
    async def test_flag_on_free_text_falls_back_to_plain_card(self):
        channel = self._channel(enabled=True)
        await channel._send_card_message(self._clarification_outbound(with_options=False))

        text_arg = channel._reply_card.call_args.args[1]
        assert '"action"' not in text_arg
        assert channel._reply_card.call_args.kwargs.get("raw_card_content") is not True
        assert channel._card_registry.consume("clarification:call_2") is None

    @pytest.mark.asyncio
    async def test_running_card_is_updated_into_button_card(self):
        channel = self._channel(enabled=True)
        channel._running_card_ids["om_src"] = "om_running"

        await channel._send_card_message(self._clarification_outbound())

        card_json = channel._update_card.call_args.args[1]
        card = json.loads(card_json)
        assert any(e.get("tag") == "action" for e in card["elements"])
        entry = channel._card_registry.consume("clarification:call_1")
        assert entry["card_message_id"] == "om_running"


class TestConsumeIfOriginator:
    """Atomic validate-and-consume for card clicks. Identity mismatch must NOT
    consume the entry (the real originator may still click later)."""

    def _registry_with_entry(self):
        registry = PendingCardRegistry()
        registry.register(
            request_id="clarification:call_1",
            thread_id="thread-1",
            chat_id="chat-1",
            originator_open_id="ou_originator",
            options=("Alpha", "Beta"),
            card_message_id="om_card_1",
        )
        return registry

    def test_originator_consumes_and_gets_entry(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("clarification:call_1", "ou_originator")
        assert reason is None
        assert entry is not None
        assert entry["card_message_id"] == "om_card_1"
        # replayed click: entry already gone
        entry2, reason2 = registry.consume_if_originator("clarification:call_1", "ou_originator")
        assert entry2 is None
        assert reason2 == "unknown"

    def test_non_originator_rejected_without_consuming(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("clarification:call_1", "ou_someone_else")
        assert entry is None
        assert reason == "not_originator"
        # the real originator can still click afterwards
        entry2, reason2 = registry.consume_if_originator("clarification:call_1", "ou_originator")
        assert reason2 is None
        assert entry2 is not None

    def test_unknown_request_id(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("clarification:nope", "ou_originator")
        assert entry is None
        assert reason == "unknown"

    def test_expired_entry_is_unknown(self):
        registry = self._registry_with_entry()
        future = time.time() + 31 * 60
        entry, reason = registry.consume_if_originator("clarification:call_1", "ou_originator", now=future)
        assert entry is None
        assert reason == "unknown"


def _make_card_action_event(*, request_id: str, option_value: str, option_id: str = "option-1", operator_open_id: str = "ou_originator"):
    """Build a minimal P2CardActionTrigger-shaped stand-in."""
    from unittest.mock import MagicMock

    event = MagicMock()
    event.event.action.value = {"request_id": request_id, "option_id": option_id, "option_value": option_value}
    event.event.operator.open_id = operator_open_id
    return event


class TestOnCardActionValidation:
    """Sync layer of the card-action callback: validation + toast, no state change."""

    def _channel(self):
        from unittest.mock import MagicMock

        from app.channels.feishu import FeishuChannel
        from app.channels.message_bus import MessageBus

        channel = FeishuChannel(MessageBus(), {"app_id": "t", "app_secret": "t", "card_interaction_enabled": True})
        channel._card_registry.register(
            request_id="clarification:call_1",
            thread_id="thread-1",
            chat_id="chat-1",
            originator_open_id="ou_originator",
            options=("Alpha", "Beta"),
            card_message_id="om_card_1",
        )
        channel._main_loop = MagicMock()
        channel._main_loop.is_running.return_value = True
        channel._submit_threadsafe_coroutine = MagicMock(return_value=True)

        class _Toast:
            pass

        class _Resp:
            pass

        channel._CallBackToast = _Toast
        channel._P2CardActionTriggerResponse = _Resp
        return channel

    def test_non_originator_gets_refusal_toast_and_entry_survives(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(request_id="clarification:call_1", option_value="Alpha", operator_open_id="ou_other"))
        assert resp.toast is not None
        assert "发起人" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_not_called()
        # entry not consumed: originator can still click
        entry, reason = channel._card_registry.consume_if_originator("clarification:call_1", "ou_originator")
        assert reason is None and entry is not None

    def test_unknown_request_id_gets_stale_toast(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(request_id="clarification:nope", option_value="Alpha"))
        assert resp.toast is not None
        assert "失效" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_not_called()

    def test_originator_gets_ack_toast_and_dispatches_async_resolution(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(request_id="clarification:call_1", option_value="Alpha"))
        assert resp.toast is not None
        assert "Alpha" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_called_once()
        # one-time: the entry is consumed by the click
        entry, reason = channel._card_registry.consume_if_originator("clarification:call_1", "ou_originator")
        assert entry is None and reason == "unknown"


class TestResolveCardClick:
    """Async layer: terminal card update + hidden synthetic inbound publication."""

    @pytest.mark.asyncio
    async def test_publishes_hidden_inbound_and_marks_card_resolved(self):
        from unittest.mock import AsyncMock

        from app.channels.feishu import FeishuChannel
        from app.channels.message_bus import HUMAN_INPUT_RESPONSE_METADATA_KEY, MessageBus

        bus = MessageBus()
        channel = FeishuChannel(bus, {"app_id": "t", "app_secret": "t", "card_interaction_enabled": True})
        channel._update_card = AsyncMock()

        published = []

        async def capture(msg):
            published.append(msg)
            return True

        channel._publish_inbound_or_drop = capture

        entry = {
            "request_id": "clarification:call_1",
            "thread_id": "thread-1",
            "chat_id": "chat-1",
            "originator_open_id": "ou_originator",
            "options": ("Alpha", "Beta"),
            "card_message_id": "om_card_1",
        }
        await channel._resolve_card_click(entry, option_id="option-1", option_value="Alpha", operator_open_id="ou_originator")

        # terminal card: no buttons, shows the choice
        assert channel._update_card.await_count == 1
        terminal_text = channel._update_card.await_args.args[1]
        assert "Alpha" in terminal_text

        # synthetic inbound: hidden human-input response routed at the card message
        assert len(published) == 1
        inbound = published[0]
        assert inbound.chat_id == "chat-1"
        assert inbound.user_id == "ou_originator"
        assert inbound.thread_ts == "om_card_1"
        response = inbound.metadata[HUMAN_INPUT_RESPONSE_METADATA_KEY]
        assert response["kind"] == "human_input_response"
        assert response["response_kind"] == "option"
        assert response["request_id"] == "clarification:call_1"
        assert response["value"] == "Alpha"
        assert inbound.metadata.get("hide_from_ui") is True
