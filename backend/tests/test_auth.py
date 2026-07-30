"""Tests for authentication module: JWT, password hashing, AuthContext, and authz decorators."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import bcrypt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.auth import create_access_token, decode_token, hash_password, verify_password
from app.gateway.auth.models import User
from app.gateway.auth.password import needs_rehash
from app.gateway.authz import (
    AuthContext,
    Permissions,
    get_auth_context,
    require_auth,
    require_permission,
)

# ── Password Hashing ────────────────────────────────────────────────────────


def test_hash_password_and_verify():
    """Hashing and verification round-trip."""
    password = "s3cr3tP@ssw0rd!"
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$dfv2$")
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_hash_password_different_each_time():
    """bcrypt generates unique salts, so same password has different hashes."""
    password = "testpassword"
    h1 = hash_password(password)
    h2 = hash_password(password)
    assert h1 != h2  # Different salts
    # But both verify correctly
    assert verify_password(password, h1) is True
    assert verify_password(password, h2) is True


def test_verify_password_rejects_empty():
    """Empty password should not verify."""
    hashed = hash_password("nonempty")
    assert verify_password("", hashed) is False


def test_hash_produces_v2_prefix():
    """hash_password output starts with $dfv2$."""
    hashed = hash_password("anypassword123")
    assert hashed.startswith("$dfv2$")


def test_verify_v1_prefixed_hash():
    """verify_password handles $dfv1$ prefixed hashes (plain bcrypt)."""
    password = "legacyP@ssw0rd"
    raw_bcrypt = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    v1_hash = f"$dfv1${raw_bcrypt}"
    assert verify_password(password, v1_hash) is True
    assert verify_password("wrong", v1_hash) is False


def test_verify_bare_bcrypt_hash():
    """verify_password handles bare bcrypt hashes (no prefix) as v1."""
    password = "oldstyleP@ss"
    raw_bcrypt = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    assert verify_password(password, raw_bcrypt) is True
    assert verify_password("wrong", raw_bcrypt) is False


def test_needs_rehash_returns_false_for_v2():
    """v2 hashes do not need rehashing."""
    hashed = hash_password("something")
    assert needs_rehash(hashed) is False


def test_needs_rehash_returns_true_for_v1():
    """v1-prefixed hashes need rehashing."""
    raw = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8")
    assert needs_rehash(f"$dfv1${raw}") is True


def test_needs_rehash_returns_true_for_bare_bcrypt():
    """Bare bcrypt hashes (no prefix) need rehashing."""
    raw = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8")
    assert needs_rehash(raw) is True


# ── JWT ─────────────────────────────────────────────────────────────────────


def test_create_and_decode_token():
    """JWT creation and decoding round-trip."""
    user_id = str(uuid4())
    # Set a valid JWT secret for this test
    import os

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(user_id)
    assert isinstance(token, str)

    payload = decode_token(token)
    assert payload is not None
    assert payload.sub == user_id


def test_decode_token_expired():
    """Expired token returns TokenError.EXPIRED."""
    from app.gateway.auth.errors import TokenError

    user_id = str(uuid4())
    # Create token that expires immediately
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    payload = decode_token(token)
    assert payload == TokenError.EXPIRED


def test_decode_token_invalid():
    """Invalid token returns TokenError."""
    from app.gateway.auth.errors import TokenError

    assert isinstance(decode_token("not.a.valid.token"), TokenError)
    assert isinstance(decode_token(""), TokenError)
    assert isinstance(decode_token("completely-wrong"), TokenError)


def test_create_token_custom_expiry():
    """Custom expiry is respected."""
    user_id = str(uuid4())
    token = create_access_token(user_id, expires_delta=timedelta(hours=1))
    payload = decode_token(token)
    assert payload is not None
    assert payload.sub == user_id


# ── AuthContext ────────────────────────────────────────────────────────────


def test_auth_context_unauthenticated():
    """AuthContext with no user."""
    ctx = AuthContext(user=None, permissions=[])
    assert ctx.is_authenticated is False
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_authenticated_no_perms():
    """AuthContext with user but no permissions."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[])
    assert ctx.is_authenticated is True
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_has_permission():
    """AuthContext permission checking."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    perms = [Permissions.THREADS_READ, Permissions.THREADS_WRITE]
    ctx = AuthContext(user=user, permissions=perms)
    assert ctx.has_permission("threads", "read") is True
    assert ctx.has_permission("threads", "write") is True
    assert ctx.has_permission("threads", "delete") is False
    assert ctx.has_permission("runs", "read") is False


def test_auth_context_require_user_raises():
    """require_user raises 401 when not authenticated."""
    ctx = AuthContext(user=None, permissions=[])
    with pytest.raises(HTTPException) as exc_info:
        ctx.require_user()
    assert exc_info.value.status_code == 401


def test_auth_context_require_user_returns_user():
    """require_user returns user when authenticated."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[])
    returned = ctx.require_user()
    assert returned == user


