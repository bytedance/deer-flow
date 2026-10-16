"""QQ channel contracts: offline synthetic events and HTTP responses only."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from app.channels import qq
from app.channels.message_bus import MessageBus, OutboundMessage


def event(kind="c2c", sender="alice", target="group1", message_id="message1", text="hello"):
    data = {
        "id": message_id,
        "content": text,
        "author": {"user_openid": sender, "member_openid": sender},
    }
    if kind == "group":
        data["group_openid"] = target
    return {
        "op": 0,
        "s": 2,
        "id": "event-" + message_id,
        "t": "C2C_MESSAGE_CREATE" if kind == "c2c" else "GROUP_AT_MESSAGE_CREATE",
        "d": data,
    }


@pytest_asyncio.fixture
async def channel():
    instance = qq.QQChannel(bus=MessageBus(), config={"app_id": "app1", "client_secret": "fixture-secret"})
    instance._bot_id = "99"
    yield instance
    await instance.stop()


@pytest.mark.asyncio
async def test_c2c_preserves_reply_and_stable_identity(channel):
    await channel._handle_inbound(event())
    first = channel.bus.get_inbound_nowait()
    await channel._handle_inbound(event(message_id="message2"))
    second = channel.bus.get_inbound_nowait()
    assert first.channel_name == "qq"
    assert first.chat_id == second.chat_id == "c2c:alice"
    assert first.user_id == "alice"
    assert first.thread_ts == "message1"
    assert first.topic_id == second.topic_id
    assert first.workspace_id == "app1:c2c"
    assert first.metadata["message_id"] == "message1"


@pytest.mark.asyncio
async def test_group_members_have_distinct_topics_and_group_scope(channel):
    await channel._handle_inbound(event("group", text="<@!99> hello"))
    alice = channel.bus.get_inbound_nowait()
    await channel._handle_inbound(event("group", sender="bob", message_id="message2"))
    bob = channel.bus.get_inbound_nowait()
    assert alice.chat_id == bob.chat_id == "group:group1"
    assert alice.topic_id != bob.topic_id
    assert alice.workspace_id == "app1:group:group1"
    assert alice.text == "hello"
    await channel._handle_inbound(event("group", target="group2", message_id="message3"))
    other = channel.bus.get_inbound_nowait()
    assert other.workspace_id != alice.workspace_id


@pytest.mark.asyncio
async def test_missing_sender_and_non_message_events_are_ignored(channel):
    malformed = event()
    malformed["d"]["author"] = {}
    for incoming in (malformed, {"t": "FRIEND_ADD", "d": {}}, event(text="")):
        await channel._handle_inbound(incoming)
    assert channel.bus.inbound_queue.empty()


@pytest.mark.asyncio
async def test_duplicate_events_are_forwarded_to_manager_dedupe(channel):
    await channel._handle_inbound(event())
    await channel._handle_inbound(event())
    # Provider adapters must not own the retry policy: ChannelManager records
    # the message id and releases it when downstream handling fails.
    assert channel.bus.inbound_queue.qsize() == 2


@pytest.mark.asyncio
async def test_allowed_users_gate_precedes_identity_query(channel):
    channel._allowed_users = {"bob"}
    channel._connection_repo = AsyncMock()
    await channel._handle_inbound(event())
    assert channel.bus.inbound_queue.empty()
    channel._connection_repo.find_connection_by_external_identity.assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_precedes_allowlist_and_never_enters_agent(channel):
    repo = AsyncMock()
    repo.consume_oauth_state.return_value = {"owner_user_id": "owner-a"}
    channel._connection_repo = repo
    channel._allowed_users = {"bob"}
    channel.send = AsyncMock()
    await channel._handle_inbound(event(text="/connect one-time-fixture"))
    repo.consume_oauth_state.assert_awaited_once_with(provider="qq", state="one-time-fixture")
    kwargs = repo.upsert_connection.await_args.kwargs
    assert kwargs["provider"] == "qq"
    assert kwargs["owner_user_id"] == "owner-a"
    assert kwargs["external_account_id"] == "alice"
    assert kwargs["workspace_id"] == "app1:c2c"
    assert channel.bus.inbound_queue.empty()
    assert "one-time-fixture" not in channel.send.await_args.args[0].text


@pytest.mark.asyncio
async def test_expired_binding_code_is_consumed_locally(channel):
    channel._connection_repo = AsyncMock()
    channel._connection_repo.consume_oauth_state.return_value = None
    channel.send = AsyncMock()
    await channel._handle_inbound(event(text="/connect expired-fixture"))
    channel._connection_repo.upsert_connection.assert_not_awaited()
    assert channel.bus.inbound_queue.empty()
    assert "expired" in channel.send.await_args.args[0].text.lower()


@pytest.mark.asyncio
async def test_bound_owner_is_attached_with_exact_workspace(channel):
    repo = AsyncMock()
    repo.find_connection_by_external_identity.return_value = {
        "id": "connection-a",
        "owner_user_id": "owner-a",
        "workspace_id": "app1:group:group1",
    }
    channel._connection_repo = repo
    await channel._handle_inbound(event("group"))
    inbound = channel.bus.get_inbound_nowait()
    assert inbound.owner_user_id == "owner-a"
    assert inbound.connection_id == "connection-a"
    repo.find_connection_by_external_identity.assert_awaited_once_with(provider="qq", external_account_id="alice", workspace_id="app1:group:group1")


@pytest.mark.asyncio
async def test_identity_failure_allows_provider_redelivery(channel):
    repo = AsyncMock()
    repo.find_connection_by_external_identity.side_effect = [RuntimeError("temporary"), None]
    channel._connection_repo = repo

    with pytest.raises(RuntimeError):
        await channel._handle_inbound(event())
    await channel._handle_inbound(event())

    assert channel.bus.inbound_queue.qsize() == 1
    assert repo.find_connection_by_external_identity.await_count == 2


@pytest.mark.asyncio
async def test_full_intake_does_not_query_identity(channel):
    channel.bus = MessageBus(inbound_queue_maxsize=1)
    await channel._handle_inbound(event())
    channel._connection_repo = AsyncMock()
    await channel._handle_inbound(event(message_id="message2"))
    channel._connection_repo.find_connection_by_external_identity.assert_not_awaited()
    assert channel.bus.inbound_queue.qsize() == 1


@pytest.mark.asyncio
async def test_token_refresh_is_shared_across_concurrent_requests(channel):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 7200})

    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    values = await asyncio.gather(*(channel._get_access_token() for _ in range(8)))
    assert values == ["fixture-token"] * 8
    assert len(calls) == 1
    assert json.loads(calls[0].content) == {
        "appId": "app1",
        "clientSecret": "fixture-secret",
    }
    channel._token_expires_at = 0
    await channel._get_access_token()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_401_refresh_reuses_reply_sequence(channel):
    tokens, replies = [], []

    def handler(request):
        if request.url.host == "bots.qq.com":
            tokens.append(request)
            return httpx.Response(200, json={"access_token": f"token-{len(tokens)}", "expires_in": 7200})
        replies.append(json.loads(request.content))
        return httpx.Response(401 if len(replies) == 1 else 200, json={"id": "reply"})

    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await channel._handle_inbound(event())
    await channel.send(
        OutboundMessage(
            channel_name="qq",
            chat_id="c2c:alice",
            thread_id="thread",
            thread_ts="message1",
            text="reply",
        )
    )
    assert len(tokens) == 2
    assert replies[0] == replies[1]
    assert replies[0]["msg_seq"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "quota"), [("c2c", 4), ("group", 5)])
async def test_send_splits_utf8_and_preserves_passive_reply_budget(channel, monkeypatch, kind, quota):
    monkeypatch.setattr(qq, "MAX_TEXT_BYTES", 100)
    calls = []

    async def send_api(method, path, **kwargs):
        assert kwargs["json"]["msg_seq"] <= quota
        calls.append((path, kwargs["json"]))
        return {"id": "reply"}

    channel._api_request = send_api
    await channel._handle_inbound(event(kind))
    await channel.send(
        OutboundMessage(
            channel_name="qq",
            chat_id="group:group1" if kind == "group" else "c2c:alice",
            thread_id="thread",
            thread_ts="message1",
            text="中文🙂" * 300,
        )
    )
    assert len(calls) == quota
    expected_path = "/v2/groups/group1/messages" if kind == "group" else "/v2/users/alice/messages"
    assert all(path == expected_path for path, _ in calls)
    assert all(len(payload["content"].encode("utf-8")) <= 100 for _, payload in calls)
    assert [payload["msg_seq"] for _, payload in calls] == list(range(1, len(calls) + 1))
    assert all(payload["msg_id"] == "message1" for _, payload in calls)
    assert "truncated" in calls[-1][1]["content"].lower()


@pytest.mark.asyncio
async def test_progress_updates_do_not_spend_reply_quota(channel):
    channel._api_request = AsyncMock()
    await channel.send(
        OutboundMessage(
            channel_name="qq",
            chat_id="c2c:alice",
            thread_id="thread",
            text="thinking",
            is_final=False,
        )
    )
    channel._api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_without_source_message_fails_closed(channel):
    channel._api_request = AsyncMock()
    with pytest.raises(qq.QQAPIError):
        await channel.send(
            OutboundMessage(
                channel_name="qq",
                chat_id="c2c:alice",
                thread_id="thread",
                text="unsolicited",
            )
        )
    channel._api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_reply_context_does_not_send(channel):
    channel._api_request = AsyncMock()
    await channel._handle_inbound(event())
    channel._replies[("c2c:alice", "message1")].expires_at = 0
    with pytest.raises(qq.QQAPIError):
        await channel.send(
            OutboundMessage(
                channel_name="qq",
                chat_id="c2c:alice",
                thread_id="thread",
                thread_ts="message1",
                text="late",
            )
        )
    channel._api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_failure_never_exposes_provider_body(channel, caplog):
    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"message": "secret-response-body"})))
    with pytest.raises(qq.QQAPIError) as caught:
        await channel._get_access_token()
    assert "secret-response-body" not in str(caught.value) + caplog.text
    assert "fixture-secret" not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "gateway",
    [
        "ws://api.sgroup.qq.com/ws",
        "wss://qq.com.attacker.invalid/ws",
        "wss://user:pass@api.sgroup.qq.com/ws",
        "wss://api.bot.qq.com.attacker.invalid/websocket/",
        "wss://attacker.bot.qq.com/websocket/",
        "ws://api.bot.qq.com/websocket/",
        "wss://api.bot.qq.com:444/websocket/",
        "wss://user:pass@api.bot.qq.com/websocket/",
        "wss://api.bot.qq.com/websocket/#fragment",
    ],
)
def test_untrusted_gateway_rejected(gateway):
    with pytest.raises(qq.QQAPIError):
        qq.validate_gateway_url(gateway)


def test_valid_gateway_accepted():
    assert qq.validate_gateway_url("wss://api.sgroup.qq.com/websocket/") == "wss://api.sgroup.qq.com/websocket/"


@pytest.mark.asyncio
async def test_official_gateway_discovery_reaches_connection(channel):
    channel._api_request = AsyncMock(return_value={"url": "wss://api.bot.qq.com/websocket/"})

    async def connection(url):
        channel._running = False

    channel._run_connection = AsyncMock(side_effect=connection)
    channel._running = True
    await asyncio.wait_for(channel._listen(), timeout=0.1)
    channel._run_connection.assert_awaited_once_with("wss://api.bot.qq.com/websocket/")


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", ["sensitive-invalid-timestamp", "2026-10-03T10:00:00", 123, {}])
async def test_unknown_timestamp_uses_full_reply_window(channel, timestamp, monkeypatch, caplog):
    monkeypatch.setattr(qq.time, "monotonic", lambda: 1000)
    incoming = event(text="sensitive-message-content")
    incoming["d"]["timestamp"] = timestamp
    await channel._handle_inbound(incoming)
    assert channel.bus.get_inbound_nowait().text == "sensitive-message-content"
    assert channel._replies[("c2c:alice", "message1")].expires_at == 4600
    assert "using full passive reply window" in caplog.text
    assert "sensitive" not in caplog.text
    await channel._handle_inbound(incoming)
    assert caplog.text.count("using full passive reply window") == 1


@pytest.mark.asyncio
async def test_reply_cache_evicts_expired_context_before_active_turn(channel, monkeypatch):
    monkeypatch.setattr(qq, "MAX_CACHED_MESSAGES", 2)
    await channel._handle_inbound(event(message_id="active"))
    active = channel._replies[("c2c:alice", "active")]
    active.sequence = 1
    await channel._handle_inbound(event(message_id="expired"))
    channel._replies[("c2c:alice", "expired")].expires_at = 0
    await channel._handle_inbound(event(message_id="new"))
    assert list(channel._replies) == [("c2c:alice", "active"), ("c2c:alice", "new")]
    await channel._handle_inbound(event(message_id="active"))
    assert channel._replies[("c2c:alice", "active")] is active
    assert active.sequence == 1
    await channel._handle_inbound(event(message_id="newest"))
    assert list(channel._replies) == [("c2c:alice", "new"), ("c2c:alice", "newest")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "expected_type"), [("/help", "command"), ("/new", "command"), ("/agent list", "command"), ("/goal implement a feature", "command"), ("/custom-skill", "chat")])
async def test_known_commands_use_shared_dispatch(channel, text, expected_type):
    await channel._handle_inbound(event(text=text))
    assert channel.bus.get_inbound_nowait().msg_type == expected_type


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "quota"), [("c2c", 4), ("group", 5)])
async def test_concurrent_replies_share_one_source_quota(channel, kind, quota):
    channel._api_request = AsyncMock(return_value={"id": "reply"})
    await channel._handle_inbound(event(kind))
    msg = OutboundMessage(
        channel_name="qq",
        chat_id="group:group1" if kind == "group" else "c2c:alice",
        thread_id="thread",
        thread_ts="message1",
        text="reply",
    )
    results = await asyncio.gather(*(channel.send(msg) for _ in range(8)), return_exceptions=True)
    assert sum(isinstance(result, qq.QQAPIError) for result in results) == 8 - quota
    assert [call.kwargs["json"]["msg_seq"] for call in channel._api_request.await_args_list] == list(range(1, quota + 1))


@pytest.mark.asyncio
async def test_ambiguous_http_timeout_is_not_retried_or_reused(channel):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            raise httpx.ReadTimeout("fixture-sensitive-provider-detail")
        return httpx.Response(200, json={"id": "reply"})

    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel._get_access_token = AsyncMock(return_value="fixture-token")
    await channel._handle_inbound(event())
    msg = OutboundMessage(
        channel_name="qq",
        chat_id="c2c:alice",
        thread_id="thread",
        thread_ts="message1",
        text="reply",
    )
    with pytest.raises(qq.QQAPIError) as caught:
        await channel.send(msg)
    assert "fixture-sensitive" not in str(caught.value)
    assert len(calls) == 1
    await channel.send(msg)
    assert [payload["msg_seq"] for payload in calls] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "age"), [("c2c", 3601), ("group", 301)])
async def test_replayed_expired_messages_do_not_create_runs(channel, kind, age):
    incoming = event(kind)
    incoming["d"]["timestamp"] = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
    await channel._handle_inbound(incoming)
    assert channel.bus.inbound_queue.empty()
    assert not channel._replies


@pytest.mark.asyncio
async def test_bind_code_without_repository_never_reaches_agent(channel):
    await channel._handle_inbound(event(text="/connect fixture-private-code"))
    assert channel.bus.inbound_queue.empty()


@pytest.mark.asyncio
async def test_only_the_actual_bot_mention_is_removed(channel):
    await channel._handle_inbound(event("group", text="<@!someone-else> hello"))
    assert channel.bus.get_inbound_nowait().text == "<@!someone-else> hello"
