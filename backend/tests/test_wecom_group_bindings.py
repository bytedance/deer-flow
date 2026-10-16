"""WeCom group binding names and legacy identity boundaries, without provider I/O."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.channels.connection_identity import lookup_thread_id
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.wecom import WeComChannel
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine


@pytest_asyncio.fixture
async def repo(tmp_path):
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'wecom.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(get_session_factory())
    finally:
        await close_engine()


def inbound(group="wr-group", bot="bot-1"):
    return InboundMessage(channel_name="wecom", chat_id="alice", user_id="alice", text="group follow-up", topic_id="alice", metadata={"aibotid": bot, "chattype": "group", "chatid": group})


@pytest.mark.asyncio
@pytest.mark.parametrize("private_metadata", [{"aibotid": "bot-1", "chattype": "single"}, {"aibotid": "bot-1"}, {}])
async def test_private_binding_does_not_authorize_an_unbound_group(repo, private_metadata):
    await repo.upsert_connection(owner_user_id="owner", provider="wecom", external_account_id="alice", workspace_id="bot-1", metadata=private_metadata)
    channel = WeComChannel(MessageBus(), {"connection_repo": repo})
    message = await channel._attach_connection_identity(inbound())
    assert message.connection_id is None
    assert message.owner_user_id is None


@pytest.mark.asyncio
async def test_legacy_group_binding_retains_owner_and_existing_thread(repo):
    legacy = await repo.upsert_connection(owner_user_id="owner", provider="wecom", external_account_id="alice", workspace_id="bot-1", metadata={"aibotid": "bot-1", "chattype": "group"})
    await repo.set_thread_id(connection_id=legacy["id"], owner_user_id="owner", provider="wecom", external_conversation_id="alice", external_topic_id="alice", thread_id="existing-thread")
    channel = WeComChannel(MessageBus(), {"connection_repo": repo})
    message = await channel._attach_connection_identity(inbound())
    assert message.connection_id == legacy["id"]
    assert message.owner_user_id == "owner"
    assert await lookup_thread_id(message, repo=repo, store=None) == "existing-thread"
    other_bot = await channel._attach_connection_identity(inbound(bot="bot-2"))
    assert other_bot.connection_id is None
    await repo.disconnect_connection(connection_id=legacy["id"], owner_user_id="owner")
    revoked = await channel._attach_connection_identity(inbound())
    assert revoked.connection_id is None


@pytest.mark.asyncio
async def test_named_group_connect_records_a_human_label_without_exposing_chatid(repo):
    channel = WeComChannel(MessageBus(), {"connection_repo": repo})
    channel._ws_client = SimpleNamespace(reply=AsyncMock(), reply_stream=AsyncMock())
    for code, group, label in (("code-1", "wr-group-1", "Release team"), ("code-2", "wr-group-2", "Support team")):
        await repo.create_oauth_state(owner_user_id="owner", provider="wecom", state=code, expires_at=datetime.now(UTC) + timedelta(minutes=5), metadata={"notification_group_name": label})
        await channel._publish_ws_inbound(
            {"body": {"aibotid": "bot-1", "chattype": "group", "chatid": group, "msgid": f"msg-{code}", "from": {"userid": "alice"}, "text": {"content": f"/connect {code}"}}},
            f"/connect {code}",
        )
    rows = await repo.list_connections("owner")
    assert len(rows) == 2
    assert {row["workspace_name"] for row in rows} == {"Release team", "Support team"}
    assert {row["workspace_id"] for row in rows} == {"bot-1:group:wr-group-1", "bot-1:group:wr-group-2"}
