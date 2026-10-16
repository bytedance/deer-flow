"""Owner-bound iLink notifications require private context and a platform ACK."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from app.channels.base import ChannelUnavailable
from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel


def _binding(**overrides):
    return {"id": "binding-1", "owner_user_id": "owner-1", "provider": "wechat", "status": "connected", "external_account_id": "wx-user", "workspace_id": "wx-user", **overrides}


def _credentials(**context):
    return {"connection_id": "binding-1", "extra": {"wechat_notification_context": {"chat_id": "wx-user", "context_token": "private-context", "bot_token_sha256": hashlib.sha256(b"bot-token").hexdigest(), **context}}}


@pytest_asyncio.fixture
async def channel():
    ch = WechatChannel(MessageBus(), {"bot_token": "bot-token"})
    ch._running = True
    ch._connection_repo = SimpleNamespace(
        find_connection_by_external_identity=AsyncMock(return_value=_binding()),
        get_credentials=AsyncMock(return_value=_credentials()),
        store_connection_context=AsyncMock(return_value=True),
    )
    ch._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ret": 0})))
    try:
        yield ch
    finally:
        await ch.stop()


async def _notify(channel):
    await channel.send_notification_for_owner(owner_user_id="owner-1", target="wx-user", text_markdown="任务完成\n**报告已就绪**")


@pytest.mark.asyncio
async def test_notification_serializes_real_http_request_and_waits_for_ack(channel):
    received = asyncio.Event()
    release = asyncio.Event()
    requests = []
    handlers = set()

    async def handle(reader, writer):
        handlers.add(asyncio.current_task())
        try:
            request_line = await reader.readline()
            headers = {}
            while (line := await reader.readline()) not in (b"\r\n", b""):
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            body = await reader.readexactly(int(headers["content-length"]))
            requests.append((request_line, headers, json.loads(body)))
            received.set()
            await release.wait()
            body = b'{"ret":0}'
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    channel._base_url = f"http://127.0.0.1:{port}"
    await channel._client.aclose()
    channel._client = httpx.AsyncClient(trust_env=False)
    sending = asyncio.create_task(_notify(channel))
    try:
        await asyncio.wait_for(received.wait(), 3)
        assert not sending.done()
        release.set()
        await asyncio.wait_for(sending, 3)
        assert len(requests) == 1
        request_line, headers, payload = requests[0]
        assert request_line == b"POST /ilink/bot/sendmessage HTTP/1.1\r\n"
        assert headers["authorization"] == "Bearer bot-token"
        assert headers["authorizationtype"] == "ilink_bot_token"
        assert payload["msg"]["to_user_id"] == "wx-user"
        assert payload["msg"]["context_token"] == "private-context"
        assert payload["msg"]["message_state"] == 2
        assert payload["msg"]["item_list"] == [{"type": 1, "text_item": {"text": "任务完成\n**报告已就绪**"}}]
    finally:
        release.set()
        if not sending.done():
            sending.cancel()
        await asyncio.gather(sending, return_exceptions=True)
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*handlers)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"owner_user_id": "other"}, {"status": "revoked"}, {"provider": "feishu"}, {"external_account_id": "other"}, {"workspace_id": "group"}])
async def test_notification_rejects_unmatched_binding(channel, overrides):
    channel._connection_repo.find_connection_by_external_identity.return_value = _binding(**overrides)
    channel._request_json = AsyncMock()
    with pytest.raises(RuntimeError, match="no longer connected"):
        await _notify(channel)
    channel._request_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("credentials", [None, {"extra": {}}, _credentials(context_token=""), _credentials(chat_id="other"), _credentials(bot_token_sha256="old-bot")])
async def test_notification_requires_private_persisted_context_without_cache_fallback(channel, credentials):
    channel._connection_repo.get_credentials.return_value = credentials
    channel._context_tokens_by_chat["wx-user"] = "unscoped-cache-token"
    channel._connection_repo.find_connection_by_external_identity.return_value = _binding(metadata={"context_token": "legacy-token"})
    channel._request_json = AsyncMock()
    with pytest.raises(RuntimeError, match="private message"):
        await _notify(channel)
    channel._request_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_rechecks_owner_after_reading_context(channel):
    channel._connection_repo.find_connection_by_external_identity.side_effect = [_binding(), _binding(owner_user_id="new-owner", id="binding-2")]
    channel._request_json = AsyncMock()
    with pytest.raises(RuntimeError, match="no longer connected"):
        await _notify(channel)
    channel._request_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stopped", "no-auth", "lookup", "stopped-during-lookup", "transport"])
async def test_notification_unavailability_parks_without_sending_or_retrying(channel, failure):
    sends = []

    def transport(request):
        sends.append(request)
        raise httpx.ConnectError("offline", request=request)

    await channel._client.aclose()
    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    if failure == "stopped":
        channel._running = False
    elif failure == "no-auth":
        channel._bot_token = ""
    elif failure == "lookup":
        channel._connection_repo.find_connection_by_external_identity.side_effect = OSError("offline DB")
    elif failure == "stopped-during-lookup":

        async def stop_during_read(connection_id):
            await channel.stop()
            return _credentials()

        channel._connection_repo.get_credentials.side_effect = stop_during_read
    with pytest.raises(ChannelUnavailable):
        await _notify(channel)
    assert len(sends) == (1 if failure == "transport" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"ret": -14, "errmsg": "private-context"},
        {"ret": 0, "errcode": 40001},
        {"ret": "bad-private-context"},
        {"ret": "0"},
        {"ret": False},
        {"ret": True},
        {"ret": 0, "errcode": False},
        {"ret": 0, "errcode": "0"},
        {"ret": 0, "errcode": []},
    ],
)
async def test_platform_rejection_is_visible_and_sent_once_without_token_in_error(channel, payload):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    await channel._client.aclose()
    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    with pytest.raises(RuntimeError) as raised:
        await _notify(channel)
    assert not isinstance(raised.value, ChannelUnavailable)
    assert "private-context" not in str(raised.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"ret": None}, {"ret": 0}, {"ret": 0.0}, {"errcode": 0}, {"errcode": 0.0}, {"errcode": None}, {"message_id": "fixture-server-id"}, {"ret": None, "errcode": None}])
async def test_notification_accepts_optional_zero_codes_and_remains_nonblocking(channel, payload):
    from support.detectors.blocking_io_runtime import detect_blocking_io_strict

    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    await channel._client.aclose()
    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    with detect_blocking_io_strict():
        await _notify(channel)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"null", b"[]", b'"text"'])
async def test_notification_requires_json_object_without_changing_legacy_request_parsing(channel, body):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    await channel._client.aclose()
    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    with pytest.raises(RuntimeError, match="JSON object"):
        await _notify(channel)
    assert len(requests) == 1
    assert await channel._request_json("/ilink/bot/sendmessage", {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"not JSON"])
async def test_notification_does_not_accept_empty_or_invalid_response_body(channel, body):
    await channel._client.aclose()
    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))
    with pytest.raises(ValueError):
        await _notify(channel)


@pytest.mark.asyncio
async def test_bind_saves_private_context_outside_public_metadata(channel):
    repo = channel._connection_repo
    repo.consume_oauth_state = AsyncMock(return_value={"owner_user_id": "owner-1"})
    repo.upsert_connection = AsyncMock(return_value=_binding())
    channel._send_connection_reply = AsyncMock()
    await channel._bind_connection_from_connect_code(chat_id="wx-user", context_token="new-private-context", code="fixture-code")
    assert "context_token" not in repo.upsert_connection.call_args.kwargs.get("metadata", {})
    context = repo.store_connection_context.call_args.kwargs["extra"]["wechat_notification_context"]
    assert context["context_token"] == "new-private-context"
    assert context["chat_id"] == "wx-user"


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", [None, "group-1"])
async def test_inbound_private_context_refresh_does_not_use_group_context(channel, group_id):
    channel._publish_inbound_or_drop = AsyncMock()
    await channel._handle_update({"message_type": 1, "from_user_id": "wx-user", "context_token": "latest-context", "group_id": group_id, "item_list": [{"type": 1, "text_item": {"text": "hello"}}]})
    writes = channel._connection_repo.store_connection_context
    assert writes.await_count == (0 if group_id else 1)
    channel._publish_inbound_or_drop.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_without_owner_never_uses_cached_context(channel):
    channel._request_json = AsyncMock()
    with pytest.raises(RuntimeError):
        await channel.send_notification(target="wx-user", text_markdown="Done")
    channel._request_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_persistence_failure_does_not_drop_inbound_chat(channel, caplog):
    channel._connection_repo.store_connection_context.side_effect = OSError("private-context")
    channel._publish_inbound_or_drop = AsyncMock()
    await channel._handle_update({"message_type": 1, "from_user_id": "wx-user", "context_token": "private-context", "item_list": [{"type": 1, "text_item": {"text": "hello"}}]})
    channel._publish_inbound_or_drop.assert_awaited_once()
    assert "private-context" not in caplog.text


@pytest.mark.asyncio
async def test_group_connect_code_cannot_seed_private_notification_context(channel):
    channel._bind_connection_from_connect_code = AsyncMock()
    channel._send_connection_reply = AsyncMock()
    await channel._handle_update({"message_type": 1, "from_user_id": "wx-user", "context_token": "group-context", "group_id": "group-1", "item_list": [{"type": 1, "text_item": {"text": "/connect fixture-code"}}]})
    channel._bind_connection_from_connect_code.assert_not_awaited()
    channel._send_connection_reply.assert_awaited_once()
    channel._connection_repo.store_connection_context.assert_not_awaited()
