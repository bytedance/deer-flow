"""Tests for authentication module: JWT, password hashing, and auth context behavior."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.plugins.auth.authorization import (
    AuthContext,
    Permissions,
    get_auth_context,
)
from app.plugins.auth.authorization.hooks import build_authz_hooks
from app.plugins.auth.domain import create_access_token, decode_token, hash_password, verify_password
from app.plugins.auth.domain.models import User
from store.persistence import MappedBase

# ── Password Hashing ────────────────────────────────────────────────────────


def test_hash_password_and_verify():
    """Hashing and verification round-trip."""
    password = "s3cr3tP@ssw0rd!"
    hashed = hash_password(password)
    assert hashed != password
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
    from app.plugins.auth.domain.errors import TokenError

    user_id = str(uuid4())
    # Create token that expires immediately
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    payload = decode_token(token)
    assert payload == TokenError.EXPIRED


def test_decode_token_invalid():
    """Invalid token returns TokenError."""
    from app.plugins.auth.domain.errors import TokenError

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
    assert ctx.principal_id is None
    assert ctx.capabilities == ()
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_authenticated_no_perms():
    """AuthContext with user but no permissions."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    ctx = AuthContext(user=user, permissions=[])
    assert ctx.is_authenticated is True
    assert ctx.principal_id == str(user.id)
    assert ctx.capabilities == ()
    assert ctx.has_permission("threads", "read") is False


def test_auth_context_has_permission():
    """AuthContext permission checking."""
    user = User(id=uuid4(), email="test@example.com", password_hash="hash")
    perms = [Permissions.THREADS_READ, Permissions.THREADS_WRITE]
    ctx = AuthContext(user=user, permissions=perms)
    assert ctx.capabilities == tuple(perms)
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


def test_register_app_sets_default_authz_hooks():
    from app.gateway.registrar import register_app

    app = register_app()

    assert app.state.authz_hooks == build_authz_hooks()


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

    from app.plugins.auth.storage import DbUserRepository, UserCreate

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmpdir}/scratch.db", future=True)
            async with engine.begin() as conn:
                await conn.run_sync(MappedBase.metadata.create_all)
            session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
            try:
                async with session_factory() as session:
                    repo = DbUserRepository(session)
                    created = await repo.create_user(
                        UserCreate(
                            email="setup@test.com",
                            password_hash="fakehash",
                            system_role="admin",
                            needs_setup=True,
                            token_version=3,
                        )
                    )
                    await session.commit()
                assert created.needs_setup is True
                assert created.token_version == 3

                async with session_factory() as session:
                    repo = DbUserRepository(session)
                    fetched = await repo.get_user_by_email("setup@test.com")
                assert fetched is not None
                assert fetched.needs_setup is True
                assert fetched.token_version == 3

                updated = fetched.model_copy(update={"needs_setup": False, "token_version": 4})
                async with session_factory() as session:
                    repo = DbUserRepository(session)
                    await repo.update_user(updated)
                    await session.commit()
                async with session_factory() as session:
                    repo = DbUserRepository(session)
                    refetched = await repo.get_user_by_id(fetched.id)
                assert refetched is not None
                assert refetched.needs_setup is False
                assert refetched.token_version == 4
            finally:
                await engine.dispose()

    asyncio.run(_run())


def test_update_user_raises_when_row_concurrently_deleted(tmp_path):
    """Concurrent-delete during update_user must hard-fail, not silently no-op.

    Earlier the SQLite repo returned the input unchanged when the row was
    missing, making a phantom success path that admin password reset
    callers (`reset_admin`, `_ensure_admin_user`) would happily log as
    'password reset'. The new contract: raise ``LookupError`` so
    a vanished row never looks like a successful update.
    """
    import asyncio
    import tempfile

    from app.plugins.auth.storage import DbUserRepository, UserCreate

    async def _run() -> None:
        from app.plugins.auth.storage.models import User as UserModel

        with tempfile.TemporaryDirectory() as d:
            engine = create_async_engine(f"sqlite+aiosqlite:///{d}/scratch.db", future=True)
            async with engine.begin() as conn:
                await conn.run_sync(MappedBase.metadata.create_all)
            sf = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
            try:
                async with sf() as session:
                    repo = DbUserRepository(session)
                    created = await repo.create_user(
                        UserCreate(
                            email="ghost@test.com",
                            password_hash="fakehash",
                            system_role="user",
                        )
                    )
                    await session.commit()

                # Simulate "row vanished underneath us" by deleting the row
                # via the raw ORM session, then attempt to update.
                async with sf() as session:
                    row = await session.get(UserModel, created.id)
                    assert row is not None
                    await session.delete(row)
                    await session.commit()

                updated = created.model_copy(update={"needs_setup": True})
                async with sf() as session:
                    repo = DbUserRepository(session)
                    with pytest.raises(LookupError):
                        await repo.update_user(updated)
            finally:
                await engine.dispose()

    asyncio.run(_run())


