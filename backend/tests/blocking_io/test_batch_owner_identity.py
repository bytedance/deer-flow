"""Dispatch revalidation reads the live account without blocking the Gateway."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.subagent_batches.identity import resolve_batch_principal
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.user.model import UserRow
from deerflow.subagents.batch_service import SubagentBatchService


@pytest.mark.asyncio
async def test_batch_owner_lookup_does_not_block_the_host_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/users.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(UserRow.__table__.create)
        repo = SQLiteUserRepository(async_sessionmaker(engine, expire_on_commit=False))
        user = await repo.create_user(User(email="owner@example.com"))
        service = SubagentBatchService(
            repository=None,
            config=SubagentBatchesConfig(),
            runtime_config=SubagentRuntimeConfig(),
            resolve_principal=lambda batch: resolve_batch_principal(batch, load_user=repo.get_user_by_id),
        )
        resolver = service._bind_principal_resolver({"user_id": str(user.id), "execution_spec": {"user_role": "user"}})
        assert (await resolver()).role == "user"
        await repo.set_disabled(str(user.id), True)
        with pytest.raises(PermissionError):
            await resolver()
    finally:
        await engine.dispose()
