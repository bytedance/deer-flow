"""QQ ownership integration against the real SQLite connection repository."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.channels.manager import ChannelManager
from app.channels.message_bus import MessageBus
from app.channels.qq import QQChannel
from app.channels.store import JsonChannelStore
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine


@pytest_asyncio.fixture
async def repo(tmp_path):
    await init_engine(
        "sqlite",
        url=f"sqlite+aiosqlite:///{tmp_path / 'qq.db'}",
        sqlite_dir=str(tmp_path),
    )
    try:
        yield ChannelConnectionRepository(get_session_factory())
    finally:
        await close_engine()


def incoming(message_id, text="hello", group=None):
    data = {
        "id": message_id,
        "content": text,
        "author": {"user_openid": "alice", "member_openid": "alice"},
    }
    if group:
        data["group_openid"] = group
    return {
        "t": "GROUP_AT_MESSAGE_CREATE" if group else "C2C_MESSAGE_CREATE",
        "d": data,
    }


async def bind(repo, channel, owner, code, message_id, group=None):
    await repo.create_oauth_state(
        owner_user_id=owner,
        provider="qq",
        state=code,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await channel._handle_inbound(incoming(message_id, f"/connect {code}", group))


@pytest.mark.asyncio
async def test_binding_transfer_rejects_queued_old_owner(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    bus = MessageBus()
    channel = QQChannel(bus, {"app_id": "app1", "client_secret": "fixture", "connection_repo": repo})
    channel.send = AsyncMock()
    manager = ChannelManager(
        bus,
        JsonChannelStore(tmp_path / "threads.json"),
        connection_repo=repo,
        require_bound_identity=True,
    )
    try:
        await bind(repo, channel, "owner-a", "code-a", "bind-a")
        await channel._handle_inbound(incoming("queued-a"))
        queued = bus.get_inbound_nowait()
        assert queued.owner_user_id == "owner-a"
        assert await manager._get_bound_identity_rejection(queued) is None

        await bind(repo, channel, "owner-b", "code-b", "bind-b")
        assert await manager._get_bound_identity_rejection(queued) is not None
        await channel._handle_inbound(incoming("fresh-b"))
        fresh = bus.get_inbound_nowait()
        assert fresh.owner_user_id == "owner-b"
        assert await manager._get_bound_identity_rejection(fresh) is None

        # A used browser code cannot transfer the identity back.
        await channel._handle_inbound(incoming("replay-a", "/connect code-a"))
        await channel._handle_inbound(incoming("after-replay"))
        assert bus.get_inbound_nowait().owner_user_id == "owner-b"
        assert "expired" in channel.send.await_args.args[0].text
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_private_group_and_app_bindings_do_not_fall_back(repo):
    channel = QQChannel(
        MessageBus(),
        {"app_id": "app1", "client_secret": "fixture", "connection_repo": repo},
    )
    other_app = QQChannel(
        MessageBus(),
        {"app_id": "app2", "client_secret": "fixture", "connection_repo": repo},
    )
    channel.send = AsyncMock()
    try:
        await bind(repo, channel, "private-owner", "private-code", "private-bind")
        await channel._handle_inbound(incoming("unbound-group", group="group1"))
        assert channel.bus.get_inbound_nowait().owner_user_id is None
        await other_app._handle_inbound(incoming("other-app"))
        assert other_app.bus.get_inbound_nowait().owner_user_id is None

        await bind(repo, channel, "group-owner", "group-code", "group-bind", group="group1")
        await channel._handle_inbound(incoming("bound-group", group="group1"))
        assert channel.bus.get_inbound_nowait().owner_user_id == "group-owner"
        await channel._handle_inbound(incoming("another-group", group="group2"))
        assert channel.bus.get_inbound_nowait().owner_user_id is None
        await channel._handle_inbound(incoming("still-private"))
        assert channel.bus.get_inbound_nowait().owner_user_id == "private-owner"
    finally:
        await channel.stop()
        await other_app.stop()