# ── get_auth_context helper ─────────────────────────────────────────────────


def test_get_auth_context_not_set():
    """get_auth_context returns None when auth not set on request."""
    mock_request = MagicMock()
    # Make getattr return None (simulating attribute not set)
    mock_request.state = MagicMock()
    del mock_request.state.auth
    assert get_auth_context(mock_request) is None


def test_get_auth_context_set():
    """get_auth_context returns the AuthContext from request."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[Permissions.THREADS_READ])

    mock_request = MagicMock()
    mock_request.state.auth = ctx

    assert get_auth_context(mock_request) == ctx


# ── require_auth decorator ──────────────────────────────────────────────────


def test_require_auth_sets_auth_context():
    """require_auth rejects unauthenticated requests with 401."""
    from fastapi import Request

    app = FastAPI()

    @app.get("/test")
    @require_auth
    async def endpoint(request: Request):
        ctx = get_auth_context(request)
        return {"authenticated": ctx.is_authenticated}

    with TestClient(app) as client:
        # No cookie → 401 (require_auth independently enforces authentication)
        response = client.get("/test")
        assert response.status_code == 401


def test_require_auth_requires_request_param():
    """require_auth raises ValueError if request parameter is missing."""
    import asyncio

    @require_auth
    async def bad_endpoint():  # Missing `request` parameter
        pass

    with pytest.raises(ValueError, match="require_auth decorator requires 'request' parameter"):
        asyncio.run(bad_endpoint())


# ── require_permission decorator ─────────────────────────────────────────────


def test_require_permission_requires_auth():
    """require_permission raises 401 when not authenticated."""
    from fastapi import Request

    app = FastAPI()

    @app.get("/test")
    @require_permission("threads", "read")
    async def endpoint(request: Request):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 401
        assert "Authentication required" in response.json()["detail"]


def test_require_permission_denies_wrong_permission():
    """User without required permission gets 403."""
    from fastapi import Request

    app = FastAPI()
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")

    @app.get("/test")
    @require_permission("threads", "delete")
    async def endpoint(request: Request):
        return {"ok": True}

    mock_auth = AuthContext(user=user, permissions=[Permissions.THREADS_READ])

    with patch("app.gateway.authz._authenticate", return_value=mock_auth):
        with TestClient(app) as client:
            response = client.get("/test")
            assert response.status_code == 403
            assert "Permission denied" in response.json()["detail"]


def _make_internal_owner_check_app():
    """App with an owner_check route and a thread owned by ``alice``."""
    import asyncio

    from fastapi import Request
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

    app = FastAPI()
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(thread_store.create("alice-thread", user_id="alice"))
    app.state.thread_store = thread_store

    @app.get("/threads/{thread_id}")
    @require_permission("threads", "read", owner_check=True)
    async def endpoint(thread_id: str, request: Request):
        return {"ok": True}

    return app


def _internal_auth_context() -> AuthContext:
    from types import SimpleNamespace

    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user = SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)
    return AuthContext(user=user, permissions=[Permissions.THREADS_READ])


def test_require_permission_internal_role_scoped_by_owner_header():
    """An internal caller acting for the thread owner passes the owner check."""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get(
                "/threads/alice-thread",
                headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "alice"},
            )
    assert response.status_code == 200


def test_require_permission_internal_role_denied_for_other_owner():
    """The internal token must not grant access to another user's thread."""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get(
                "/threads/alice-thread",
                headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "mallory"},
            )
    assert response.status_code == 404


def test_require_permission_internal_role_without_header_is_scoped_to_internal_user():
    """With no owner header, internal callers are scoped like before the bypass."""
    app = _make_internal_owner_check_app()
    with patch("app.gateway.authz._authenticate", return_value=_internal_auth_context()):
        with TestClient(app) as client:
            response = client.get("/threads/alice-thread")
    assert response.status_code == 404


