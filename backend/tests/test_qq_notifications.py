"""QQ proactive C2C notifications: serialized HTTP, no real provider calls."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import traceback
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.channels.base import ChannelUnavailable
from app.channels.message_bus import MessageBus
from app.channels.qq import QQAPIError, QQChannel, _ReplyContext

pytestmark = pytest.mark.asyncio


def binding(**overrides):
    return {
        "owner_user_id": "owner",
        "provider": "qq",
        "status": "connected",
        "external_account_id": "user-openid",
        "workspace_id": "app1:c2c",
        "metadata": {"chat_type": "c2c"},
        **overrides,
    }


@asynccontextmanager
async def connected(handler=None, *, bindings=None):
    requests = []

    async def respond(request):
        requests.append(request)
        if handler is not None:
            response = handler(request)
            if inspect.isawaitable(response):
                response = await response
            return response
        if request.url.host == "bots.qq.com":
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 7200})
        return httpx.Response(200, json={"id": "notification-id"})

    repo = SimpleNamespace(list_connections=AsyncMock(return_value=[binding()] if bindings is None else bindings))
    channel = QQChannel(MessageBus(), {"app_id": "app1", "client_secret": "fixture-secret", "connection_repo": repo})
    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=15, trust_env=False)
    channel._running = True
    channel._ready.set()
    channel._listener = asyncio.create_task(asyncio.Event().wait())
    try:
        yield channel, requests
    finally:
        await channel.stop()


async def notify(channel, *, owner="owner", target="user-openid", text="任务已完成。\nOpen DeerFlow for details."):
    await channel.send_notification_for_owner(owner_user_id=owner, target=target, text_markdown=text)


async def test_private_notification_serializes_without_passive_message_context():
    async with connected() as (channel, requests):
        context = _ReplyContext("/unused/passive/path", time.monotonic() - 1, 4, sequence=4)
        channel._replies[("c2c:user-openid", "old-message")] = context
        await notify(channel)
        channel._connection_repo.list_connections.assert_awaited_once_with("owner")
        assert len(requests) == 2
        token, message = requests
        assert json.loads(token.content) == {"appId": "app1", "clientSecret": "fixture-secret"}
        assert str(message.url) == "https://api.sgroup.qq.com/v2/users/user-openid/messages"
        assert message.headers["Authorization"] == "QQBot fixture-token"
        assert message.headers["X-Union-Appid"] == "app1"
        assert message.extensions["timeout"] == {"connect": 15, "read": 15, "write": 15, "pool": 15}
        assert json.loads(message.content) == {"msg_type": 0, "content": "任务已完成。\nOpen DeerFlow for details."}
        assert context.sequence == 4
        assert len(channel._replies) == 1


async def test_notification_waits_for_message_ack():
    sending, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        sending.set()
        await release.wait()
        return httpx.Response(200, json={"id": "notification-id"})

    async with connected(handler) as (channel, requests):
        channel._access_token = "fixture-token"
        channel._token_expires_at = time.monotonic() + 60
        task = asyncio.create_task(notify(channel))
        try:
            await asyncio.wait_for(sending.wait(), 1)
            assert not task.done()
            release.set()
            await task
            assert len(requests) == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "override",
    [
        {"owner_user_id": "other-owner"},
        {"provider": "feishu"},
        {"status": "revoked"},
        {"external_account_id": "other-user"},
        {"workspace_id": "another-app:c2c"},
        {"workspace_id": "app1:group:group-id", "metadata": {"chat_type": "group"}},
        {"metadata": {"chat_type": "group"}},
        {"metadata": {}},
    ],
)
async def test_notification_refuses_non_private_or_wrong_owner_binding(override):
    async with connected(bindings=[binding(**override)]) as (channel, requests):
        with pytest.raises(QQAPIError, match="private.*connected"):
            await notify(channel)
        assert requests == []


async def test_notification_rechecks_binding_on_every_attempt():
    async with connected() as (channel, requests):
        await notify(channel)
        channel._connection_repo.list_connections.return_value = []
        with pytest.raises(QQAPIError, match="private.*connected"):
            await notify(channel)
        assert len(requests) == 2
        assert channel._connection_repo.list_connections.await_count == 2


@pytest.mark.parametrize("case", ["lookup-error", "missing-owner", "missing-repo"])
async def test_missing_binding_verification_parks_without_send(case, caplog):
    async with connected() as (channel, requests):
        owner = "owner"
        if case == "lookup-error":
            channel._connection_repo.list_connections.side_effect = OSError("sensitive-owner-detail")
        elif case == "missing-owner":
            owner = None
        else:
            channel._connection_repo = None
        with pytest.raises(ChannelUnavailable) as caught:
            await notify(channel, owner=owner)
        assert requests == []
        assert "sensitive-owner-detail" not in "".join(traceback.format_exception(caught.value)) + caplog.text


@pytest.mark.parametrize("condition", ["stopped", "not-ready", "listener-ended", "http-closed", "http-missing"])
async def test_notification_parks_without_live_transport(condition):
    async with connected() as (channel, requests):
        if condition == "stopped":
            channel._running = False
        elif condition == "not-ready":
            channel._ready.clear()
        elif condition == "listener-ended":
            channel._listener.cancel()
            await asyncio.gather(channel._listener, return_exceptions=True)
        elif condition == "http-closed":
            await channel._http.aclose()
        else:
            await channel._http.aclose()
            channel._http = None
        with pytest.raises(ChannelUnavailable):
            await notify(channel)
        assert requests == []


@pytest.mark.parametrize("stage", ["token", "message"])
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
async def test_transport_error_parks_without_retry_or_sensitive_details(stage, error_type, caplog):
    def handler(request):
        raise error_type("sensitive-provider-detail", request=request)

    async with connected(handler) as (channel, requests):
        if stage == "message":
            channel._access_token = "fixture-token"
            channel._token_expires_at = time.monotonic() + 60
        with pytest.raises(ChannelUnavailable) as caught:
            await notify(channel)
        assert len(requests) == 1
        rendered = "".join(traceback.format_exception(caught.value)) + caplog.text
        assert "sensitive-provider-detail" not in rendered
        assert "fixture-secret" not in rendered
        assert "fixture-token" not in rendered


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (403, {"err_code": 40054013, "message": "sensitive-rejection-body"}),
        (429, {"err_code": 40034100, "message": "sensitive-rejection-body"}),
        (200, {"code": 40034105, "id": "not-an-ack", "message": "sensitive-rejection-body"}),
        (200, {"err_code": 40054013, "id": "not-an-ack", "message": "sensitive-rejection-body"}),
        (200, {}),
        (200, {"id": ""}),
        (200, {"id": 12}),
        (200, {"id": " "}),
    ],
)
async def test_rejection_or_missing_ack_counts_as_failure(status, payload, caplog):
    async with connected(lambda request: httpx.Response(status, json=payload)) as (channel, requests):
        channel._access_token = "fixture-token"
        channel._token_expires_at = time.monotonic() + 60
        with pytest.raises(QQAPIError) as caught:
            await notify(channel)
        assert not isinstance(caught.value, ChannelUnavailable)
        assert len(requests) == 1
        assert "sensitive-rejection-body" not in "".join(traceback.format_exception(caught.value)) + caplog.text


async def test_auth_refresh_keeps_proactive_payload_and_no_passive_budget():
    token_requests, message_requests = [], []

    def handler(request):
        if request.url.host == "bots.qq.com":
            token_requests.append(request)
            return httpx.Response(200, json={"access_token": f"token-{len(token_requests)}", "expires_in": 7200})
        message_requests.append(request)
        return httpx.Response(401 if len(message_requests) == 1 else 200, json={"id": "notification-id"})

    async with connected(handler) as (channel, requests):
        await notify(channel)
        assert len(token_requests) == 2
        assert len(message_requests) == 2
        assert message_requests[0].content == message_requests[1].content
        assert message_requests[1].headers["Authorization"] == "QQBot token-2"
        assert not channel._replies


def group_binding(**overrides):
    return {
        "id": "group-binding",
        "owner_user_id": "owner",
        "provider": "qq",
        "status": "connected",
        "external_account_id": "member-openid",
        "workspace_id": "app1:group:group-openid",
        "metadata": {"chat_type": "group", "group_openid": "group-openid"},
        **overrides,
    }


async def test_group_notification_serializes_to_group_endpoint_without_passive_context():
    async with connected(bindings=[group_binding()]) as (channel, requests):
        await channel.send_group_notification_for_owner(
            owner_user_id="owner",
            target="group-binding",
            text_markdown="任务已完成。\nOpen DeerFlow for details.",
        )
        channel._connection_repo.list_connections.assert_awaited_once_with("owner")
        assert len(requests) == 2
        _token, message = requests
        assert str(message.url) == "https://api.sgroup.qq.com/v2/groups/group-openid/messages"
        assert json.loads(message.content) == {"msg_type": 0, "content": "任务已完成。\nOpen DeerFlow for details."}


@pytest.mark.parametrize(
    "override",
    [
        {"id": "other-binding"},
        {"owner_user_id": "other-owner"},
        {"provider": "feishu"},
        {"status": "revoked"},
        {"workspace_id": "another-app:group:group-openid"},
        {"workspace_id": "app1:c2c", "metadata": {"chat_type": "c2c"}},
        {"metadata": {"chat_type": "c2c"}},
        {"metadata": {"chat_type": "group", "group_openid": "other-group"}},
    ],
)
async def test_group_notification_refuses_invalid_or_unowned_binding_without_private_fallback(override):
    async with connected(bindings=[binding(), group_binding(**override)]) as (channel, requests):
        with pytest.raises(QQAPIError, match="group.*connected"):
            await channel.send_group_notification_for_owner(
                owner_user_id="owner",
                target="group-binding",
                text_markdown="Done",
            )
        assert requests == []


async def test_notification_cancellation_propagates_without_retry():
    sending = asyncio.Event()

    async def handler(request):
        sending.set()
        await asyncio.Event().wait()

    async with connected(handler) as (channel, requests):
        channel._access_token = "fixture-token"
        channel._token_expires_at = time.monotonic() + 60
        task = asyncio.create_task(notify(channel))
        try:
            await asyncio.wait_for(sending.wait(), 1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(requests) == 1


async def test_qq_group_bind_does_not_use_raw_ids_as_display_names():
    from unittest.mock import AsyncMock

    async with connected() as (channel, _requests):
        channel._connection_repo.consume_oauth_state = AsyncMock(return_value={"owner_user_id": "owner"})
        channel._connection_repo.upsert_connection = AsyncMock(return_value={"id": "bound"})
        await channel._handle_inbound(
            {
                "t": "GROUP_AT_MESSAGE_CREATE",
                "d": {
                    "group_openid": "group-open-1",
                    "author": {"member_openid": "member-1"},
                    "id": "m-1",
                    "content": "/connect code-1",
                },
            }
        )
        await channel._handle_inbound(
            {
                "t": "GROUP_AT_MESSAGE_CREATE",
                "d": {
                    "group_openid": "group-open-2",
                    "author": {"member_openid": "member-1"},
                    "id": "m-2",
                    "content": "/connect code-2",
                },
            }
        )
        calls = channel._connection_repo.upsert_connection.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["workspace_id"] == "app1:group:group-open-1"
        assert calls[0].kwargs["workspace_name"] is None
        assert calls[1].kwargs["workspace_id"] == "app1:group:group-open-2"
        assert calls[1].kwargs["workspace_name"] is None
