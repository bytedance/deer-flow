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

    from deerflow.config.auth_config import load_auth_config_from_dict

    load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret-key-for-jwt-testing-minimum-32-chars"})

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

    from deerflow.config.auth_config import load_auth_config_from_dict

    load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret-key-for-jwt-testing-minimum-32-chars"})

    app = FastAPI()

    @app.get("/test")
    @require_permission("threads", "read")
    async def endpoint(request: Request):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 401
        assert "Authentication required" in str(response.json()["detail"])


def test_require_permission_denies_wrong_permission():
    """User without required permission gets 403."""
    from fastapi import Request

    from deerflow.config.auth_config import load_auth_config_from_dict

    load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret-key-for-jwt-testing-minimum-32-chars"})

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
            assert "Permission denied" in str(response.json()["detail"])


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
                    system_role="superadmin",
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
    from deerflow.config.auth_config import load_auth_config_from_dict

    load_auth_config_from_dict({"enabled": True, "provider": "local", "jwt_secret": "test-secret-key-for-jwt-testing-minimum-32-chars"})

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

# ── Weak JWT secret warning ──────────────────────────────────────────────────


def test_missing_jwt_secret_generates_ephemeral(monkeypatch, caplog, tmp_path):
    """get_auth_config() auto-generates an ephemeral secret when AUTH_JWT_SECRET is unset and no persisted file exists."""
    import logging

    import app.gateway.auth.config as config_module

    config_module._auth_config = None
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    # Patch the secret file path to a non-existent location to test first-boot behavior
    nonexistent = str(tmp_path / "nonexistent" / "jwt_secret")
    monkeypatch.setattr(config_module, "_jwt_secret_file", lambda: nonexistent)

    with caplog.at_level(logging.WARNING):
        config = config_module.get_auth_config()

    assert config.jwt_secret  # non-empty ephemeral secret
    assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)

    # Cleanup
    config_module._auth_config = None


def test_jwt_secret_loads_from_persisted_file(monkeypatch, caplog, tmp_path):
    """get_auth_config() loads the secret from persisted file when it exists."""
    import logging

    import app.gateway.auth.config as config_module

    # Create a persisted secret file
    secret_file = tmp_path / "jwt_secret"
    secret_file.write_text("persisted-secret-value")

    config_module._auth_config = None
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    monkeypatch.setattr(config_module, "_jwt_secret_file", lambda: str(secret_file))

    with caplog.at_level(logging.INFO):
        config = config_module.get_auth_config()

    assert config.jwt_secret == "persisted-secret-value"
    assert any("Loaded persisted JWT secret" in msg for msg in caplog.messages)

    # Cleanup
    config_module._auth_config = None