# ── Weak JWT secret warning ──────────────────────────────────────────────────


# ── User Model Fields ──────────────────────────────────────────────────────


def test_user_model_has_needs_setup_default_false():
    """New users default to needs_setup=False."""
    user = User(email="test@example.com", password_hash="hash")
    assert user.needs_setup is False


def test_user_model_has_token_version_default_zero():
    """New users default to token_version=0."""
    user = User(email="test@example.com", password_hash="hash")
    assert user.token_version == 0


def test_user_model_needs_setup_true():
    """Auto-created admin has needs_setup=True."""
    user = User(email="admin@example.com", password_hash="hash", needs_setup=True)
    assert user.needs_setup is True


def test_sqlite_round_trip_new_fields():
    """needs_setup and token_version survive create → read round-trip.

    Uses the shared persistence engine (same one threads_meta, runs,
    run_events, and feedback use). The old separate .deer-flow/users.db
    file is gone.
    """
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import (
            close_engine,
            get_session_factory,
            init_engine,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"sqlite+aiosqlite:///{tmpdir}/scratch.db"
            await init_engine("sqlite", url=url, sqlite_dir=tmpdir)
            try:
                repo = SQLiteUserRepository(get_session_factory())
                user = User(
                    email="setup@test.com",
                    password_hash="fakehash",
                    system_role="admin",
                    needs_setup=True,
                    token_version=3,
                )
                created = await repo.create_user(user)
                assert created.needs_setup is True
                assert created.token_version == 3

                fetched = await repo.get_user_by_email("setup@test.com")
                assert fetched is not None
                assert fetched.needs_setup is True
                assert fetched.token_version == 3

                fetched.needs_setup = False
                fetched.token_version = 4
                await repo.update_user(fetched)
                refetched = await repo.get_user_by_id(str(fetched.id))
                assert refetched is not None
                assert refetched.needs_setup is False
                assert refetched.token_version == 4
            finally:
                await close_engine()

    asyncio.run(_run())


def test_update_user_raises_when_row_concurrently_deleted(tmp_path):
    """Concurrent-delete during update_user must hard-fail, not silently no-op.

    Earlier the SQLite repo returned the input unchanged when the row was
    missing, making a phantom success path that admin password reset
    callers (`reset_admin`, `_ensure_admin_user`) would happily log as
    'password reset'. The new contract: raise ``UserNotFoundError`` so
    a vanished row never looks like a successful update.
    """
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.base import UserNotFoundError
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import (
            close_engine,
            get_session_factory,
            init_engine,
        )
        from deerflow.persistence.user.model import UserRow

        with tempfile.TemporaryDirectory() as d:
            url = f"sqlite+aiosqlite:///{d}/scratch.db"
            await init_engine("sqlite", url=url, sqlite_dir=d)
            try:
                sf = get_session_factory()
                repo = SQLiteUserRepository(sf)
                user = User(
                    email="ghost@test.com",
                    password_hash="fakehash",
                    system_role="user",
                )
                created = await repo.create_user(user)

                # Simulate "row vanished underneath us" by deleting the row
                # via the raw ORM session, then attempt to update.
                async with sf() as session:
                    row = await session.get(UserRow, str(created.id))
                    assert row is not None
                    await session.delete(row)
                    await session.commit()

                created.needs_setup = True
                with pytest.raises(UserNotFoundError):
                    await repo.update_user(created)
            finally:
                await close_engine()

    asyncio.run(_run())


# ── Email case-insensitivity (account collision invariant) ──────────────────
#
# Regression coverage for the case-collision gap: local registration normalises
# email through ``EmailStr`` (lowercases only the domain) while OIDC lowercases
# the whole address, and the repo lookup used to be case-sensitive, so
# ``Victim@x.com`` and ``victim@x.com`` became two separate accounts — defeating
# the invariant that a local account blocks an SSO login on the same email
# (flagged on PR #3506, fixed there only OIDC-side). The repo now canonicalises
# to lowercase on write and matches case-insensitively on read.


def test_email_lookup_is_case_insensitive(tmp_path):
    """A user registered with mixed case resolves for any-case lookup."""
    import asyncio

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            repo = SQLiteUserRepository(get_session_factory())
            created = await repo.create_user(User(email="Victim@x.com", password_hash="h", system_role="user"))
            # Stored canonical (lowercase) and reflected back on the returned object.
            assert created.email == "victim@x.com"

            for variant in ("victim@x.com", "VICTIM@X.COM", "Victim@x.com"):
                found = await repo.get_user_by_email(variant)
                assert found is not None, f"lookup missed {variant!r}"
                assert str(found.id) == str(created.id)
        finally:
            await close_engine()

    asyncio.run(_run())


def test_create_user_rejects_email_differing_only_in_case(tmp_path):
    """The second case-variant registration collides on the canonical email."""
    import asyncio

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            repo = SQLiteUserRepository(get_session_factory())
            await repo.create_user(User(email="Victim@x.com", password_hash="h", system_role="user"))
            with pytest.raises(ValueError):
                await repo.create_user(User(email="victim@x.com", password_hash="h", system_role="user"))
            assert await repo.count_users() == 1
        finally:
            await close_engine()

    asyncio.run(_run())


def test_create_user_rejects_legacy_mixed_case_email(tmp_path):
    """Registration must not duplicate a mixed-case row created before normalization."""
    import asyncio
    from uuid import uuid4

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.user.model import UserRow

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            sf = get_session_factory()
            repo = SQLiteUserRepository(sf)
            async with sf() as session:
                session.add(
                    UserRow(
                        id=str(uuid4()),
                        email="Victim@x.com",
                        password_hash="h",
                        system_role="user",
                        needs_setup=False,
                        token_version=0,
                    )
                )
                await session.commit()

            with pytest.raises(ValueError, match="Email already registered"):
                await repo.create_user(User(email="victim@x.com", password_hash="h", system_role="user"))
            assert await repo.count_users() == 1
        finally:
            await close_engine()

    asyncio.run(_run())


def test_update_user_normalizes_email(tmp_path):
    """Changing an email through update_user stores the canonical lowercase form."""
    import asyncio

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            repo = SQLiteUserRepository(get_session_factory())
            user = await repo.create_user(User(email="user@x.com", password_hash="h", system_role="user"))
            user.email = "New@Mixed.COM"
            await repo.update_user(user)
            refetched = await repo.get_user_by_id(str(user.id))
            assert refetched is not None
            assert refetched.email == "new@mixed.com"
            assert await repo.get_user_by_email("NEW@MIXED.com") is not None
        finally:
            await close_engine()

    asyncio.run(_run())


def test_distinct_emails_remain_distinct(tmp_path):
    """Case-folding must not collapse genuinely different addresses."""
    import asyncio

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            repo = SQLiteUserRepository(get_session_factory())
            alice = await repo.create_user(User(email="alice@x.com", password_hash="h", system_role="user"))
            bob = await repo.create_user(User(email="bob@x.com", password_hash="h", system_role="user"))
            assert await repo.count_users() == 2
            fa = await repo.get_user_by_email("Alice@x.com")
            fb = await repo.get_user_by_email("BOB@x.com")
            assert fa is not None and str(fa.id) == str(alice.id)
            assert fb is not None and str(fb.id) == str(bob.id)
            assert str(fa.id) != str(fb.id)
        finally:
            await close_engine()

    asyncio.run(_run())


def test_legacy_mixed_case_duplicate_rows_resolve_without_error(tmp_path):
    """A pre-fix DB with two case-variant rows resolves to the oldest, never 500s.

    Migration-safety: existing installations may already hold ``Victim@x.com``
    and ``victim@x.com`` as separate rows. The case-insensitive lookup must not
    raise ``MultipleResultsFound``; it deterministically returns the oldest
    (most-established) account.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.user.model import UserRow

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            sf = get_session_factory()
            repo = SQLiteUserRepository(sf)
            older = datetime.now(UTC) - timedelta(days=5)
            newer = datetime.now(UTC)
            # Insert raw rows (bypassing create_user's normalisation) to mimic
            # data written before this fix.
            async with sf() as session:
                session.add(UserRow(id=str(uuid4()), email="Victim@x.com", password_hash="h", system_role="user", created_at=older, needs_setup=False, token_version=0))
                session.add(UserRow(id=str(uuid4()), email="victim@x.com", password_hash="h", system_role="user", created_at=newer, needs_setup=False, token_version=0))
                await session.commit()

            found = await repo.get_user_by_email("VICTIM@X.COM")
            assert found is not None
            assert found.email == "Victim@x.com"  # oldest wins, deterministically
        finally:
            await close_engine()

    asyncio.run(_run())


def test_update_user_on_legacy_mixed_case_row_does_not_collide(tmp_path):
    """A password-only update on a legacy mixed-case row must not 500.

    Migration-safety, write side. A pre-fix DB may already hold two rows
    differing only in case (``Victim@x.com`` + ``victim@x.com``). A password
    change or admin reset reloads the row and calls ``update_user`` with the
    email unchanged. ``update_user`` must not opportunistically re-lowercase the
    mixed-case email, because that collides with the already-canonical row's
    unique email and raises ``IntegrityError`` — which surfaces as a 500 on the
    change-password / reset-admin paths that don't catch it. The read path was
    hardened for this legacy state; the write path must match, so only a genuine
    email change (differing case-insensitively from the stored value) rewrites
    the column.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    async def _run() -> None:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.user.model import UserRow

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            sf = get_session_factory()
            repo = SQLiteUserRepository(sf)
            mixed_id = str(uuid4())
            canonical_id = str(uuid4())
            older = datetime.now(UTC) - timedelta(days=5)
            newer = datetime.now(UTC)
            # Raw rows written before the fix (the mixed-case row is the oldest).
            async with sf() as session:
                session.add(UserRow(id=mixed_id, email="Victim@x.com", password_hash="old-hash", system_role="user", created_at=older, needs_setup=False, token_version=0))
                session.add(UserRow(id=canonical_id, email="victim@x.com", password_hash="canonical-hash", system_role="user", created_at=newer, needs_setup=False, token_version=0))
                await session.commit()

            # Simulate a password change on the mixed-case row: reload it, keep
            # the email as-stored, set a new hash + bump the token version.
            mixed = await repo.get_user_by_id(mixed_id)
            assert mixed is not None
            assert mixed.email == "Victim@x.com"
            mixed.password_hash = "new-hash-after-change"
            mixed.token_version += 1

            # Must not raise IntegrityError even though lowercasing the email
            # would collide with the canonical row's unique email.
            await repo.update_user(mixed)

            # The mixed-case row kept its stored casing and took the new password.
            refetched = await repo.get_user_by_id(mixed_id)
            assert refetched is not None
            assert refetched.email == "Victim@x.com"
            assert refetched.password_hash == "new-hash-after-change"
            assert refetched.token_version == 1

            # The canonical row is untouched, and no row was lost or merged.
            canonical = await repo.get_user_by_id(canonical_id)
            assert canonical is not None
            assert canonical.email == "victim@x.com"
            assert canonical.password_hash == "canonical-hash"
            assert await repo.count_users() == 2

            # Case-insensitive lookup still resolves the mixed-case row (oldest wins).
            found = await repo.get_user_by_email("VICTIM@X.COM")
            assert found is not None
            assert str(found.id) == mixed_id
        finally:
            await close_engine()

    asyncio.run(_run())


def test_oidc_login_blocked_by_existing_local_account_across_case(tmp_path):
    """End-to-end invariant: an SSO login cannot create a duplicate of a local
    account whose email differs only in case.

    Uses the real repository + provider + provisioning (no mocks), so it covers
    the cross-path gap the mock-based OIDC tests could not: local registration
    keeps the local-part case (``Victim@x.com``) while OIDC lowercases the whole
    address (``victim@x.com``).
    """
    import asyncio

    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
    from deerflow.config.auth_config import OIDCProviderConfig

    async def _run() -> None:
        from fastapi import HTTPException

        from app.gateway.auth.oidc import OIDCIdentity
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path}/scratch.db"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            provider = LocalAuthProvider(SQLiteUserRepository(get_session_factory()))
            await provider.create_user(email="Victim@x.com", password="pw-abc-123!", system_role="user")

            cfg = OIDCProviderConfig(display_name="Test SSO", issuer="https://issuer.example.com", client_id="deer-flow", auto_create_users=True)
            identity = OIDCIdentity(provider="keycloak", subject="sub-1", email="Victim@x.com", email_verified=True, name="Victim", claims={})

            with pytest.raises(HTTPException) as exc_info:
                await get_or_provision_oidc_user(provider_id="keycloak", provider_config=cfg, identity=identity, local_provider=provider)

            assert exc_info.value.status_code == 409
            # No duplicate auto-created — the local account still owns the email.
            assert await provider.count_users() == 1
        finally:
            await close_engine()

    asyncio.run(_run())


