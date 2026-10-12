"""Feishu card delivery and continuation through the real adapter/SDK seams."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.channels.feishu import FeishuChannel, _ParsedMessage, _RoutingAttempt
from app.channels.message_bus import HUMAN_INPUT_REQUEST_METADATA_KEY, HUMAN_INPUT_RESPONSE_METADATA_KEY, PENDING_CLARIFICATION_METADATA_KEY, InboundMessage, InboundMessageType, MessageBus, OutboundMessage


def clarification_payload(request_id: str = "clarification:call-1") -> dict:
    return {
        "version": 1,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": request_id,
        "question": "Pick one",
        "input_mode": "choice_with_other",
        "options": [{"id": "alpha", "label": "Alpha", "value": "Alpha"}, {"id": "beta", "label": "Beta", "value": "Beta"}],
    }


def clarification_outbound(*, request_id: str = "clarification:call-1", topic_id: str | None = "topic-1", thread_id: str = "thread-1", source_id: str = "source-1") -> OutboundMessage:
    return OutboundMessage(
        channel_name="feishu",
        chat_id="chat-1",
        thread_id=thread_id,
        text="Pick one",
        is_final=True,
        thread_ts=source_id,
        metadata={"user_id": "ou-originator", "topic_id": topic_id, PENDING_CLARIFICATION_METADATA_KEY: True, HUMAN_INPUT_REQUEST_METADATA_KEY: clarification_payload(request_id)},
    )


@pytest.fixture
def card_channel(tmp_path):
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, PatchMessageRequest, PatchMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody

    from app.channels.store import JsonChannelStore

    channel = FeishuChannel(MessageBus(), {"app_id": "offline-test", "app_secret": "offline-test", "card_interaction_enabled": True})
    channel.config["channel_store"] = JsonChannelStore(path=tmp_path / "cards.json")
    channel._ReplyMessageRequest = ReplyMessageRequest
    channel._ReplyMessageRequestBody = ReplyMessageRequestBody
    channel._PatchMessageRequest = PatchMessageRequest
    channel._PatchMessageRequestBody = PatchMessageRequestBody
    channel._CreateMessageRequest = CreateMessageRequest
    channel._CreateMessageRequestBody = CreateMessageRequestBody
    channel._api_client = MagicMock()
    channel._api_client.im.v1.message.reply.side_effect = lambda request: SimpleNamespace(success=lambda: True, data=SimpleNamespace(message_id=f"card-{request.message_id}"))
    channel._api_client.im.v1.message.patch.return_value = SimpleNamespace(success=lambda: True)
    channel._api_client.im.v1.message.create.return_value = SimpleNamespace(success=lambda: True)
    channel._CallBackToast = SimpleNamespace
    channel._P2CardActionTriggerResponse = SimpleNamespace
    return channel


def sent_button(channel, index: int = 0) -> dict:
    for call in reversed(channel._api_client.im.v1.message.mock_calls):
        if call[0] not in {"reply", "patch"}:
            continue
        card = json.loads(call.args[0].request_body.content)
        for element in card["elements"]:
            if element["tag"] == "action":
                return element["actions"][index]["value"]
    raise AssertionError("No button card was delivered")


async def click_button(channel, value: dict):
    channel._main_loop = asyncio.get_running_loop()
    event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=value), operator=SimpleNamespace(open_id="ou-originator")))
    response = channel._on_card_action(event)
    assert response.toast.type == "success"
    inbound = await asyncio.wait_for(channel.bus.get_inbound(), timeout=2)
    channel.bus.inbound_task_done()
    return inbound


@pytest.mark.asyncio
@pytest.mark.parametrize("running_card", ["absent", "present", "patch_rejected"])
@pytest.mark.parametrize(
    ("context", "expected_content"),
    [(None, "Pick one"), ("这将**永久删除**生产表中的数据。", "这将**永久删除**生产表中的数据。\n\nPick one")],
)
async def test_button_delivery_uses_real_sdk_requests(card_channel, running_card, context, expected_content):
    channel = card_channel
    if running_card != "absent":
        channel._running_card_ids["source-1"] = "running-card"
    if running_card == "patch_rejected":
        channel._api_client.im.v1.message.patch.return_value = SimpleNamespace(success=lambda: False, code=230099, msg="offline rejection", get_log_id=lambda: "offline")

    message = clarification_outbound()
    if context is not None:
        message.metadata[HUMAN_INPUT_REQUEST_METADATA_KEY]["context"] = context
        message.text = expected_content
    await channel.send(message, _max_retries=1)

    if running_card == "present":
        sdk_request = channel._api_client.im.v1.message.patch.call_args.args[0]
        assert sdk_request.message_id == "running-card"
    else:
        sdk_request = channel._api_client.im.v1.message.reply.call_args.args[0]
        assert sdk_request.message_id == "source-1"
        assert sdk_request.request_body.msg_type == "interactive"
    card = json.loads(sdk_request.request_body.content)
    assert card["config"]["update_multi"] is True
    markdown = next(element for element in card["elements"] if element["tag"] == "markdown")
    assert markdown["content"] == expected_content
    actions = next(element for element in card["elements"] if element["tag"] == "action")["actions"]
    assert [action["value"]["option_id"] for action in actions] == ["alpha", "beta"]
    assert [action["text"]["content"] for action in actions] == ["Alpha", "Beta"]


@pytest.mark.asyncio
async def test_plain_reply_keeps_markdown_wrapper(card_channel):
    message = clarification_outbound()
    message.metadata.pop(HUMAN_INPUT_REQUEST_METADATA_KEY)
    await card_channel.send(message, _max_retries=1)
    sdk_request = card_channel._api_client.im.v1.message.reply.call_args.args[0]
    card = json.loads(sdk_request.request_body.content)
    assert card["elements"] == [{"tag": "markdown", "content": "Pick one"}]


@pytest.mark.asyncio
async def test_button_answer_is_persisted_as_latest_human_input(card_channel):
    from langchain_core.messages import HumanMessage

    from app.channels.manager import _human_input_message_with_channel_response
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    await card_channel.send(clarification_outbound(), _max_retries=1)
    try:
        inbound = await click_button(card_channel, sent_button(card_channel))
        posted = _human_input_message_with_channel_response(inbound.text, metadata=inbound.metadata)
        hidden = HumanMessage(content=posted["content"], additional_kwargs=posted["additional_kwargs"])
        store = MemoryRunEventStore()
        journal = RunJournal("run-1", "thread-1", store)
        try:
            journal.on_chat_model_start({}, [[HumanMessage(content="Original question"), hidden]], run_id=uuid4(), tags=["lead_agent"])
            await journal.flush()
            events = await store.list_events("thread-1", "run-1")
            human_events = [event for event in events if event["event_type"] == "llm.human.input"]
            assert len(human_events) == 1
            assert human_events[0]["content"]["content"] == "Alpha"
            assert inbound.metadata[HUMAN_INPUT_RESPONSE_METADATA_KEY]["source"] == "ask_clarification"
        finally:
            await journal.close(flush=True)
    finally:
        await card_channel._close_and_drain_threadsafe_futures()


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_identity", [False, True])
@pytest.mark.parametrize("topic_id", [None, "topic-1"])
@pytest.mark.parametrize("reset_conversation", [False, True])
async def test_consecutive_card_answers_resume_the_same_thread(card_channel, tmp_path, monkeypatch, bound_identity, topic_id, reset_conversation):
    from app.channels.manager import ChannelManager
    from app.channels.store import JsonChannelStore
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    store = JsonChannelStore(path=tmp_path / "routing.json")
    card_channel.config["channel_store"] = store
    message = clarification_outbound(topic_id=topic_id)
    repo = None
    try:
        if bound_identity:
            await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'connections.db'}", sqlite_dir=str(tmp_path))
            repo = ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("offline-key"))
            connection = await repo.upsert_connection(owner_user_id="owner-1", provider="feishu", external_account_id="ou-originator", workspace_id="chat-1")
            message.connection_id = connection["id"]
            message.owner_user_id = "owner-1"
            card_channel._connection_repo = repo
            await repo.set_thread_id(connection_id=connection["id"], owner_user_id="owner-1", provider="feishu", external_conversation_id="chat-1", thread_id="thread-1", external_topic_id=topic_id)
        else:
            await store.set_thread_id("feishu", "chat-1", "thread-1", topic_id=topic_id, user_id="ou-originator")

        manager = ChannelManager(bus=card_channel.bus, store=store, connection_repo=repo, require_bound_identity=bound_identity)
        client = MagicMock()
        client.threads.create = AsyncMock(return_value={"thread_id": "unexpected-new-thread"})
        client.threads.update = AsyncMock(return_value={"thread_id": "thread-1"})
        client.threads.get = AsyncMock(return_value={"thread_id": "thread-1"})

        async def stream(*args, **kwargs):
            messages = [{"type": "human", "content": "Alpha"}]
            if client.runs.stream.call_count == 1:
                messages.append({"type": "tool", "name": "ask_clarification", "content": "Pick again", "artifact": {"human_input": clarification_payload("clarification:call-2")}})
            else:
                messages.append({"type": "ai", "content": "Done"})
            yield SimpleNamespace(event="values", data={"messages": messages, "artifacts": []})

        client.runs.stream = MagicMock(side_effect=stream)
        manager._client = client
        final_messages = []

        async def deliver(message):
            if message.is_final:
                final_messages.append(message)
            await card_channel._on_outbound(message)

        card_channel.bus.subscribe_outbound(deliver)
        await card_channel.send(message, _max_retries=1)
        button = sent_button(card_channel)
        if reset_conversation:
            command = InboundMessage(
                channel_name="feishu",
                chat_id="chat-1",
                user_id="ou-originator",
                text="/new",
                msg_type=InboundMessageType.COMMAND,
                topic_id=topic_id,
                connection_id=message.connection_id,
                owner_user_id=message.owner_user_id,
                workspace_id="chat-1",
                metadata={"user_id": "ou-originator", "topic_id": topic_id},
            )
            await manager._handle_command(command)
        first = await click_button(card_channel, button)
        await manager._handle_chat(first)
        assert final_messages[-1].metadata[PENDING_CLARIFICATION_METADATA_KEY] is True
        second = await click_button(card_channel, sent_button(card_channel))
        await manager._handle_chat(second)

        assert client.threads.create.call_count == int(reset_conversation)
        assert [call.args[0] for call in client.runs.stream.call_args_list] == ["thread-1", "thread-1"]
        if reset_conversation:
            assert await manager._lookup_thread_id(command) == "unexpected-new-thread"
        for inbound in (first, second):
            assert inbound.topic_id == inbound.metadata["topic_id"]
            if bound_identity:
                assert inbound.workspace_id == "chat-1"
                assert inbound.connection_id == connection["id"]
                assert inbound.owner_user_id == "owner-1"
        for call in client.runs.stream.call_args_list:
            posted = call.kwargs["input"]["messages"][0]
            assert posted["additional_kwargs"]["hide_from_ui"] is True
            assert posted["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY]["source"] == "ask_clarification"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()
        if bound_identity:
            await close_engine()


@pytest.mark.asyncio
async def test_reused_request_ids_do_not_cross_route_cards(card_channel):
    first_message = clarification_outbound()
    await card_channel.send(first_message, _max_retries=1)
    first_button = sent_button(card_channel)
    second_message = clarification_outbound(thread_id="thread-2", topic_id="topic-2", source_id="source-2")
    await card_channel.send(second_message, _max_retries=1)
    second_button = sent_button(card_channel)
    try:
        first = await click_button(card_channel, first_button)
        second = await click_button(card_channel, second_button)
        assert first.topic_id == "feishu-card:thread-1"
        assert first.thread_ts == "card-source-1"
        assert second.topic_id == "feishu-card:thread-2"
        assert second.thread_ts == "card-source-2"
        assert first_button["callback_token"] != second_button["callback_token"]
        for inbound in (first, second):
            assert inbound.metadata[HUMAN_INPUT_RESPONSE_METADATA_KEY]["request_id"] == first_message.metadata[HUMAN_INPUT_REQUEST_METADATA_KEY]["request_id"]
    finally:
        await card_channel._close_and_drain_threadsafe_futures()


def group_message(message_id: str) -> _ParsedMessage:
    return _ParsedMessage(chat_id="chat-1", msg_id=message_id, sender_id="ou-originator", root_id=None, parent_id=None, feishu_thread_id=None, chat_type="group", text="Another question", files=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("with_store", [False, True])
@pytest.mark.parametrize("other_pending_card", [False, True])
async def test_answered_card_clears_only_its_text_continuation(card_channel, tmp_path, with_store, other_pending_card):
    from app.channels.store import JsonChannelStore

    if with_store:
        card_channel.config["channel_store"] = JsonChannelStore(path=tmp_path / "hints.json")

    async def route(message_id):
        parsed = group_message(message_id)
        return await card_channel._resolve_routing(_RoutingAttempt(parsed)) if with_store else card_channel._route_without_store(parsed)

    if other_pending_card:
        await card_channel.send(clarification_outbound(request_id="clarification:other", thread_id="other-thread", topic_id="other-topic", source_id="other-source"), _max_retries=1)
    await card_channel.send(clarification_outbound(), _max_retries=1)
    try:
        await click_button(card_channel, sent_button(card_channel))
        if other_pending_card:
            remaining = await route("reply-to-other-card")
            assert remaining.topic_id == "feishu-card:other-thread"
            assert remaining.from_pending is True
        independent = await route("independent-question")
        assert independent.topic_id == "independent-question"
        assert independent.from_pending is False
    finally:
        await card_channel._close_and_drain_threadsafe_futures()


@pytest.mark.asyncio
async def test_forged_option_id_does_not_consume_card(card_channel):
    await card_channel.send(clarification_outbound(), _max_retries=1)
    button = sent_button(card_channel)
    forged = dict(button, option_id="beta")
    card_channel._main_loop = asyncio.get_running_loop()
    event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=forged), operator=SimpleNamespace(open_id="ou-originator")))
    try:
        response = card_channel._on_card_action(event)
        assert response.toast.type == "warning"
        with pytest.raises(asyncio.QueueEmpty):
            card_channel.bus.get_inbound_nowait()
        accepted = await click_button(card_channel, button)
        assert accepted.metadata[HUMAN_INPUT_RESPONSE_METADATA_KEY]["option_id"] == "alpha"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_state", ["full", "closed"])
async def test_rejected_answer_keeps_text_fallback_and_card_unresolved(card_channel, queue_state):
    from app.channels.message_bus import InboundMessage

    card_channel.bus = MessageBus(inbound_queue_maxsize=1)
    await card_channel.send(clarification_outbound(), _max_retries=1)
    if queue_state == "closed":
        card_channel.bus.close_inbound()
    else:
        await card_channel.bus.publish_inbound(InboundMessage(channel_name="feishu", chat_id="busy", user_id="busy", text="Already admitted"))
    button = sent_button(card_channel)
    entry, reason = card_channel._card_registry.consume_if_originator(button["callback_token"], "ou-originator", option_id=button["option_id"], option_value=button["option_value"])
    assert reason is None and entry is not None
    await card_channel._resolve_card_click(entry, option_id=button["option_id"], option_value=button["option_value"], operator_open_id="ou-originator")
    card_channel._api_client.im.v1.message.patch.assert_not_called()
    text_reply = card_channel._route_without_store(group_message("typed-answer"))
    assert text_reply.topic_id == "feishu-card:thread-1"
    assert text_reply.from_pending is True
    if queue_state == "full":
        assert card_channel.bus.get_inbound_nowait().text == "Already admitted"
        card_channel.bus.inbound_task_done()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_reply", [False, True])
async def test_accepted_text_answer_retires_its_button_card(card_channel, explicit_reply):
    await card_channel.send(clarification_outbound(), _max_retries=1)
    button = sent_button(card_channel)
    parsed = group_message("typed-answer")
    parsed.text = "Beta"
    if explicit_reply:
        parsed.root_id = "source-1"
        parsed.parent_id = "card-source-1"
    routing = await card_channel._resolve_routing(_RoutingAttempt(parsed))
    card_channel._main_loop = asyncio.get_running_loop()
    card_channel._dispatch_inbound(parsed, routing)
    try:
        inbound = await asyncio.wait_for(card_channel.bus.get_inbound(), timeout=2)
        card_channel.bus.inbound_task_done()
        assert inbound.text == "Beta"
        assert inbound.topic_id == "feishu-card:thread-1"
        event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=button), operator=SimpleNamespace(open_id="ou-originator")))
        assert card_channel._on_card_action(event).toast.type == "warning"
        with pytest.raises(asyncio.QueueEmpty):
            card_channel.bus.get_inbound_nowait()
    finally:
        await card_channel._close_and_drain_threadsafe_futures()
        await asyncio.gather(*card_channel._running_card_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_explicit_text_answer_targets_the_card_before_its_shared_topic(card_channel):
    await card_channel.send(clarification_outbound(source_id="source-1"), _max_retries=1)
    first_button = sent_button(card_channel)
    await card_channel.send(clarification_outbound(thread_id="thread-2", source_id="source-2"), _max_retries=1)
    second_button = sent_button(card_channel)
    parsed = group_message("typed-second-answer")
    parsed.text = "Beta"
    parsed.root_id = "topic-1"
    parsed.parent_id = "card-source-2"
    routing = await card_channel._resolve_routing(_RoutingAttempt(parsed))
    card_channel._main_loop = asyncio.get_running_loop()
    card_channel._dispatch_inbound(parsed, routing)
    try:
        inbound = await asyncio.wait_for(card_channel.bus.get_inbound(), timeout=2)
        card_channel.bus.inbound_task_done()
        assert inbound.topic_id == "feishu-card:thread-2"
        event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=second_button), operator=SimpleNamespace(open_id="ou-originator")))
        assert card_channel._on_card_action(event).toast.type == "warning"
        assert (await click_button(card_channel, first_button)).topic_id == "feishu-card:thread-1"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()
        await asyncio.gather(*card_channel._running_card_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_explicit_text_answer_keeps_the_new_conversation_route(card_channel):
    from app.channels.manager import ChannelManager

    store = card_channel.config["channel_store"]
    await store.set_thread_id("feishu", "chat-1", "thread-1", topic_id="topic-1", user_id="ou-originator")
    await card_channel.send(clarification_outbound(), _max_retries=1)
    manager = ChannelManager(bus=card_channel.bus, store=store)
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": "thread-after-new"})
    client.threads.get = AsyncMock(return_value={"thread_id": "thread-1", "metadata": {}})
    client.threads.update = AsyncMock(return_value={"thread_id": "thread-1"})

    async def stream(*args, **kwargs):
        yield SimpleNamespace(event="values", data={"messages": [{"type": "human", "content": "Beta"}, {"type": "ai", "content": "Done"}], "artifacts": []})

    client.runs.stream = MagicMock(side_effect=stream)
    manager._client = client
    card_channel.bus.subscribe_outbound(card_channel._on_outbound)
    command = InboundMessage(
        channel_name="feishu",
        chat_id="chat-1",
        user_id="ou-originator",
        text="/new",
        msg_type=InboundMessageType.COMMAND,
        thread_ts="source-new",
        topic_id="topic-1",
        metadata={"user_id": "ou-originator", "message_id": "source-new", "topic_id": "topic-1"},
    )
    await manager._handle_command(command)
    assert await manager._lookup_thread_id(command) == "thread-after-new"
    parsed = group_message("typed-old-answer")
    parsed.text = "Beta"
    parsed.root_id = "topic-1"
    parsed.parent_id = "card-source-1"
    routing = await card_channel._resolve_routing(_RoutingAttempt(parsed))
    card_channel._main_loop = asyncio.get_running_loop()
    card_channel._dispatch_inbound(parsed, routing)
    try:
        inbound = await asyncio.wait_for(card_channel.bus.get_inbound(), timeout=2)
        card_channel.bus.inbound_task_done()
        await manager._handle_chat(inbound)
        assert client.runs.stream.call_args.args[0] == "thread-1"
        assert await manager._lookup_thread_id(command) == "thread-after-new"
        next_message = group_message("new-task")
        next_message.root_id = "topic-1"
        card_channel._dispatch_inbound(next_message, await card_channel._resolve_routing(_RoutingAttempt(next_message)))
        next_inbound = await asyncio.wait_for(card_channel.bus.get_inbound(), timeout=2)
        card_channel.bus.inbound_task_done()
        await manager._handle_chat(next_inbound)
        assert client.runs.stream.call_args.args[0] == "thread-after-new"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()
        await asyncio.gather(*card_channel._running_card_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_identity", [False, True])
@pytest.mark.parametrize("reset_conversation", [False, True])
@pytest.mark.parametrize("topic_id", [None, "source-1"])
async def test_ordinary_text_uses_current_conversation(card_channel, tmp_path, monkeypatch, bound_identity, reset_conversation, topic_id):
    from app.channels.manager import ChannelManager
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    store = card_channel.config["channel_store"]
    message = clarification_outbound(topic_id=topic_id)
    repo = None
    try:
        if bound_identity:
            await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'connections.db'}", sqlite_dir=str(tmp_path))
            repo = ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("offline-key"))
            connection = await repo.upsert_connection(owner_user_id="owner-1", provider="feishu", external_account_id="ou-originator", workspace_id="chat-1")
            message.connection_id = connection["id"]
            message.owner_user_id = "owner-1"
            card_channel._connection_repo = repo
            await repo.set_thread_id(connection_id=connection["id"], owner_user_id="owner-1", provider="feishu", external_conversation_id="chat-1", thread_id="thread-1", external_topic_id=topic_id)
        else:
            await store.set_thread_id("feishu", "chat-1", "thread-1", topic_id=topic_id, user_id="ou-originator")
        manager = ChannelManager(bus=card_channel.bus, store=store, connection_repo=repo, require_bound_identity=bound_identity)
        client = MagicMock()
        client.threads.create = AsyncMock(return_value={"thread_id": "thread-after-new"})
        client.threads.get = AsyncMock(return_value={"thread_id": "thread-1", "metadata": {}})
        client.threads.update = AsyncMock(return_value={"thread_id": "thread-1"})

        async def stream(*args, **kwargs):
            yield SimpleNamespace(event="values", data={"messages": [{"type": "human", "content": "Beta"}, {"type": "ai", "content": "Done"}], "artifacts": []})

        client.runs.stream = MagicMock(side_effect=stream)
        manager._client = client
        card_channel.bus.subscribe_outbound(card_channel._on_outbound)
        await card_channel.send(message, _max_retries=1)
        old_button = sent_button(card_channel)
        command = InboundMessage(
            channel_name="feishu",
            chat_id="chat-1",
            user_id="ou-originator",
            text="/new",
            msg_type=InboundMessageType.COMMAND,
            topic_id=topic_id,
            connection_id=message.connection_id,
            owner_user_id=message.owner_user_id,
            workspace_id="chat-1",
            metadata={"user_id": "ou-originator", "topic_id": topic_id},
        )
        if reset_conversation:
            await manager._handle_command(command)
        parsed = group_message("ordinary-answer")
        parsed.chat_type = "group" if topic_id else "p2p"
        parsed.root_id = topic_id
        parsed.parent_id = "source-new" if topic_id and reset_conversation else None
        parsed.text = "Beta"
        card_channel._main_loop = asyncio.get_running_loop()
        card_channel._dispatch_inbound(parsed, await card_channel._resolve_routing(_RoutingAttempt(parsed)))
        inbound = await asyncio.wait_for(card_channel.bus.get_inbound(), timeout=2)
        card_channel.bus.inbound_task_done()
        await manager._handle_chat(inbound)
        expected_thread = "thread-after-new" if reset_conversation else "thread-1"
        assert client.runs.stream.call_args.args[0] == expected_thread
        assert await manager._lookup_thread_id(command) == expected_thread
        if reset_conversation:
            old_answer = await click_button(card_channel, old_button)
            await manager._handle_chat(old_answer)
            assert client.runs.stream.call_args.args[0] == "thread-1"
            assert await manager._lookup_thread_id(command) == "thread-after-new"
        else:
            event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=old_button), operator=SimpleNamespace(open_id="ou-originator")))
            assert card_channel._on_card_action(event).toast.type == "warning"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()
        await asyncio.gather(*card_channel._running_card_tasks.values(), return_exceptions=True)
        if bound_identity:
            await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["callback_token", "option_id", "option_value", "operator"])
async def test_malformed_callback_keeps_the_real_button_usable(card_channel, field):
    await card_channel.send(clarification_outbound(), _max_retries=1)
    button = sent_button(card_channel)
    invalid = dict(button)
    operator = "ou-originator"
    if field == "operator":
        operator = []
    else:
        invalid[field] = []
    event = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value=invalid), operator=SimpleNamespace(open_id=operator)))
    try:
        assert card_channel._on_card_action(event).toast.type == "warning"
        assert (await click_button(card_channel, button)).text == "Alpha"
    finally:
        await card_channel._close_and_drain_threadsafe_futures()


@pytest.mark.asyncio
async def test_failed_thread_alias_binding_falls_back_to_text(card_channel, tmp_path):
    from app.channels.store import JsonChannelStore

    class FailingAliasStore(JsonChannelStore):
        async def set_thread_id(self, *args, **kwargs):
            if (kwargs.get("topic_id") or "").startswith("feishu-card:"):
                raise RuntimeError("offline database failure")
            return await super().set_thread_id(*args, **kwargs)

    card_channel.config["channel_store"] = FailingAliasStore(path=tmp_path / "failing.json")
    await card_channel.send(clarification_outbound(), _max_retries=1)
    request = card_channel._api_client.im.v1.message.reply.call_args.args[0]
    assert json.loads(request.request_body.content)["elements"] == [{"tag": "markdown", "content": "Pick one"}]


@pytest.mark.asyncio
async def test_visible_buttons_work_while_auxiliary_mapping_is_slow(card_channel, tmp_path):
    from app.channels.store import JsonChannelStore

    waiting = asyncio.Event()
    release = asyncio.Event()

    class SlowMessageAliasStore(JsonChannelStore):
        async def set_thread_id(self, *args, **kwargs):
            if kwargs.get("topic_id") == "source-1":
                waiting.set()
                await release.wait()
            return await super().set_thread_id(*args, **kwargs)

    card_channel.config["channel_store"] = SlowMessageAliasStore(path=tmp_path / "slow.json")
    delivery = asyncio.create_task(card_channel.send(clarification_outbound(), _max_retries=1))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=2)
        inbound = await click_button(card_channel, sent_button(card_channel))
        assert inbound.topic_id == "feishu-card:thread-1"
    finally:
        release.set()
        await delivery
        await card_channel._close_and_drain_threadsafe_futures()


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_state", ["full", "closed_reservation"])
async def test_rejected_text_answer_keeps_the_button_usable(card_channel, queue_state):
    from app.channels.feishu import _PENDING_CARD_METADATA_KEY
    from app.channels.message_bus import InboundQueueFullError

    card_channel.bus = MessageBus(inbound_queue_maxsize=1)
    await card_channel.send(clarification_outbound(), _max_retries=1)
    button = sent_button(card_channel)
    inbound = InboundMessage(channel_name="feishu", chat_id="chat-1", user_id="ou-originator", text="Beta", topic_id="feishu-card:thread-1", metadata={_PENDING_CARD_METADATA_KEY: "card-source-1"})
    reservation = None
    try:
        if queue_state == "full":
            await card_channel.bus.publish_inbound(InboundMessage(channel_name="feishu", chat_id="busy", user_id="busy", text="Already admitted"))
            with pytest.raises(InboundQueueFullError):
                await card_channel._prepare_inbound("typed-answer", inbound)
            card_channel.bus.get_inbound_nowait()
            card_channel.bus.inbound_task_done()
        else:
            reservation = card_channel.bus.reserve_inbound(inbound)
            card_channel.bus.close_inbound()
            await card_channel._prepare_inbound("typed-answer", inbound, reservation=reservation)
        entry, reason = card_channel._card_registry.consume_if_originator(button["callback_token"], "ou-originator", option_id=button["option_id"], option_value=button["option_value"])
        assert reason is None and entry is not None
        assert _PENDING_CARD_METADATA_KEY not in inbound.metadata
    finally:
        if reservation:
            reservation.release()
        await asyncio.gather(*card_channel._running_card_tasks.values(), return_exceptions=True)
