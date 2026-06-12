"""Connection binding tests for browser-connectable IM channels beyond Telegram/Slack/Discord."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.channels.message_bus import InboundMessage, MessageBus


async def _make_repo(tmp_path, name: str):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / f'{name}.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(get_session_factory())


async def _seed_state(repo, provider: str, state: str, owner_user_id: str = "deerflow-user-1") -> None:
    await repo.create_oauth_state(
        owner_user_id=owner_user_id,
        provider=provider,
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_feishu_connect_command_binds_identity(tmp_path):
    import anyio

    from app.channels.feishu import FeishuChannel

    async def go():
        repo = await _make_repo(tmp_path, "feishu")
        state = "feishu-bind-code"
        await _seed_state(repo, "feishu", state)
        channel = FeishuChannel(
            bus=MessageBus(),
            config={"app_id": "app", "app_secret": "secret", "connection_repo": repo},
        )
        channel._reply_card = AsyncMock()

        handled = await channel._bind_connection_from_connect_code(
            message_id="om-message-1",
            chat_id="oc-chat-1",
            user_id="ou-user-1",
            code=state,
        )

        connections = await repo.list_connections("deerflow-user-1")
        assert handled is True
        assert len(connections) == 1
        assert connections[0]["provider"] == "feishu"
        assert connections[0]["external_account_id"] == "ou-user-1"
        assert connections[0]["workspace_id"] == "oc-chat-1"
        channel._reply_card.assert_awaited_once_with("om-message-1", "Feishu connected to DeerFlow.")
        await repo.close()

    anyio.run(go)


def test_dingtalk_connect_command_binds_identity(tmp_path):
    import anyio

    from app.channels.dingtalk import _CONVERSATION_TYPE_GROUP, DingTalkChannel

    async def go():
        repo = await _make_repo(tmp_path, "dingtalk")
        state = "dingtalk-bind-code"
        await _seed_state(repo, "dingtalk", state)
        channel = DingTalkChannel(
            bus=MessageBus(),
            config={"client_id": "client", "client_secret": "secret", "connection_repo": repo},
        )
        channel._send_connection_reply = AsyncMock()

        handled = await channel._bind_connection_from_connect_code(
            conversation_type=_CONVERSATION_TYPE_GROUP,
            sender_staff_id="staff-user-1",
            sender_nick="Alice",
            conversation_id="cid-group-1",
            code=state,
        )

        connections = await repo.list_connections("deerflow-user-1")
        assert handled is True
        assert len(connections) == 1
        assert connections[0]["provider"] == "dingtalk"
        assert connections[0]["external_account_id"] == "staff-user-1"
        assert connections[0]["external_account_name"] == "Alice"
        assert connections[0]["workspace_id"] == "cid-group-1"
        channel._send_connection_reply.assert_awaited_once()
        await repo.close()

    anyio.run(go)


def test_wechat_connect_command_binds_identity(tmp_path):
    import anyio

    from app.channels.wechat import WechatChannel

    async def go():
        repo = await _make_repo(tmp_path, "wechat")
        state = "wechat-bind-code"
        await _seed_state(repo, "wechat", state)
        channel = WechatChannel(
            bus=MessageBus(),
            config={"bot_token": "token", "connection_repo": repo},
        )
        channel._send_connection_reply = AsyncMock()

        handled = await channel._bind_connection_from_connect_code(
            chat_id="wx-user-1",
            context_token="ctx-1",
            code=state,
        )

        connections = await repo.list_connections("deerflow-user-1")
        assert handled is True
        assert len(connections) == 1
        assert connections[0]["provider"] == "wechat"
        assert connections[0]["external_account_id"] == "wx-user-1"
        assert connections[0]["workspace_id"] == "wx-user-1"
        channel._send_connection_reply.assert_awaited_once_with("wx-user-1", "ctx-1", "WeChat connected to DeerFlow.")
        await repo.close()

    anyio.run(go)


def test_wecom_connect_command_binds_identity(tmp_path):
    import anyio

    from app.channels.wecom import WeComChannel

    async def go():
        repo = await _make_repo(tmp_path, "wecom")
        state = "wecom-bind-code"
        await _seed_state(repo, "wecom", state)
        channel = WeComChannel(
            bus=MessageBus(),
            config={"bot_id": "bot", "bot_secret": "secret", "connection_repo": repo},
        )
        channel._ws_client = MagicMock()
        channel._ws_client.reply = AsyncMock()
        frame = {"body": {"aibotid": "bot-1", "chattype": "single"}}

        handled = await channel._bind_connection_from_connect_code(
            frame=frame,
            user_id="wecom-user-1",
            code=state,
        )

        connections = await repo.list_connections("deerflow-user-1")
        assert handled is True
        assert len(connections) == 1
        assert connections[0]["provider"] == "wecom"
        assert connections[0]["external_account_id"] == "wecom-user-1"
        assert connections[0]["workspace_id"] == "bot-1"
        channel._ws_client.reply.assert_awaited_once_with(frame, {"msgtype": "text", "text": {"content": "WeCom connected to DeerFlow."}})
        await repo.close()

    anyio.run(go)


def test_additional_channels_attach_owner_identity(tmp_path):
    import anyio

    from app.channels.dingtalk import _CONVERSATION_TYPE_GROUP, DingTalkChannel
    from app.channels.feishu import FeishuChannel
    from app.channels.wechat import WechatChannel
    from app.channels.wecom import WeComChannel

    async def go():
        repo = await _make_repo(tmp_path, "additional-identity")
        await repo.upsert_connection(
            owner_user_id="deerflow-user-1",
            provider="feishu",
            external_account_id="ou-user-1",
            workspace_id="oc-chat-1",
        )
        await repo.upsert_connection(
            owner_user_id="deerflow-user-1",
            provider="dingtalk",
            external_account_id="staff-user-1",
            workspace_id="cid-group-1",
        )
        await repo.upsert_connection(
            owner_user_id="deerflow-user-1",
            provider="wechat",
            external_account_id="wx-user-1",
            workspace_id="wx-user-1",
        )
        await repo.upsert_connection(
            owner_user_id="deerflow-user-1",
            provider="wecom",
            external_account_id="wecom-user-1",
            workspace_id="bot-1",
        )

        cases = [
            (
                FeishuChannel(bus=MessageBus(), config={"connection_repo": repo}),
                InboundMessage(channel_name="feishu", chat_id="oc-chat-1", user_id="ou-user-1", text="hello"),
            ),
            (
                DingTalkChannel(bus=MessageBus(), config={"connection_repo": repo}),
                InboundMessage(
                    channel_name="dingtalk",
                    chat_id="cid-group-1",
                    user_id="staff-user-1",
                    text="hello",
                    metadata={
                        "conversation_type": _CONVERSATION_TYPE_GROUP,
                        "conversation_id": "cid-group-1",
                    },
                ),
            ),
            (
                WechatChannel(bus=MessageBus(), config={"connection_repo": repo}),
                InboundMessage(channel_name="wechat", chat_id="wx-user-1", user_id="wx-user-1", text="hello"),
            ),
            (
                WeComChannel(bus=MessageBus(), config={"connection_repo": repo}),
                InboundMessage(
                    channel_name="wecom",
                    chat_id="wecom-user-1",
                    user_id="wecom-user-1",
                    text="hello",
                    metadata={"aibotid": "bot-1"},
                ),
            ),
        ]

        for channel, inbound in cases:
            attached = await channel._attach_connection_identity(inbound)
            assert attached.owner_user_id == "deerflow-user-1"
            assert attached.connection_id
            assert (
                attached.workspace_id
                == {
                    "feishu": "oc-chat-1",
                    "dingtalk": "cid-group-1",
                    "wechat": "wx-user-1",
                    "wecom": "bot-1",
                }[channel.name]
            )

        await repo.close()

    anyio.run(go)