# ── Token Versioning ───────────────────────────────────────────────────────


def test_jwt_encodes_ver():
    """JWT payload includes ver field."""
    import os

    from app.gateway.auth.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()), token_version=3)
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 3


def test_jwt_default_ver_zero():
    """JWT ver defaults to 0."""
    import os

    from app.gateway.auth.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()))
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 0


def test_token_version_mismatch_rejects():
    """Token with stale ver is rejected by get_current_user_from_request."""
    import asyncio
    import os

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"

    user_id = str(uuid4())
    token = create_access_token(user_id, token_version=0)

    mock_user = User(id=user_id, email="test@example.com", password_hash="hash", token_version=1)

    mock_request = MagicMock()
    mock_request.cookies = {"access_token": token}

    with patch("app.gateway.deps.get_local_provider") as mock_provider_fn:
        mock_provider = MagicMock()
        mock_provider.get_user = AsyncMock(return_value=mock_user)
        mock_provider_fn.return_value = mock_provider

        from app.gateway.deps import get_current_user_from_request

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_user_from_request(mock_request))
        assert exc_info.value.status_code == 401
        assert "revoked" in str(exc_info.value.detail).lower()


# ── change-password extension ──────────────────────────────────────────────


def test_change_password_request_accepts_new_email():
    """ChangePasswordRequest model accepts optional new_email."""
    from app.gateway.routers.auth import ChangePasswordRequest

    req = ChangePasswordRequest(
        current_password="old",
        new_password="newpassword",
        new_email="new@example.com",
    )
    assert req.new_email == "new@example.com"


