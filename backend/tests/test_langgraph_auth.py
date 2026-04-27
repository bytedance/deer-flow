"""Tests for LangGraph Server auth handler (langgraph_auth.py).

Validates that the LangGraph auth layer enforces the same rules as Gateway:
  cookie → JWT decode → DB lookup → token_version check → owner filter
"""

import asyncio
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-langgraph-auth-testing-min-32")

from langgraph_sdk import Auth

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.jwt import create_access_token, decode_token
from app.gateway.auth.models import User
from app.gateway.langgraph_auth import add_owner_filter, authenticate

# ── Helpers ───────────────────────────────────────────────────────────────

_JWT_SECRET = "test-secret-key-for-langgraph-auth-testing-min-32"


@pytest.fixture(autouse=True)
def _setup_auth_config():
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    yield
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))


def _req(cookies=None, method="GET", headers=None):
    return SimpleNamespace(cookies=cookies or {}, method=method, headers=headers or {})


def _user(user_id=None, token_version=0):
    return User(email="test@example.com", password_hash="fakehash", system_role="user", id=user_id or uuid4(), token_version=token_version)


def _mock_provider(user=None):
    p = AsyncMock()
    p.get_user = AsyncMock(return_value=user)
    return p


# ── @auth.authenticate ───────────────────────────────────────────────────


def test_no_cookie_raises_401():
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req()))
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


def test_invalid_jwt_raises_401():
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req({"access_token": "garbage"})))
    assert exc.value.status_code == 401
    assert "Invalid token" in str(exc.value.detail)


def test_expired_jwt_raises_401():
    token = create_access_token("user-1", expires_delta=timedelta(seconds=-1))
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req({"access_token": token})))
    assert exc.value.status_code == 401


def test_user_not_found_raises_401():
    token = create_access_token("ghost")
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(None)):
        with pytest.raises(Auth.exceptions.HTTPException) as exc:
            asyncio.run(authenticate(_req({"access_token": token})))
        assert exc.value.status_code == 401
        assert "User not found" in str(exc.value.detail)


def test_token_version_mismatch_raises_401():
    user = _user(token_version=2)
    token = create_access_token(str(user.id), token_version=1)
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(user)):
        with pytest.raises(Auth.exceptions.HTTPException) as exc:
            asyncio.run(authenticate(_req({"access_token": token})))
        assert exc.value.status_code == 401
        assert "revoked" in str(exc.value.detail).lower()


def test_valid_token_returns_user_id():
    user = _user(token_version=0)
    token = create_access_token(str(user.id), token_version=0)
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(user)):
        result = asyncio.run(authenticate(_req({"access_token": token})))
    assert result == str(user.id)


def test_valid_token_matching_version():
    user = _user(token_version=5)
    token = create_access_token(str(user.id), token_version=5)
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(user)):
        result = asyncio.run(authenticate(_req({"access_token": token})))
    assert result == str(user.id)


# ── @auth.authenticate edge cases ────────────────────────────────────────


def test_provider_exception_propagates():
    """Provider raises → should not be swallowed silently."""
    token = create_access_token("user-1")
    p = AsyncMock()
    p.get_user = AsyncMock(side_effect=RuntimeError("DB down"))
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=p):
        with pytest.raises(RuntimeError, match="DB down"):
            asyncio.run(authenticate(_req({"access_token": token})))


def test_jwt_missing_ver_defaults_to_zero():
    """JWT without 'ver' claim → decoded as ver=0, matches user with token_version=0."""
    import jwt as pyjwt

    uid = str(uuid4())
    raw = pyjwt.encode({"sub": uid, "exp": 9999999999, "iat": 1000000000}, _JWT_SECRET, algorithm="HS256")
    user = _user(user_id=uid, token_version=0)
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(user)):
        result = asyncio.run(authenticate(_req({"access_token": raw})))
    assert result == uid


def test_jwt_missing_ver_rejected_when_user_version_nonzero():
    """JWT without 'ver' (defaults 0) vs user with token_version=1 → 401."""
    import jwt as pyjwt

    uid = str(uuid4())
    raw = pyjwt.encode({"sub": uid, "exp": 9999999999, "iat": 1000000000}, _JWT_SECRET, algorithm="HS256")
    user = _user(user_id=uid, token_version=1)
    with patch("app.gateway.langgraph_auth.get_local_provider", return_value=_mock_provider(user)):
        with pytest.raises(Auth.exceptions.HTTPException) as exc:
            asyncio.run(authenticate(_req({"access_token": raw})))
        assert exc.value.status_code == 401


def test_wrong_secret_raises_401():
    """Token signed with different secret → 401."""
    import jwt as pyjwt

    raw = pyjwt.encode({"sub": "user-1", "exp": 9999999999, "ver": 0}, "wrong-secret-that-is-long-enough-32chars!", algorithm="HS256")
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req({"access_token": raw})))
    assert exc.value.status_code == 401


