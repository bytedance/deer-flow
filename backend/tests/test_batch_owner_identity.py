"""Gateway batch identity resolves against the current account repository."""

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.subagent_batches.identity import resolve_batch_principal
from deerflow.persistence.user.model import UserRow


@pytest_asyncio.fixture
async def accounts(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/users.db")
    async with engine.begin() as connection:
        await connection.run_sync(UserRow.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = SQLiteUserRepository(sessions)
    owner = await repo.create_user(User(email="owner@example.com", system_role="admin", oauth_provider="oidc", oauth_id="current"))
    await repo.create_user(User(email="root@example.com", system_role="admin"))
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    try:
        yield repo, owner, sessions
    finally:
        await engine.dispose()


def _batch(owner, **spec):
    return {"user_id": owner, "execution_spec": spec}


@pytest.mark.asyncio
async def test_current_profile_replaces_stored_oauth_and_attributes(accounts):
    repo, owner, _ = accounts
    principal = await resolve_batch_principal(_batch(str(owner.id), user_role="admin", oauth_provider="old", oauth_id="old", authz_attributes={"admin": True}, is_internal=True, channel_user_id="im-user"), load_user=repo.get_user_by_id)
    assert (principal.user_id, principal.role, principal.oauth_provider, principal.oauth_id) == (str(owner.id), "admin", "oidc", "current")
    assert principal.is_internal and principal.channel_user_id == "im-user"
    assert principal.attributes == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "demoted", "reset", "deleted"])
@pytest.mark.parametrize("internal", [False, True])
async def test_revoked_local_owner_cannot_fall_back_to_internal(accounts, change, internal):
    repo, owner, sessions = accounts
    batch = _batch(str(owner.id), user_role="admin", is_internal=internal)
    if change == "disabled":
        await repo.set_disabled(str(owner.id), True)
    elif change == "demoted":
        await repo.update_system_role(str(owner.id), "user")
    elif change == "reset":
        await repo.update_user(owner.model_copy(update={"needs_setup": True}))
    else:
        async with sessions() as session:
            await session.execute(delete(UserRow).where(UserRow.id == str(owner.id)))
            await session.commit()
    with pytest.raises(PermissionError):
        await resolve_batch_principal(batch, load_user=repo.get_user_by_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("original,current", [("user", "admin"), ("reviewer", "operator"), (None, "admin")])
async def test_role_changes_do_not_invent_a_role_hierarchy(accounts, original, current):
    repo, owner, _ = accounts
    await repo.update_system_role(str(owner.id), current)
    with pytest.raises(PermissionError):
        await resolve_batch_principal(_batch(str(owner.id), user_role=original), load_user=repo.get_user_by_id)


@pytest.mark.asyncio
async def test_unmapped_internal_owner_keeps_default_role_without_stale_claims(accounts):
    repo, _, _ = accounts
    batch = _batch("external-owner", is_internal=True, oauth_provider="old", oauth_id="old", authz_attributes={"admin": True})
    principal = await resolve_batch_principal(batch, load_user=repo.get_user_by_id)
    assert principal.user_id == "external-owner" and principal.is_internal
    assert principal.role is None and principal.oauth_provider is None and principal.oauth_id is None
    assert principal.attributes == {}
    batch["execution_spec"]["is_internal"] = False
    with pytest.raises(PermissionError):
        await resolve_batch_principal(batch, load_user=repo.get_user_by_id)


@pytest.mark.asyncio
async def test_auth_disabled_only_preserves_explicit_synthetic_owner(accounts, monkeypatch):
    repo, owner, _ = accounts
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    batch = _batch("default", user_role="admin")
    principal = await resolve_batch_principal(batch, load_user=repo.get_user_by_id)
    assert principal.user_id == "default" and principal.role == "admin"
    await repo.set_disabled(str(owner.id), True)
    with pytest.raises(PermissionError):
        await resolve_batch_principal(_batch(str(owner.id), user_role="admin"), load_user=repo.get_user_by_id)
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    with pytest.raises(PermissionError):
        await resolve_batch_principal(batch, load_user=repo.get_user_by_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_loader", "exception", "mismatch"])
async def test_unavailable_identity_fails_closed(accounts, failure):
    _, owner, _ = accounts

    async def load_user(user_id):
        if failure == "exception":
            raise RuntimeError("sensitive database connection details")
        return User(email="different@example.com", system_role="admin")

    with pytest.raises(PermissionError) as exc:
        await resolve_batch_principal(_batch(str(owner.id), user_role="admin", is_internal=True), load_user=None if failure == "missing_loader" else load_user)
    assert "sensitive" not in str(exc.value)