def test_change_password_request_new_email_optional():
    """ChangePasswordRequest model works without new_email."""
    from app.gateway.routers.auth import ChangePasswordRequest

    req = ChangePasswordRequest(current_password="old", new_password="newpassword")
    assert req.new_email is None


def test_login_response_includes_needs_setup():
    """LoginResponse includes needs_setup field."""
    from app.gateway.routers.auth import LoginResponse

    resp = LoginResponse(expires_in=3600, needs_setup=True)
    assert resp.needs_setup is True
    resp2 = LoginResponse(expires_in=3600)
    assert resp2.needs_setup is False


# ── Rate Limiting ──────────────────────────────────────────────────────────


def test_rate_limiter_allows_under_limit():
    """Requests under the limit are allowed."""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts

    _login_attempts.clear()
    _check_rate_limit("192.168.1.1")  # Should not raise


def test_rate_limiter_blocks_after_max_failures():
    """IP is blocked after 5 consecutive failures."""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts, _record_login_failure

    _login_attempts.clear()
    ip = "10.0.0.1"
    for _ in range(5):
        _record_login_failure(ip)
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(ip)
    assert exc_info.value.status_code == 429


def test_rate_limiter_resets_on_success():
    """Successful login clears the failure counter."""
    from app.gateway.routers.auth import _check_rate_limit, _login_attempts, _record_login_failure, _record_login_success

    _login_attempts.clear()
    ip = "10.0.0.2"
    for _ in range(4):
        _record_login_failure(ip)
    _record_login_success(ip)
    _check_rate_limit(ip)  # Should not raise