# ── Token Versioning ───────────────────────────────────────────────────────


def test_jwt_encodes_ver():
    """JWT payload includes ver field."""
    import os

    from app.plugins.auth.domain.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()), token_version=3)
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 3


def test_jwt_default_ver_zero():
    """JWT ver defaults to 0."""
    import os

    from app.plugins.auth.domain.errors import TokenError

    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"
    token = create_access_token(str(uuid4()))
    payload = decode_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.ver == 0


def test_token_version_mismatch_rejects():
    """Token with stale ver is rejected by get_current_user_from_request."""
    import os
    from types import SimpleNamespace

    from app.plugins.auth.security.dependencies import get_current_user_from_request
    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-for-jwt-testing-minimum-32-chars"

    user_id = str(uuid4())
    token = create_access_token(user_id, token_version=0)
    request = SimpleNamespace(
        cookies={"access_token": token},
        state=SimpleNamespace(
            _auth_session=MagicMock(),
        ),
    )
    stale_user = User(id=user_id, email="test@example.com", password_hash="hash", token_version=1)
    request.state._auth_session.__aenter__ = AsyncMock(return_value=request.state._auth_session)
    request.state._auth_session.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.plugins.auth.security.dependencies.DbUserRepository.get_user_by_id",
        new=AsyncMock(return_value=stale_user),
    ):
        with pytest.raises(HTTPException) as exc_info:
            import asyncio

            asyncio.run(get_current_user_from_request(request))
    assert exc_info.value.status_code == 401
    assert "revoked" in str(exc_info.value.detail).lower()


# ── change-password extension ──────────────────────────────────────────────


def test_change_password_request_accepts_new_email():
    """ChangePasswordRequest model accepts optional new_email."""
    from app.plugins.auth.api.schemas import ChangePasswordRequest

    req = ChangePasswordRequest(
        current_password="old",
        new_password="newpassword",
        new_email="new@example.com",
    )
    assert req.new_email == "new@example.com"


def test_change_password_request_new_email_optional():
    """ChangePasswordRequest model works without new_email."""
    from app.plugins.auth.api.schemas import ChangePasswordRequest

    req = ChangePasswordRequest(current_password="old", new_password="newpassword")
    assert req.new_email is None


def test_login_response_includes_needs_setup():
    """LoginResponse includes needs_setup field."""
    from app.plugins.auth.api.schemas import LoginResponse

    resp = LoginResponse(expires_in=3600, needs_setup=True)
    assert resp.needs_setup is True
    resp2 = LoginResponse(expires_in=3600)
    assert resp2.needs_setup is False


# ── Rate Limiting ──────────────────────────────────────────────────────────


def test_rate_limiter_allows_under_limit():
    """Requests under the limit are allowed."""
    from app.plugins.auth.api.schemas import _check_rate_limit, _login_attempts

    _login_attempts.clear()
    _check_rate_limit("192.168.1.1")  # Should not raise


def test_rate_limiter_blocks_after_max_failures():
    """IP is blocked after 5 consecutive failures."""
    from app.plugins.auth.api.schemas import _check_rate_limit, _login_attempts, _record_login_failure

    _login_attempts.clear()
    ip = "10.0.0.1"
    for _ in range(5):
        _record_login_failure(ip)
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(ip)
    assert exc_info.value.status_code == 429


