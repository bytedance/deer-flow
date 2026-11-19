"""Proactive Feishu delivery uses a bound identity and waits for the SDK ACK."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from app.channels.base import Channel, ChannelUnavailable
from app.channels.feishu import FeishuChannel
from app.channels.message_bus import MessageBus


@pytest.fixture
def channel():
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, GetChatRequest

    instance = FeishuChannel(MessageBus(), {})
    instance._running = True
    instance._thread = MagicMock()
    instance._thread.is_alive.return_value = True
    instance._CreateMessageRequest = CreateMessageRequest
    instance._CreateMessageRequestBody = CreateMessageRequestBody
    instance._GetChatRequest = GetChatRequest
    instance._api_client = MagicMock()
    instance._api_client.im.v1.message.create.return_value = SimpleNamespace(success=lambda: True)
    return instance


def _private_binding(**overrides):
    return {
        "owner_user_id": "owner-1",
        "provider": "feishu",
        "status": "connected",
        "external_account_id": "ou_bound_user",
        "workspace_id": "oc_private",
        "metadata": {"chat_id": "oc_private", "chat_type": "p2p"},
        **overrides,
    }


def _group_binding(**overrides):
    return _private_binding(id="group-binding", workspace_id="oc_group", metadata={"chat_id": "oc_group", "chat_type": "group"}, **overrides)


@pytest.mark.asyncio
async def test_base_group_notification_is_unsupported_and_never_falls_back(channel):
    channel.send_notification = AsyncMock()
    with pytest.raises(NotImplementedError):
        await Channel.send_group_notification_for_owner(channel, owner_user_id="owner-1", target="group-binding", text_markdown="Done")
    channel.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_group_notification_uses_selected_binding_and_group_chat(channel):
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(return_value=[_private_binding(), _group_binding()]))
    await channel.send_group_notification_for_owner(owner_user_id="owner-1", target="group-binding", text_markdown="Done")
    channel._connection_repo.list_connections.assert_awaited_once_with("owner-1")
    create = channel._api_client.im.v1.message.create
    create.assert_called_once()
    request = create.call_args.args[0]
    assert request.receive_id_type == "chat_id"
    assert request.request_body.receive_id == "oc_group"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "different-binding"},
        {"owner_user_id": "another-owner"},
        {"provider": "wecom"},
        {"status": "revoked"},
        {"workspace_id": "oc_other"},
        {"metadata": {"chat_id": "oc_group", "chat_type": "p2p"}},
        {"metadata": {"chat_id": "oc_group"}},
    ],
)
async def test_group_notification_refuses_invalid_binding_without_private_fallback(channel, overrides):
    binding = {**_group_binding(), **overrides}
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(return_value=[binding]))
    with pytest.raises(RuntimeError, match="no longer connected"):
        await channel.send_group_notification_for_owner(owner_user_id="owner-1", target="group-binding", text_markdown="Done")
    channel._api_client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
async def test_group_notification_binding_lookup_failure_parks(channel):
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(side_effect=OSError("private database detail")))
    with pytest.raises(ChannelUnavailable):
        await channel.send_group_notification_for_owner(owner_user_id="owner-1", target="group-binding", text_markdown="Done")
    channel._api_client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "rejected", "exception"])
async def test_group_binding_reads_name_offloop_without_blocking_binding_on_failure(channel, outcome):
    channel._connection_repo = SimpleNamespace(consume_oauth_state=AsyncMock(return_value={"owner_user_id": "owner-1"}), upsert_connection=AsyncMock())
    channel._reply_card = AsyncMock()
    loop_thread = threading.get_ident()
    worker_threads = []

    def get_name(request):
        worker_threads.append(threading.get_ident())
        assert request.chat_id == "oc_group"
        if outcome == "exception":
            raise OSError("private transport detail")
        return SimpleNamespace(success=lambda: outcome == "success", code=0 if outcome == "success" else 99991672, data=SimpleNamespace(name="Release team"))

    channel._api_client.im.v1.chat.get.side_effect = get_name
    assert await channel._bind_connection_from_connect_code(message_id="om_bind", chat_id="oc_group", user_id="ou_bound_user", code="connect-code", chat_type="group")
    binding = channel._connection_repo.upsert_connection.call_args.kwargs
    assert worker_threads and worker_threads != [loop_thread]
    assert binding.get("workspace_name") == ("Release team" if outcome == "success" else None)
    assert binding["metadata"]["chat_type"] == "group"
    assert binding["metadata"]["chat_id"] == "oc_group"


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type,expected", [("group", "Release team"), ("p2p", None)])
async def test_owner_chosen_group_name_is_consumed_only_for_group_binding(channel, chat_type, expected):
    channel._connection_repo = SimpleNamespace(consume_oauth_state=AsyncMock(return_value={"owner_user_id": "owner-1", "metadata": {"notification_group_name": "Release team"}}), upsert_connection=AsyncMock())
    channel._reply_card = AsyncMock()
    channel._get_group_name = AsyncMock()
    await channel._bind_connection_from_connect_code(message_id="om_bind", chat_id="oc_group", user_id="ou_bound_user", code="connect-code", chat_type=chat_type)
    assert channel._connection_repo.upsert_connection.await_args.kwargs["workspace_name"] == expected
    channel._get_group_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_owner_notification_preserves_existing_provider_send(channel):
    channel.send_notification = AsyncMock()

    await Channel.send_notification_for_owner(channel, owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    channel.send_notification.assert_awaited_once_with(target="ou_bound_user", text_markdown="Done")


@pytest.mark.asyncio
async def test_owner_notification_uses_only_its_bound_private_chat(channel):
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(return_value=[_private_binding(owner_user_id="another-owner"), _private_binding(metadata={"chat_id": "oc_private", "chat_type": "group"}), _private_binding()]))

    await channel.send_notification_for_owner(owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    channel._connection_repo.list_connections.assert_awaited_once_with("owner-1")
    request = channel._api_client.im.v1.message.create.call_args.args[0]
    assert request.receive_id_type == "chat_id"
    assert request.request_body.receive_id == "oc_private"
    assert json.loads(request.request_body.content)["elements"] == [{"tag": "markdown", "content": "Done"}]
    channel._api_client.im.v1.message.create.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"owner_user_id": "another-owner"},
        {"provider": "wecom"},
        {"status": "revoked"},
        {"external_account_id": "ou_someone_else"},
        {"workspace_id": "oc_different_chat"},
        {"metadata": {"chat_id": "oc_private", "chat_type": "group"}},
        {"metadata": {"chat_id": "oc_private"}},
        {"metadata": {"chat_id": "", "chat_type": "p2p"}},
    ],
)
async def test_owner_notification_never_promotes_unverified_chat_id(channel, overrides):
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(return_value=[_private_binding(**overrides), _private_binding(metadata={"chat_id": "oc_private", "chat_type": "group"})]))

    await channel.send_notification_for_owner(owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    request = channel._api_client.im.v1.message.create.call_args.args[0]
    assert request.receive_id_type == "open_id"
    assert request.request_body.receive_id == "ou_bound_user"


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [None, {"status": "revoked"}, {"owner_user_id": "another-owner"}, {"provider": "wecom"}, {"external_account_id": "ou_someone_else"}])
async def test_owner_notification_does_not_send_when_binding_is_no_longer_active(channel, overrides):
    rows = [] if overrides is None else [_private_binding(**overrides)]
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(return_value=rows))

    with pytest.raises(RuntimeError, match="no longer connected"):
        await channel.send_notification_for_owner(owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    channel._api_client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
async def test_owner_notification_without_connection_repo_keeps_open_id(channel):
    await channel.send_notification_for_owner(owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    request = channel._api_client.im.v1.message.create.call_args.args[0]
    assert request.receive_id_type == "open_id"
    assert request.request_body.receive_id == "ou_bound_user"


@pytest.mark.asyncio
async def test_owner_notification_parks_on_binding_lookup_error(channel):
    channel._connection_repo = SimpleNamespace(list_connections=AsyncMock(side_effect=OSError("private database detail")))

    with pytest.raises(ChannelUnavailable) as caught:
        await channel.send_notification_for_owner(owner_user_id="owner-1", target="ou_bound_user", text_markdown="Done")

    assert "private database detail" not in str(caught.value)
    channel._api_client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type", ["p2p", "group", None])
async def test_binding_records_chat_type_from_inbound_event(channel, chat_type):
    channel._connection_repo = SimpleNamespace(consume_oauth_state=AsyncMock(return_value={"owner_user_id": "owner-1"}), upsert_connection=AsyncMock())
    channel._reply_card = AsyncMock()

    assert await channel._bind_connection_from_connect_code(message_id="om_bind", chat_id="oc_bound", user_id="ou_bound_user", code="connect-code", chat_type=chat_type)

    binding = channel._connection_repo.upsert_connection.call_args.kwargs
    assert binding["owner_user_id"] == "owner-1"
    assert binding["external_account_id"] == "ou_bound_user"
    assert binding["workspace_id"] == "oc_bound"
    assert binding["metadata"] == {"chat_id": "oc_bound", "message_id": "om_bind", "chat_type": chat_type}


@pytest.mark.asyncio
async def test_bind_callback_passes_parsed_chat_type(channel):
    channel._connection_repo = MagicMock()
    channel._parse_message_event = MagicMock(return_value=SimpleNamespace(msg_id="om_bind", chat_id="oc_bound", sender_id="ou_bound_user", text="/connect connect-code", chat_type="p2p"))
    channel._main_loop = asyncio.get_running_loop()
    channel._bind_connection_from_connect_code = AsyncMock()
    pending = []

    def capture(coroutine, *_args, **_kwargs):
        pending.append(coroutine)
        return True

    channel._submit_threadsafe_coroutine = capture
    channel._on_message(object())
    assert len(pending) == 1
    await pending[0]

    channel._bind_connection_from_connect_code.assert_awaited_once_with(message_id="om_bind", chat_id="oc_bound", user_id="ou_bound_user", code="connect-code", chat_type="p2p")


@pytest.mark.asyncio
async def test_notification_uses_bound_open_id_and_static_markdown_card(channel):
    text = "**任务已完成**\n结果已准备好。"

    await channel.send_notification(target="ou_bound_user", text_markdown=text)

    create = channel._api_client.im.v1.message.create
    create.assert_called_once()
    request = create.call_args.args[0]
    assert request.receive_id_type == "open_id"
    assert request.request_body.receive_id == "ou_bound_user"
    assert request.request_body.msg_type == "interactive"
    assert json.loads(request.request_body.content)["elements"] == [{"tag": "markdown", "content": text}]
    channel._api_client.im.v1.message.reply.assert_not_called()
    channel._api_client.im.v1.message.patch.assert_not_called()
    assert channel._running_card_ids == {}
    assert channel._pending_clarifications == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["stopped", "missing_thread", "dead_thread", "missing_client"])
async def test_notification_without_live_channel_parks_without_sending(channel, unavailable):
    create = channel._api_client.im.v1.message.create
    if unavailable == "stopped":
        channel._running = False
    elif unavailable == "missing_thread":
        channel._thread = None
    elif unavailable == "dead_thread":
        channel._thread.is_alive.return_value = False
    else:
        channel._api_client = None

    with pytest.raises(ChannelUnavailable):
        await channel.send_notification(target="ou_bound_user", text_markdown="Done")

    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RequestsConnectionError, RequestsTimeout, ConnectionError, TimeoutError, OSError])
async def test_notification_transport_failures_park_without_local_retry(channel, error_type):
    create = channel._api_client.im.v1.message.create
    create.side_effect = error_type("private transport detail")

    with pytest.raises(ChannelUnavailable) as caught:
        await channel.send_notification(target="ou_bound_user", text_markdown="Done")

    create.assert_called_once()
    assert "private transport detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_notification_platform_rejection_remains_a_counted_failure(channel):
    create = channel._api_client.im.v1.message.create
    create.return_value = SimpleNamespace(success=lambda: False, code=230013, msg="private provider detail")

    with pytest.raises(RuntimeError, match="230013") as caught:
        await channel.send_notification(target="ou_bound_user", text_markdown="Done")

    assert not isinstance(caught.value, ChannelUnavailable)
    assert "private provider detail" not in str(caught.value)
    create.assert_called_once()


@pytest.mark.asyncio
async def test_notification_unexpected_sdk_error_is_not_disguised_as_transport(channel):
    error = ValueError("invalid request")
    channel._api_client.im.v1.message.create.side_effect = error

    with pytest.raises(ValueError) as caught:
        await channel.send_notification(target="ou_bound_user", text_markdown="Done")

    assert caught.value is error
    channel._api_client.im.v1.message.create.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_notification_sdk_send_runs_offloop_and_waits_for_ack(channel, cancel):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    worker_threads = []

    def send(request):
        worker_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise TimeoutError("test did not release send")
            return SimpleNamespace(success=lambda: True)
        finally:
            loop.call_soon_threadsafe(finished.set)

    channel._api_client.im.v1.message.create.side_effect = send
    task = asyncio.create_task(channel.send_notification(target="ou_bound_user", text_markdown="Done"))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert worker_threads != [loop_thread]
        assert not task.done()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        if worker_threads:
            await asyncio.wait_for(finished.wait(), timeout=2)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