# ── Client IP extraction ─────────────────────────────────────────────────


def test_get_client_ip_direct_connection_no_proxy(monkeypatch):
    """Direct mode (no AUTH_TRUSTED_PROXIES): use TCP peer regardless of X-Real-IP."""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "203.0.113.42"
    req.headers = {}
    assert _get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_x_real_ip_ignored_when_no_trusted_proxy(monkeypatch):
    """X-Real-IP is silently ignored if AUTH_TRUSTED_PROXIES is unset.

    This closes the bypass where any client could rotate X-Real-IP per
    request to dodge per-IP rate limits in dev / direct mode.
    """
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_x_real_ip_honored_from_trusted_proxy(monkeypatch):
    """X-Real-IP is honored when the TCP peer matches AUTH_TRUSTED_PROXIES."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"  # in trusted CIDR
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_x_real_ip_rejected_from_untrusted_peer(monkeypatch):
    """X-Real-IP is rejected when the TCP peer is NOT in the trusted list."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "8.8.8.8"  # NOT in trusted CIDR
    req.headers = {"x-real-ip": "203.0.113.42"}  # client trying to spoof
    assert _get_client_ip(req) == "8.8.8.8"


def test_get_client_ip_xff_never_honored(monkeypatch):
    """X-Forwarded-For is never used; only X-Real-IP from a trusted peer."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers = {"x-forwarded-for": "198.51.100.5"}  # no x-real-ip
    assert _get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_invalid_trusted_proxy_entry_skipped(monkeypatch, caplog):
    """Garbage entries in AUTH_TRUSTED_PROXIES are warned and skipped."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "not-an-ip,10.0.0.0/8")
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"  # valid entry still works