def test_rate_limiter_resets_on_success():
    """Successful login clears the failure counter."""
    from app.plugins.auth.api.schemas import _check_rate_limit, _login_attempts, _record_login_failure, _record_login_success

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
    from app.plugins.auth.api.schemas import _get_client_ip

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
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_x_real_ip_honored_from_trusted_proxy(monkeypatch):
    """X-Real-IP is honored when the TCP peer matches AUTH_TRUSTED_PROXIES."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"  # in trusted CIDR
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_x_real_ip_rejected_from_untrusted_peer(monkeypatch):
    """X-Real-IP is rejected when the TCP peer is NOT in the trusted list."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client.host = "8.8.8.8"  # NOT in trusted CIDR
    req.headers = {"x-real-ip": "203.0.113.42"}  # client trying to spoof
    assert _get_client_ip(req) == "8.8.8.8"


def test_get_client_ip_xff_never_honored(monkeypatch):
    """X-Forwarded-For is never used; only X-Real-IP from a trusted peer."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client.host = "10.0.0.1"
    req.headers = {"x-forwarded-for": "198.51.100.5"}  # no x-real-ip
    assert _get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_invalid_trusted_proxy_entry_skipped(monkeypatch, caplog):
    """Garbage entries in AUTH_TRUSTED_PROXIES are warned and skipped."""
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "not-an-ip,10.0.0.0/8")
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client.host = "10.5.6.7"
    req.headers = {"x-real-ip": "203.0.113.42"}
    assert _get_client_ip(req) == "203.0.113.42"  # valid entry still works


def test_get_client_ip_no_client_returns_unknown(monkeypatch):
    """No request.client → 'unknown' marker (no crash)."""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    from app.plugins.auth.api.schemas import _get_client_ip

    req = MagicMock()
    req.client = None
    req.headers = {}
    assert _get_client_ip(req) == "unknown"


# ── Common-password blocklist ────────────────────────────────────────────────


def test_register_rejects_literal_password():
    """Pydantic validator rejects 'password' as a registration password."""
    from pydantic import ValidationError

    from app.plugins.auth.api.schemas import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="password")
    assert "too common" in str(exc.value)


def test_register_rejects_common_password_case_insensitive():
    """Case variants of common passwords are also rejected."""
    from pydantic import ValidationError

    from app.plugins.auth.api.schemas import RegisterRequest

    for variant in ["PASSWORD", "Password1", "qwerty123", "letmein1"]:
        with pytest.raises(ValidationError):
            RegisterRequest(email="x@example.com", password=variant)


def test_register_accepts_strong_password():
    """A non-blocklisted password of length >=8 is accepted."""
    from app.plugins.auth.api.schemas import RegisterRequest

    req = RegisterRequest(email="x@example.com", password="Tr0ub4dor&3-Horse")
    assert req.password == "Tr0ub4dor&3-Horse"


def test_change_password_rejects_common_password():
    """The same blocklist applies to change-password."""
    from pydantic import ValidationError

    from app.plugins.auth.api.schemas import ChangePasswordRequest

    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="anything", new_password="iloveyou")


def test_password_blocklist_keeps_short_passwords_for_length_check():
    """Short passwords still fail the min_length check (not the blocklist)."""
    from pydantic import ValidationError

    from app.plugins.auth.api.schemas import RegisterRequest

    with pytest.raises(ValidationError) as exc:
        RegisterRequest(email="x@example.com", password="abc")
    # the length check should fire, not the blocklist
    assert "at least 8 characters" in str(exc.value)


# ── Weak JWT secret warning ──────────────────────────────────────────────────


def test_missing_jwt_secret_generates_ephemeral(monkeypatch, caplog):
    """get_auth_config() auto-generates an ephemeral secret when AUTH_JWT_SECRET is unset."""
    import logging

    import app.plugins.auth.runtime.config_state as config_module
    from app.plugins.auth.runtime.config_state import reset_auth_config

    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with caplog.at_level(logging.WARNING):
        reset_auth_config()
        config = config_module.get_auth_config()

    assert config.jwt_secret  # non-empty ephemeral secret
    assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)

    # Cleanup
    reset_auth_config()
