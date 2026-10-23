"""Tests for the Feishu interactive-card clarification module (outbound half).

Rendering, ownership, one-time consumption and bounded registry lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.feishu_card_interaction import (
    MAX_CARD_OPTIONS,
    ClarificationCardRequest,
    PendingCardRegistry,
    build_button_card,
)
from app.channels.message_bus import HUMAN_INPUT_RESPONSE_METADATA_KEY, InboundMessage, MessageBus
from app.channels.store import JsonChannelStore


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

    def test_custom_option_ids_pass_through_to_buttons(self):
        req = ClarificationCardRequest.from_metadata(
            _metadata(
                _payload(
                    options=[
                        {"id": "approve", "label": "批准", "value": "批准"},
                        {"id": "reject", "label": "拒绝", "value": "拒绝"},
                    ]
                )
            )
        )
        assert req is not None
        card = json.loads(build_button_card(req))
        actions = next(e for e in card["elements"] if e["tag"] == "action")["actions"]
        assert [a["value"]["option_id"] for a in actions] == ["approve", "reject"]

    def test_malformed_payload_returns_none(self):
        assert ClarificationCardRequest.from_metadata(_metadata({"kind": "other"})) is None
        assert ClarificationCardRequest.from_metadata({"human_input_request": "not-a-dict"}) is None


class TestBuildButtonCard:
    def test_card_preserves_context_before_question(self):
        req = ClarificationCardRequest.from_metadata(_metadata(_payload(question="是否继续？", context="这将**永久删除**生产表中的数据。\n请先确认已有备份。")))
        assert req is not None

        card = json.loads(build_button_card(req))
        markdown = next(element for element in card["elements"] if element["tag"] == "markdown")
        assert markdown["content"] == "这将**永久删除**生产表中的数据。\n请先确认已有备份。\n\n是否继续？"

    @pytest.mark.parametrize("context", [None, "", " \t\n ", 42, ["background"]])
    def test_missing_or_invalid_context_keeps_question_only(self, context):
        req = ClarificationCardRequest.from_metadata(_metadata(_payload(context=context)))
        assert req is not None

        card = json.loads(build_button_card(req))
        markdown = next(element for element in card["elements"] if element["tag"] == "markdown")
        assert markdown["content"] == "Pick one"

    def test_card_structure_binds_buttons_to_request(self):
        req = ClarificationCardRequest.from_metadata(_metadata(_payload()))
        assert req is not None
        assert req.option_ids == ("option-1", "option-2")
        card = json.loads(build_button_card(req))

        assert card["config"]["update_multi"] is True
        assert card["header"]["title"]["content"]
        elements = card["elements"]
        markdown = next(e for e in elements if e["tag"] == "markdown")
        assert "Pick one" in markdown["content"]

        actions = next(e for e in elements if e["tag"] == "action")["actions"]
        assert len(actions) == 2
        for i, (action, label) in enumerate(zip(actions, ("Alpha", "Beta")), start=1):
            assert action["tag"] == "button"
            assert action["text"]["content"] == label
            assert action["value"]["callback_token"] == req.callback_token
            assert action["value"]["option_id"] == f"option-{i}"
            assert action["value"]["option_value"] == label
        assert actions[0]["type"] == "primary"
        assert actions[1]["type"] == "default"


class TestPendingCardRegistry:
    def _entry(self, request_id: str = "clarification:call_1", **overrides) -> dict:
        entry = {
            "callback_token": "callback-1",
            "request_id": request_id,
            "source": "ask_clarification",
            "thread_id": "thread-1",
            "chat_id": "chat-1",
            "originator_open_id": "ou_originator",
            "options": ("Alpha", "Beta"),
            "option_ids": ("option-1", "option-2"),
        }
        entry.update(overrides)
        return entry

    def test_register_then_consume_returns_entry_once(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry(topic_id="topic-1", connection_id="conn-1", owner_user_id="deer-user-1"))
        entry, reason = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason is None and entry is not None
        assert entry["originator_open_id"] == "ou_originator"
        assert entry["topic_id"] == "topic-1"
        assert entry["connection_id"] == "conn-1"
        assert entry["owner_user_id"] == "deer-user-1"
        entry2, _ = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry2 is None  # one-time

    def test_same_request_id_keeps_independent_cards(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        registry.register(**self._entry(callback_token="callback-2", originator_open_id="ou_new"))
        first, _ = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert first is not None and first["originator_open_id"] == "ou_originator"
        entry, _ = registry.consume_if_originator("callback-2", "ou_new", option_id="option-1", option_value="Alpha")
        assert entry is not None
        assert entry["originator_open_id"] == "ou_new"

    def test_duplicate_callback_token_cannot_replace_a_pending_card(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry())
        with pytest.raises(ValueError, match="already owns"):
            registry.register(**self._entry(request_id="clarification:other"))
        entry, _ = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is not None and entry["request_id"] == "clarification:call_1"

    def test_register_prunes_expired_cards_without_clicks(self, monkeypatch):
        clock = [100.0]
        monkeypatch.setattr("app.channels.feishu_card_interaction.time.time", lambda: clock[0])
        registry = PendingCardRegistry(ttl_seconds=10)
        registry.register(**self._entry())
        clock[0] += 11
        registry.register(**self._entry(callback_token="callback-2"))
        assert len(registry._entries) == 1
        entry, _ = registry.consume_if_originator("callback-2", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is not None

    def test_capacity_retires_oldest_card_and_keeps_new_cards_usable(self):
        registry = PendingCardRegistry(max_entries=2)
        for index in range(3):
            registry.register(**self._entry(callback_token=f"callback-{index}"))
        oldest, _ = registry.consume_if_originator("callback-0", "ou_originator", option_id="option-1", option_value="Alpha")
        assert oldest is None
        for index in (1, 2):
            entry, _ = registry.consume_if_originator(f"callback-{index}", "ou_originator", option_id="option-1", option_value="Alpha")
            assert entry is not None

    def test_discard_thread_retires_all_matching_cards(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry(callback_token="cb-1", thread_id="thread-target"))
        registry.register(**self._entry(callback_token="cb-2", thread_id="thread-target"))
        registry.register(**self._entry(callback_token="cb-3", thread_id="thread-other"))
        assert len(registry) == 3

        pruned = registry.discard_thread("thread-target")
        assert pruned == 2
        assert len(registry) == 1
        entry, _ = registry.consume_if_originator("cb-3", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is not None

    def test_prune_expired_removes_stale_cards_and_returns_count(self):
        registry = PendingCardRegistry(ttl_seconds=10)
        registry.register(**self._entry(callback_token="cb-fresh"))
        registry.register(**self._entry(callback_token="cb-stale"))
        registry._entries["cb-stale"]["created_at"] -= 15

        cleaned = registry.prune_expired()
        assert cleaned == 1
        assert len(registry) == 1
        assert "cb-fresh" in registry._entries
        assert "cb-stale" not in registry._entries

    def test_get_pending_entry_provides_read_only_view(self):
        registry = PendingCardRegistry()
        registry.register(**self._entry(callback_token="cb-inspect", thread_id="th-100"))
        view = registry.get_pending_entry("cb-inspect")
        assert view is not None
        assert view["thread_id"] == "th-100"
        assert len(registry) == 1
        consumed, _ = registry.consume_if_originator("cb-inspect", "ou_originator", option_id="option-1", option_value="Alpha")
        assert consumed is not None
        assert registry.get_pending_entry("cb-inspect") is None


class TestFeishuChannelButtonCardWiring:
    """Channel-level wiring: when the flag and payload line up, final
    clarification outbounds go out as button cards; everything else is
    byte-identical to today's plain-text path."""

    def _channel(self, *, enabled: bool, tmp_path):
        from unittest.mock import AsyncMock

        from app.channels.feishu import FeishuChannel
        from app.channels.message_bus import MessageBus

        channel = FeishuChannel(MessageBus(), {"app_id": "test", "app_secret": "test", "card_interaction_enabled": enabled, "channel_store": JsonChannelStore(path=tmp_path / "routes.json")})
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
    async def test_flag_on_options_renders_button_card_and_registers(self, tmp_path):
        channel = self._channel(enabled=True, tmp_path=tmp_path)
        await channel._send_card_message(self._clarification_outbound())

        card_json = channel._reply_card.call_args.args[1]
        card = json.loads(card_json)
        assert any(e.get("tag") == "action" for e in card["elements"])

        token = next(e for e in card["elements"] if e["tag"] == "action")["actions"][0]["value"]["callback_token"]
        entry, reason = channel._card_registry.consume_if_originator(token, "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason is None and entry is not None
        assert entry["originator_open_id"] == "ou_originator"
        assert entry["thread_id"] == "thread-1"
        assert entry["card_message_id"] == "om_card_final"

    @pytest.mark.asyncio
    async def test_flag_off_falls_back_to_plain_card(self, tmp_path):
        channel = self._channel(enabled=False, tmp_path=tmp_path)
        await channel._send_card_message(self._clarification_outbound())

        # Plain-text path: markdown text, no raw-card bypass, nothing registered.
        text_arg = channel._reply_card.call_args.args[1]
        assert "Pick one" in text_arg
        assert '"action"' not in text_arg
        assert channel._reply_card.call_args.kwargs.get("raw_card_content") is not True
        entry, _ = channel._card_registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is None

    @pytest.mark.asyncio
    async def test_flag_on_free_text_falls_back_to_plain_card(self, tmp_path):
        channel = self._channel(enabled=True, tmp_path=tmp_path)
        await channel._send_card_message(self._clarification_outbound(with_options=False))

        text_arg = channel._reply_card.call_args.args[1]
        assert '"action"' not in text_arg
        assert channel._reply_card.call_args.kwargs.get("raw_card_content") is not True
        entry, _ = channel._card_registry.consume_if_originator("clarification:call_2", "ou_originator", option_id="option-1", option_value="x")
        assert entry is None

    @pytest.mark.asyncio
    async def test_running_card_is_updated_into_button_card(self, tmp_path):
        channel = self._channel(enabled=True, tmp_path=tmp_path)
        channel._running_card_ids["om_src"] = "om_running"

        await channel._send_card_message(self._clarification_outbound())

        card_json = channel._update_card.call_args.args[1]
        card = json.loads(card_json)
        assert any(e.get("tag") == "action" for e in card["elements"])
        token = next(e for e in card["elements"] if e["tag"] == "action")["actions"][0]["value"]["callback_token"]
        entry, _ = channel._card_registry.consume_if_originator(token, "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is not None
        assert entry["card_message_id"] == "om_running"


class TestConsumeIfOriginator:
    """Atomic validate-and-consume for card clicks. Identity mismatch must NOT
    consume the entry (the real originator may still click later)."""

    def _registry_with_entry(self):
        registry = PendingCardRegistry()
        registry.register(
            callback_token="callback-1",
            request_id="clarification:call_1",
            source="ask_clarification",
            thread_id="thread-1",
            chat_id="chat-1",
            originator_open_id="ou_originator",
            options=("Alpha", "Beta"),
            option_ids=("option-1", "option-2"),
            card_message_id="om_card_1",
        )
        return registry

    def test_originator_consumes_and_gets_entry(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason is None
        assert entry is not None
        assert entry["card_message_id"] == "om_card_1"
        # replayed click: entry already gone
        entry2, reason2 = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry2 is None
        assert reason2 == "unknown"

    def test_non_originator_rejected_without_consuming(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("callback-1", "ou_someone_else", option_id="option-1", option_value="Alpha")
        assert entry is None
        assert reason == "not_originator"
        # the real originator can still click afterwards
        entry2, reason2 = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason2 is None
        assert entry2 is not None

    def test_unknown_request_id(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("clarification:nope", "ou_originator", option_id="option-1", option_value="Alpha")
        assert entry is None
        assert reason == "unknown"

    def test_expired_entry_is_unknown(self):
        registry = self._registry_with_entry()
        future = time.time() + 31 * 60
        entry, reason = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha", now=future)
        assert entry is None
        assert reason == "unknown"

    def test_unknown_option_value_rejected_without_consuming(self):
        registry = self._registry_with_entry()
        entry, reason = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="注入值")
        assert entry is None
        assert reason == "unknown"
        # the real button value still works afterwards
        entry2, reason2 = registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason2 is None and entry2 is not None


def _make_card_action_event(*, callback_token: str, option_value: str, option_id: str = "option-1", operator_open_id: str = "ou_originator"):
    """Build a minimal P2CardActionTrigger-shaped stand-in."""
    from unittest.mock import MagicMock

    event = MagicMock()
    event.event.action.value = {"callback_token": callback_token, "option_id": option_id, "option_value": option_value}
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
            callback_token="callback-1",
            request_id="clarification:call_1",
            source="ask_clarification",
            thread_id="thread-1",
            chat_id="chat-1",
            originator_open_id="ou_originator",
            options=("Alpha", "Beta"),
            option_ids=("option-1", "option-2"),
            card_message_id="om_card_1",
        )
        channel._main_loop = MagicMock()
        channel._main_loop.is_running.return_value = True
        channel._submit_threadsafe_coroutine = MagicMock(side_effect=lambda coroutine, *args, **kwargs: (coroutine.close(), True)[1])

        class _Toast:
            pass

        class _Resp:
            pass

        channel._CallBackToast = _Toast
        channel._P2CardActionTriggerResponse = _Resp
        return channel

    def test_non_originator_gets_refusal_toast_and_entry_survives(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(callback_token="callback-1", option_id="option-1", option_value="Alpha", operator_open_id="ou_other"))
        assert resp.toast is not None
        assert "发起人" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_not_called()
        # entry not consumed: originator can still click
        entry, reason = channel._card_registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
        assert reason is None and entry is not None

    def test_unknown_request_id_gets_stale_toast(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(callback_token="unknown", option_id="option-1", option_value="Alpha"))
        assert resp.toast is not None
        assert "失效" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_not_called()

    def test_dispatch_failure_returns_warning_toast(self):
        channel = self._channel()
        channel._submit_threadsafe_coroutine = MagicMock(side_effect=lambda coroutine, *args, **kwargs: (coroutine.close(), False)[1])
        resp = channel._on_card_action(_make_card_action_event(callback_token="callback-1", option_id="option-1", option_value="Alpha"))
        assert resp.toast is not None
        assert resp.toast.type == "warning"

    def test_originator_gets_ack_toast_and_dispatches_async_resolution(self):
        channel = self._channel()
        resp = channel._on_card_action(_make_card_action_event(callback_token="callback-1", option_id="option-1", option_value="Alpha"))
        assert resp.toast is not None
        assert "Alpha" in resp.toast.content
        channel._submit_threadsafe_coroutine.assert_called_once()
        # one-time: the entry is consumed by the click
        entry, reason = channel._card_registry.consume_if_originator("callback-1", "ou_originator", option_id="option-1", option_value="Alpha")
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
            "source": "ask_clarification",
            "thread_id": "thread-1",
            "chat_id": "chat-1",
            "originator_open_id": "ou_originator",
            "options": ("Alpha", "Beta"),
            "option_ids": ("option-1", "option-2"),
            "card_message_id": "om_card_1",
            "topic_id": "om_topic_1",
            "connection_id": "conn-1",
            "owner_user_id": "deer-user-1",
        }
        await channel._resolve_card_click(entry, option_id="option-1", option_value="Alpha", operator_open_id="ou_originator")

        # terminal card: no buttons, shows the choice
        assert channel._update_card.await_count == 1
        terminal_text = channel._update_card.await_args.args[1]
        assert "Alpha" in terminal_text

        # synthetic inbound: hidden human-input response routed at the card message,
        # carrying the routing identity the manager keys on (topic + connection).
        assert len(published) == 1
        inbound = published[0]
        assert inbound.chat_id == "chat-1"
        assert inbound.user_id == "ou_originator"
        assert inbound.thread_ts == "om_card_1"
        assert inbound.topic_id == "om_topic_1"
        assert inbound.connection_id == "conn-1"
        assert inbound.owner_user_id == "deer-user-1"
        response = inbound.metadata[HUMAN_INPUT_RESPONSE_METADATA_KEY]
        assert response["kind"] == "human_input_response"
        assert response["response_kind"] == "option"
        assert response["request_id"] == "clarification:call_1"
        assert response["value"] == "Alpha"
        assert inbound.metadata.get("hide_from_ui") is True

    @pytest.mark.asyncio
    async def test_dropped_inbound_leaves_card_unresolved(self):
        """If the inbound cannot be published, the card must not flip to a false resolved state."""
        from unittest.mock import AsyncMock

        from app.channels.feishu import FeishuChannel
        from app.channels.message_bus import MessageBus

        channel = FeishuChannel(MessageBus(), {"app_id": "t", "app_secret": "t", "card_interaction_enabled": True})
        channel._update_card = AsyncMock()
        channel._publish_inbound_or_drop = AsyncMock(return_value=False)

        entry = {
            "request_id": "clarification:call_1",
            "source": "ask_clarification",
            "thread_id": "thread-1",
            "chat_id": "chat-1",
            "originator_open_id": "ou_originator",
            "options": ("Alpha",),
            "card_message_id": "om_card_1",
        }
        await channel._resolve_card_click(entry, option_id="option-1", option_value="Alpha", operator_open_id="ou_originator")

        channel._update_card.assert_not_awaited()


class TestCardClickEndToEndRouting:
    """Pin the contract the reviewer flagged: the synthetic inbound must carry
    the routing identity the manager's thread resolution keys on, so a card
    click resumes the clarified thread instead of opening a new one."""

    def test_card_answer_resumes_existing_thread(self, tmp_path, monkeypatch):
        from app.channels.manager import ChannelManager
        from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channel-connections.db'}", sqlite_dir=str(tmp_path))
            repo = ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("test-channel-key"))
            conn = await repo.upsert_connection(
                owner_user_id="deer-user-1",
                provider="feishu",
                external_account_id="ou_originator",
                workspace_id="chat-1",
            )
            # What the channel persisted when the button card was delivered:
            # the card's topic maps to the clarified thread.
            await repo.set_thread_id(
                connection_id=conn["id"],
                owner_user_id="deer-user-1",
                provider="feishu",
                external_conversation_id="chat-1",
                thread_id="thread-existing",
                external_topic_id="om_topic_1",
            )

            bus = MessageBus()
            store = JsonChannelStore(path=tmp_path / "legacy-store.json")
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo)
            mock_client = MagicMock()
            mock_client.threads.create = AsyncMock(return_value={"thread_id": "thread-existing"})
            mock_client.threads.update = AsyncMock(return_value={"thread_id": "thread-existing"})
            mock_client.threads.get = AsyncMock(return_value={"thread_id": "thread-existing"})
            mock_client.runs.wait = AsyncMock(return_value={"messages": [{"type": "human", "content": "Alpha"}, {"type": "ai", "content": "resumed"}]})

            # Feishu is a streaming channel: the run goes through runs.stream,
            # whose first positional argument is the thread id.
            class _Part:
                def __init__(self, event, data):
                    self.event = event
                    self.data = data

            async def _stream(*args, **kwargs):
                yield _Part("values", {"messages": [{"type": "human", "content": "Alpha"}, {"type": "ai", "content": "resumed"}], "artifacts": []})

            mock_client.runs.stream = MagicMock(side_effect=lambda *args, **kwargs: _stream(*args, **kwargs))
            manager._client = mock_client

            # The synthetic inbound exactly as _resolve_card_click builds it.
            inbound = InboundMessage(
                channel_name="feishu",
                chat_id="chat-1",
                user_id="ou_originator",
                owner_user_id="deer-user-1",
                connection_id=conn["id"],
                text="Alpha",
                thread_ts="om_card_1",
                topic_id="om_topic_1",
                metadata={
                    "hide_from_ui": True,
                    HUMAN_INPUT_RESPONSE_METADATA_KEY: {
                        "version": 1,
                        "kind": "human_input_response",
                        "source": "ask_clarification",
                        "request_id": "clarification:call_1",
                        "response_kind": "option",
                        "option_id": "option-1",
                        "value": "Alpha",
                    },
                },
            )
            await manager._handle_chat(inbound)

            # The clarified thread is reused — nothing is created anew.
            mock_client.threads.create.assert_not_called()
            assert mock_client.runs.stream.call_count == 1
            assert mock_client.runs.stream.call_args.args[0] == "thread-existing"

            # And the posted human message carries the hidden human-input response.
            posted = mock_client.runs.stream.call_args.kwargs["input"]["messages"][0]
            assert posted["additional_kwargs"]["hide_from_ui"] is True
            assert posted["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY]["value"] == "Alpha"

        try:
            asyncio.run(go())
        finally:
            asyncio.run(close_engine())

    def test_card_answer_passes_bound_identity_admission(self, tmp_path, monkeypatch):
        """Connections-enabled deployments (require_bound_identity=True) re-read the
        binding with workspace_id; Feishu binds connections with workspace_id=chat_id,
        so the synthetic inbound must carry it or every click is rejected as unbound."""
        from app.channels.manager import ChannelManager
        from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)

        async def go():
            await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'cc.db'}", sqlite_dir=str(tmp_path))
            repo = ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("test-channel-key"))
            conn = await repo.upsert_connection(
                owner_user_id="deer-user-1",
                provider="feishu",
                external_account_id="ou_originator",
                workspace_id="chat-1",
            )
            await repo.set_thread_id(
                connection_id=conn["id"],
                owner_user_id="deer-user-1",
                provider="feishu",
                external_conversation_id="chat-1",
                thread_id="thread-existing",
                external_topic_id="om_topic_1",
            )

            bus = MessageBus()
            store = JsonChannelStore(path=tmp_path / "legacy-store.json")
            manager = ChannelManager(bus=bus, store=store, connection_repo=repo, require_bound_identity=True)
            mock_client = MagicMock()
            mock_client.threads.create = AsyncMock(return_value={"thread_id": "thread-existing"})
            mock_client.threads.update = AsyncMock(return_value={"thread_id": "thread-existing"})
            mock_client.threads.get = AsyncMock(return_value={"thread_id": "thread-existing"})

            class _Part:
                def __init__(self, event, data):
                    self.event = event
                    self.data = data

            async def _stream(*args, **kwargs):
                yield _Part("values", {"messages": [{"type": "human", "content": "Alpha"}, {"type": "ai", "content": "resumed"}], "artifacts": []})

            mock_client.runs.stream = MagicMock(side_effect=lambda *args, **kwargs: _stream(*args, **kwargs))
            manager._client = mock_client

            # Build the inbound through the channel's real click-resolution path,
            # then hand it to the manager — this is the production seam.
            from app.channels.feishu import FeishuChannel

            channel = FeishuChannel(MessageBus(), {"app_id": "t", "app_secret": "t", "card_interaction_enabled": True})
            channel._update_card = AsyncMock()
            produced = []

            async def capture(msg):
                produced.append(msg)
                return True

            channel._publish_inbound_or_drop = capture
            entry = {
                "request_id": "clarification:call_1",
                "source": "ask_clarification",
                "thread_id": "thread-existing",
                "chat_id": "chat-1",
                "originator_open_id": "ou_originator",
                "options": ("Alpha", "Beta"),
                "option_ids": ("option-1", "option-2"),
                "card_message_id": "om_card_1",
                "topic_id": "om_topic_1",
                "connection_id": conn["id"],
                "owner_user_id": "deer-user-1",
            }
            await channel._resolve_card_click(entry, option_id="option-1", option_value="Alpha", operator_open_id="ou_originator")
            assert len(produced) == 1

            await manager._handle_chat(produced[0])

            mock_client.threads.create.assert_not_called()
            assert mock_client.runs.stream.call_count == 1
            assert mock_client.runs.stream.call_args.args[0] == "thread-existing"

        try:
            asyncio.run(go())
        finally:
            asyncio.run(close_engine())
