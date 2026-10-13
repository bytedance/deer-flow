"""Native SQL workspace lifecycle before Gateway authorization is wired."""

import asyncio
import importlib
import importlib.util
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_workspace_repository_provisions_and_preserves_one_owner(native_engine):  # noqa: F811
    from deerflow.persistence.user.model import UserRow

    name = "deerflow.persistence.workspaces.sql"
    assert importlib.util.find_spec(name) is not None, "native workspace repository is not implemented"
    module = importlib.import_module(name)
    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
        for user in ("peer", "third"):
            conn.execute(sa.insert(UserRow).values(id=user, email=user + "@example.invalid", email_verified_at=datetime.now(UTC)))
        conn.execute(sa.insert(UserRow).values(id="pending", email="pending@example.invalid"))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            assert module.workspace_repository(sf, enabled=False) is None
            with pytest.raises(ValueError, match="persistent"):
                module.workspace_repository(None, enabled=True)
            repo = module.workspace_repository(sf, enabled=True)
            with pytest.raises(module.WorkspaceAccessDenied):
                await repo.provision_personal("pending")
            first = await repo.provision_personal("owner")
            assert (await repo.provision_personal("owner"))["id"] == first["id"]
            assert (await repo.get_active_membership(first["id"], "owner"))["role"] == "owner"
            assert await repo.get_active_membership(first["id"], "peer") is None
            team = await repo.create_team("owner", "Research", "create-once")
            assert (await repo.create_team("owner", "Research", "create-once"))["id"] == team["id"]
            with pytest.raises(ValueError, match="idempotency"):
                await repo.create_team("owner", "Changed", "create-once")
            assert len(await repo.list_workspaces("owner")) == 2
            assert await repo.list_workspaces("pending") == []
            await repo.add_member(team["id"], "owner", "peer", role="member")
            await repo.add_member(team["id"], "owner", "third", role="member")
            await repo.change_role(team["id"], "owner", "peer", role="admin")
            with pytest.raises(module.WorkspaceAccessDenied):
                await repo.remove_member(team["id"], "peer", "owner")
            with pytest.raises(module.WorkspaceAccessDenied):
                await repo.add_member(first["id"], "owner", "peer", role="member")
            if native_engine.dialect.name == "postgresql":
                # A reset already holding the native account row must win over
                # a transfer carrying its old proof. Observe actual DB lock
                # waiting (or early task completion), not a mocked authority.
                async with sf() as reset_session:
                    await reset_session.execute(sa.update(UserRow).where(UserRow.id == "owner").values(token_version=1))
                    transfer = asyncio.create_task(repo.transfer_owner(team["id"], "owner", "peer", expected_token_version=0, expected_password_hash=None))
                    try:
                        async with asyncio.timeout(5):
                            while not transfer.done():
                                async with sf() as observer:
                                    waiting = await observer.scalar(
                                        sa.text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE :query"),
                                        {"query": "SELECT users.token_version, users.password_hash%"},
                                    )
                                if waiting:
                                    break
                                await asyncio.sleep(0.02)
                    finally:
                        await reset_session.commit()
                        transfer_result = (await asyncio.gather(transfer, return_exceptions=True))[0]
                    assert isinstance(transfer_result, module.WorkspaceAccessDenied), "old credential proof committed ownership while password reset held the user row"
                assert (await repo.get_active_membership(team["id"], "owner"))["role"] == "owner"
            results = await asyncio.gather(repo.transfer_owner(team["id"], "owner", "peer"), repo.transfer_owner(team["id"], "owner", "third"), return_exceptions=True)
            assert sum(not isinstance(result, Exception) for result in results) == 1
            assert sum(isinstance(result, module.WorkspaceAccessDenied) for result in results) == 1
            peers = [await repo.get_active_membership(team["id"], user) for user in ("owner", "peer", "third")]
            assert sum(member["role"] == "owner" for member in peers) == 1
            new_owner = next(member["user_id"] for member in peers if member["role"] == "owner")
            with pytest.raises(module.WorkspaceAccessDenied):
                await repo.remove_member(team["id"], new_owner, new_owner)
            await repo.remove_member(team["id"], new_owner, "owner")
            assert await repo.get_active_membership(team["id"], "owner") is None
            with pytest.raises(module.WorkspaceAccessDenied):
                await repo.create_team("owner", "Research", "create-once")
            assert [row["id"] for row in await repo.list_workspaces("owner")] == [first["id"]]
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    with native_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM workspace_memberships WHERE role='owner' AND status='active'")).scalar_one() == 2