def test_get_client_ip_no_client_returns_unknown(monkeypatch):
    """No request.client → 'unknown' marker (no crash)."""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.gateway.routers.auth import _get_client_ip

    req = MagicMock()
    req.client = None
    req.headers = {}
    assert _get_client_ip(req) == "unknown"


# ── Common-password blocklist ────────────────────────────────────────────────


def test_register_rejects_literal_password():
    """Pydantic validator rejects 'password' as a registration password."""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="password")
    assert "too common" in str(exc.value)


def test_register_rejects_common_password_case_insensitive():
    """Case variants of common passwords are also rejected."""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    for variant in ["PASSWORD", "Password1", "qwerty123", "letmein1"]:
        with pytest.raises(ValidationError):
            RegisterRequest(email="x@example.com", password=variant)


def test_register_accepts_strong_password():
    """A non-blocklisted password of length >=8 is accepted."""
    from app.gateway.routers.auth import RegisterRequest

    req = RegisterRequest(email="x@example.com", password="Tr0ub4dor&3-Horse")
    assert req.password == "Tr0ub4dor&3-Horse"


def test_change_password_rejects_common_password():
    """The same blocklist applies to change-password."""
    from pydantic import ValidationError

    from app.gateway.routers.auth import ChangePasswordRequest

    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="anything", new_password="iloveyou")


def test_password_blocklist_keeps_short_passwords_for_length_check():
    """Short passwords still fail the min_length check (not the blocklist)."""
    from pydantic import ValidationError

    from app.gateway.routers.auth import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="abc")
    # the length check should fire, not the blocklist
    assert "at least 8 characters" in str(exc.value)


# ── Weak JWT secret warning ──────────────────────────────────────────────────


def test_missing_jwt_secret_generates_ephemeral(monkeypatch, caplog):
    """get_auth_config() auto-generates an ephemeral secret when AUTH_JWT_SECRET is unset."""
    import logging

    import app.gateway.auth.config as config_module

    config_module._auth_config = None
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with caplog.at_level(logging.WARNING):
        config = config_module.get_auth_config()

    assert config.jwt_secret  # non-empty ephemeral secret
    assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)

    # Cleanup
    config_module._auth_config = None


# ── Auto-rehash on login ──────────────────────────────────────────────────


def test_authenticate_auto_rehashes_legacy_hash():
    """authenticate() upgrades a bare bcrypt hash to v2 on successful login."""
    import asyncio

    from app.gateway.auth.local_provider import LocalAuthProvider

    password = "rehashTest123"

    user = User(
        id=uuid4(),
        email="rehash@test.com",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
    )

    mock_repo = MagicMock()
    mock_repo.get_user_by_email = AsyncMock(return_value=user)
    mock_repo.update_user = AsyncMock(return_value=user)

    provider = LocalAuthProvider(mock_repo)

    result = asyncio.run(provider.authenticate({"email": "rehash@test.com", "password": password}))
    assert result is not None
    assert result.password_hash.startswith("$dfv2$")
    mock_repo.update_user.assert_called_once()


def test_authenticate_skips_rehash_for_v2_hash():
    """authenticate() does NOT rehash when the stored hash is already v2."""
    import asyncio

    from app.gateway.auth.local_provider import LocalAuthProvider

    password = "alreadyv2Pass!"

    user = User(
        id=uuid4(),
        email="v2@test.com",
        password_hash=hash_password(password),
    )

    mock_repo = MagicMock()
    mock_repo.get_user_by_email = AsyncMock(return_value=user)
    mock_repo.update_user = AsyncMock(return_value=user)

    provider = LocalAuthProvider(mock_repo)

    result = asyncio.run(provider.authenticate({"email": "v2@test.com", "password": password}))
    assert result is not None
    mock_repo.update_user.assert_not_called()


def test_validate_next_param_rejects_colon_paths():
    from app.gateway.routers.auth import validate_next_param

    assert validate_next_param("/workspace") == "/workspace"
    assert validate_next_param("/:evil") is None