# ── @auth.on (owner filter) ──────────────────────────────────────────────


class _FakeUser:
    """Minimal BaseUser-compatible object without langgraph_api.config dependency."""

    def __init__(self, identity: str):
        self.identity = identity
        self.is_authenticated = True
        self.display_name = identity


def _make_ctx(user_id):
    return Auth.types.AuthContext(resource="threads", action="create", user=_FakeUser(user_id), permissions=[])


def test_filter_injects_user_id():
    value = {}
    asyncio.run(add_owner_filter(_make_ctx("user-a"), value))
    assert value["metadata"]["user_id"] == "user-a"


def test_filter_preserves_existing_metadata():
    value = {"metadata": {"title": "hello"}}
    asyncio.run(add_owner_filter(_make_ctx("user-a"), value))
    assert value["metadata"]["user_id"] == "user-a"
    assert value["metadata"]["title"] == "hello"


def test_filter_returns_user_id_dict():
    result = asyncio.run(add_owner_filter(_make_ctx("user-x"), {}))
    assert result == {"user_id": "user-x"}


def test_filter_read_write_consistency():
    value = {}
    filter_dict = asyncio.run(add_owner_filter(_make_ctx("user-1"), value))
    assert value["metadata"]["user_id"] == filter_dict["user_id"]


def test_different_users_different_filters():
    f_a = asyncio.run(add_owner_filter(_make_ctx("a"), {}))
    f_b = asyncio.run(add_owner_filter(_make_ctx("b"), {}))
    assert f_a["user_id"] != f_b["user_id"]


def test_filter_overrides_conflicting_user_id():
    """If value already has a different user_id in metadata, it gets overwritten."""
    value = {"metadata": {"user_id": "attacker"}}
    asyncio.run(add_owner_filter(_make_ctx("real-owner"), value))
    assert value["metadata"]["user_id"] == "real-owner"


def test_filter_with_empty_metadata():
    """Explicit empty metadata dict is fine."""
    value = {"metadata": {}}
    result = asyncio.run(add_owner_filter(_make_ctx("user-z"), value))
    assert value["metadata"]["user_id"] == "user-z"
    assert result == {"user_id": "user-z"}


# ── Gateway parity ───────────────────────────────────────────────────────


def test_shared_jwt_secret():
    token = create_access_token("user-1", token_version=3)
    payload = decode_token(token)
    from app.gateway.auth.errors import TokenError

    assert not isinstance(payload, TokenError)
    assert payload.sub == "user-1"
    assert payload.ver == 3


def test_langgraph_json_has_auth_path():
    import json

    config = json.loads((Path(__file__).parent.parent / "langgraph.json").read_text())
    assert "auth" in config
    assert "langgraph_auth" in config["auth"]["path"]


def test_auth_handler_has_both_layers():
    from app.gateway.langgraph_auth import auth

    assert auth._authenticate_handler is not None
    assert len(auth._global_handlers) == 1


# ── CSRF in LangGraph auth ──────────────────────────────────────────────


def test_csrf_get_no_check():
    """GET requests skip CSRF — should proceed to JWT validation."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req(method="GET")))
    # Rejected by missing cookie, NOT by CSRF
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


def test_csrf_post_missing_token():
    """POST without CSRF token → 403."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req(method="POST", cookies={"access_token": "some-jwt"})))
    assert exc.value.status_code == 403
    assert "CSRF token missing" in str(exc.value.detail)


def test_csrf_post_mismatched_token():
    """POST with mismatched CSRF tokens → 403."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(
            authenticate(
                _req(
                    method="POST",
                    cookies={"access_token": "some-jwt", "csrf_token": "real-token"},
                    headers={"x-csrf-token": "wrong-token"},
                )
            )
        )
    assert exc.value.status_code == 403
    assert "mismatch" in str(exc.value.detail)


def test_csrf_post_matching_token_proceeds_to_jwt():
    """POST with matching CSRF tokens passes CSRF check, then fails on JWT."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(
            authenticate(
                _req(
                    method="POST",
                    cookies={"access_token": "garbage", "csrf_token": "same-token"},
                    headers={"x-csrf-token": "same-token"},
                )
            )
        )
    # Past CSRF, rejected by JWT decode
    assert exc.value.status_code == 401
    assert "Invalid token" in str(exc.value.detail)


def test_csrf_put_requires_token():
    """PUT also requires CSRF."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req(method="PUT", cookies={"access_token": "jwt"})))
    assert exc.value.status_code == 403


def test_csrf_delete_requires_token():
    """DELETE also requires CSRF."""
    with pytest.raises(Auth.exceptions.HTTPException) as exc:
        asyncio.run(authenticate(_req(method="DELETE", cookies={"access_token": "jwt"})))
    assert exc.value.status_code == 403
