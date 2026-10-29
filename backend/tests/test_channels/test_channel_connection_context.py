"""Private context writes cannot restore credentials after binding revocation."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.dml import Update
from support.postgres import asyncpg_test_url

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel
from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher, ChannelCredentialRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repo(tmp_path, request):
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres connection-context guards)")
        import deerflow.persistence.models  # noqa: F401 -- production ORM registration
        from deerflow.persistence.base import Base

        schema = f"channel_context_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
        created = False
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            yield ChannelConnectionRepository(async_sessionmaker(engine, expire_on_commit=False), cipher=ChannelCredentialCipher.from_key("test-only-context-key"))
        finally:
            try:
                if created:
                    async with engine.begin() as connection:
                        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            finally:
                await engine.dispose()
        return

    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("test-only-context-key"))
    finally:
        await close_engine()


async def _bind(repo, owner="owner-1"):
    return await repo.upsert_connection(owner_user_id=owner, provider="wechat", external_account_id="wx-user", workspace_id="wx-user")


async def _store(repo, connection, **overrides):
    args = {"owner_user_id": "owner-1", "provider": "wechat", "external_account_id": "wx-user", "workspace_id": "wx-user", "extra": {"context": "private-context"}, **overrides}
    return await repo.store_connection_context(connection["id"], **args)


@pytest.mark.asyncio
async def test_context_is_encrypted_and_preserves_existing_credentials(repo):
    connection = await _bind(repo)
    await repo.store_credentials(connection["id"], access_token="access", refresh_token="refresh", token_type="Bearer", extra={"another_context": "keep"})
    assert await _store(repo, connection)
    restored = ChannelConnectionRepository(repo.session_factory, cipher=ChannelCredentialCipher.from_key("test-only-context-key"))
    credentials = await restored.get_credentials(connection["id"])
    assert credentials["access_token"] == "access"
    assert credentials["refresh_token"] == "refresh"
    assert credentials["token_type"] == "Bearer"
    assert credentials["extra"] == {"another_context": "keep", "context": "private-context"}
    assert (await repo.list_connections("owner-1"))[0]["metadata"] == {}
    async with repo.session_factory() as session:
        row = await session.get(ChannelCredentialRow, connection["id"])
        assert "private-context" not in row.encrypted_extra_json


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"owner_user_id": "other"}, {"provider": "feishu"}, {"external_account_id": "other"}, {"workspace_id": "group"}])
async def test_context_write_requires_matching_current_identity(repo, override):
    connection = await _bind(repo)
    assert not await _store(repo, connection, **override)
    assert await repo.get_credentials(connection["id"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disconnect", "transfer"])
async def test_delayed_context_write_cannot_restore_revoked_credentials(repo, change):
    connection = await _bind(repo)
    await repo.store_credentials(connection["id"], access_token=None, extra={"context": "old"})
    ready, release = asyncio.Event(), asyncio.Event()

    async def delayed_write():
        ready.set()
        await release.wait()
        return await _store(repo, connection)

    pending = asyncio.create_task(delayed_write())
    try:
        await ready.wait()
        if change == "disconnect":
            await repo.disconnect_connection(connection_id=connection["id"], owner_user_id="owner-1")
        else:
            await _bind(repo, "owner-2")
        release.set()
        assert not await pending
        assert await repo.get_credentials(connection["id"]) is None
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_transfer_waits_for_context_write_then_removes_its_credentials(repo):
    connection = await _bind(repo)
    locked, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class WriterSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            if isinstance(statement, Update) and statement.table.name == "channel_connections":
                locked.set()
                await release.wait()
            return result

    class TransferSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "channel_connections":
                attempted.set()
            return await super().execute(statement, *args, **kwargs)

    cipher = ChannelCredentialCipher.from_key("test-only-context-key")
    engine = repo.session_factory.kw["bind"]
    writer_repo = ChannelConnectionRepository(async_sessionmaker(engine, class_=WriterSession, expire_on_commit=False), cipher=cipher)
    transfer_repo = ChannelConnectionRepository(async_sessionmaker(engine, class_=TransferSession, expire_on_commit=False), cipher=cipher)
    writer = asyncio.create_task(_store(writer_repo, connection))
    transfer = None
    try:
        await asyncio.wait_for(locked.wait(), 3)
        transfer = asyncio.create_task(_bind(transfer_repo, "owner-2"))
        await asyncio.wait_for(attempted.wait(), 3)
        assert not transfer.done()
        release.set()
        assert await asyncio.wait_for(writer, 3)
        replacement = await asyncio.wait_for(transfer, 3)
        assert await repo.get_credentials(connection["id"]) is None
        assert await repo.get_credentials(replacement["id"]) is None
    finally:
        release.set()
        await asyncio.gather(writer, *([transfer] if transfer else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_wechat_private_context_survives_channel_and_repository_restart(repo):
    connection = await _bind(repo)
    old = WechatChannel(MessageBus(), {"bot_token": "bot-token", "connection_repo": repo})
    old._publish_inbound_or_drop = AsyncMock()
    await old._handle_update({"message_type": 1, "from_user_id": "wx-user", "context_token": "restored-private-context", "item_list": [{"type": 1, "text_item": {"text": "hello"}}]})
    assert "context_token" not in (await repo.list_connections("owner-1"))[0]["metadata"]
    restored_repo = ChannelConnectionRepository(repo.session_factory, cipher=ChannelCredentialCipher.from_key("test-only-context-key"))
    channel = WechatChannel(MessageBus(), {"bot_token": "bot-token", "connection_repo": restored_repo})
    channel._running = True
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ret": 0})

    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        assert not channel._context_tokens_by_chat
        await channel.send_notification_for_owner(owner_user_id="owner-1", target="wx-user", text_markdown="Done")
        assert sent[0]["msg"]["context_token"] == "restored-private-context"
        await repo.disconnect_connection(connection_id=connection["id"], owner_user_id="owner-1")
        with pytest.raises(RuntimeError, match="no longer connected"):
            await channel.send_notification_for_owner(owner_user_id="owner-1", target="wx-user", text_markdown="Done")
        assert len(sent) == 1
    finally:
        await channel.stop()
