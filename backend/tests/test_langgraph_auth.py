"""Tests for LangGraph Server auth handler (langgraph_auth.py).

Validates that the LangGraph auth layer enforces the same rules as Gateway:
  cookie → JWT decode → DB lookup → token_version check → owner filter
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-langgraph-auth-testing-min-32")

from langgraph_sdk import Auth

from app.gateway import langgraph_auth as auth_module
from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.jwt import create_access_token, decode_token
from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID
from app.gateway.langgraph_auth import add_owner_filter, authenticate
from deerflow.mcp_scope import (
    THREAD_INCARNATION_CONTEXT_KEY,
    THREAD_INCARNATION_METADATA_GUARD_KEY,
)

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


def test_auth_disabled_skips_csrf_and_authenticates_e2e_user(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")

    identity = asyncio.run(authenticate(_req(method="POST")))

    assert identity == AUTH_DISABLED_USER_ID


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


def _make_ctx(user_id, *, resource="threads", action="create", user=None):
    return Auth.types.AuthContext(resource=resource, action=action, user=user or _FakeUser(user_id), permissions=[])


def _studio_ctx(*, resource="assistants", action="search"):
    return _make_ctx(
        "langgraph-studio-user",
        resource=resource,
        action=action,
        user=Auth.types.StudioUser("langgraph-studio-user"),
    )


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


def test_thread_create_overwrites_client_incarnation():
    value = {"metadata": {THREAD_INCARNATION_CONTEXT_KEY: "attacker"}}

    asyncio.run(add_owner_filter(_make_ctx("user-a"), value))

    incarnation = value["metadata"][THREAD_INCARNATION_CONTEXT_KEY]
    assert incarnation != "attacker"
    assert isinstance(incarnation, str) and incarnation


@pytest.mark.parametrize("value", ["attacker", "", None, False])
def test_thread_update_cannot_change_incarnation(value):
    request = {"metadata": {THREAD_INCARNATION_CONTEXT_KEY: value}}

    asyncio.run(
        add_owner_filter(
            _make_ctx("user-a", action="update"),
            request,
        )
    )

    assert THREAD_INCARNATION_CONTEXT_KEY not in request["metadata"]


def test_run_admission_uses_persisted_incarnation_and_scrubs_client_values():
    thread_id = uuid4()
    run_id = uuid4()
    value = {
        "thread_id": thread_id,
        "run_id": run_id,
        "metadata": {
            THREAD_INCARNATION_CONTEXT_KEY: "metadata-attacker",
            THREAD_INCARNATION_METADATA_GUARD_KEY: True,
        },
        "kwargs": {
            "context": {
                THREAD_INCARNATION_CONTEXT_KEY: "context-attacker",
                THREAD_INCARNATION_METADATA_GUARD_KEY: False,
                "user_id": "attacker",
                "thread_id": "attacker",
                "run_id": "attacker",
            },
            "config": {
                "context": {
                    THREAD_INCARNATION_CONTEXT_KEY: "config-context-attacker",
                    THREAD_INCARNATION_METADATA_GUARD_KEY: False,
                },
                "metadata": {
                    THREAD_INCARNATION_CONTEXT_KEY: "config-metadata-attacker",
                    THREAD_INCARNATION_METADATA_GUARD_KEY: False,
                },
                "configurable": {
                    THREAD_INCARNATION_CONTEXT_KEY: "configurable-attacker",
                    THREAD_INCARNATION_METADATA_GUARD_KEY: False,
                },
            },
        },
        "if_not_exists": "reject",
    }

    with patch.object(
        auth_module,
        "_read_standalone_thread",
        AsyncMock(
            return_value={
                "metadata": {THREAD_INCARNATION_CONTEXT_KEY: "server-incarnation"},
            }
        ),
    ):
        asyncio.run(
            add_owner_filter(
                _make_ctx("user-a", action="create_run"),
                value,
            )
        )

    assert value["kwargs"]["context"][THREAD_INCARNATION_CONTEXT_KEY] == "server-incarnation"
    assert value["kwargs"]["context"][THREAD_INCARNATION_METADATA_GUARD_KEY] is True
    assert value["kwargs"]["context"]["user_id"] == "user-a"
    assert value["kwargs"]["context"]["thread_id"] == str(thread_id)
    assert value["kwargs"]["context"]["run_id"] == str(run_id)
    assert THREAD_INCARNATION_CONTEXT_KEY not in value["metadata"]
    assert THREAD_INCARNATION_METADATA_GUARD_KEY not in value["metadata"]
    assert THREAD_INCARNATION_CONTEXT_KEY not in value["kwargs"]["config"]["context"]
    assert THREAD_INCARNATION_METADATA_GUARD_KEY not in value["kwargs"]["config"]["context"]
    assert "user_id" not in value["kwargs"]["config"]["context"]
    assert "thread_id" not in value["kwargs"]["config"]["context"]
    assert "run_id" not in value["kwargs"]["config"]["context"]
    assert THREAD_INCARNATION_CONTEXT_KEY not in value["kwargs"]["config"]["metadata"]
    assert THREAD_INCARNATION_METADATA_GUARD_KEY not in value["kwargs"]["config"]["metadata"]
    assert THREAD_INCARNATION_CONTEXT_KEY not in value["kwargs"]["config"]["configurable"]
    assert THREAD_INCARNATION_METADATA_GUARD_KEY not in value["kwargs"]["config"]["configurable"]


def test_existing_legacy_thread_uses_explicit_none_without_backfill():
    with patch.object(
        auth_module,
        "_read_standalone_thread",
        AsyncMock(return_value={"metadata": {"legacy": True}}),
    ):
        incarnation = asyncio.run(
            auth_module._ensure_standalone_thread_incarnation(
                uuid4(),
                _make_ctx("user-a", action="create_run"),
                create_if_missing=False,
            )
        )

    assert incarnation is None


def test_implicit_create_accepts_legacy_thread_created_by_mixed_version_peer():
    class _Connection:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    async def _put_rows():
        yield {"metadata": {"legacy": True}}

    put = AsyncMock(return_value=_put_rows())
    runtime_package = ModuleType("langgraph_runtime")
    runtime_package.__path__ = []
    database_module = ModuleType("langgraph_runtime.database")
    database_module.connect = _Connection
    ops_module = ModuleType("langgraph_runtime.ops")
    ops_module.Threads = SimpleNamespace(put=put)

    with (
        patch.object(
            auth_module,
            "_read_standalone_thread",
            AsyncMock(side_effect=[None, {"metadata": {"legacy": True}}]),
        ),
        patch.dict(
            sys.modules,
            {
                "langgraph_runtime": runtime_package,
                "langgraph_runtime.database": database_module,
                "langgraph_runtime.ops": ops_module,
            },
        ),
    ):
        incarnation = asyncio.run(
            auth_module._ensure_standalone_thread_incarnation(
                uuid4(),
                _make_ctx("user-a", action="create_run"),
                create_if_missing=True,
            )
        )

    assert incarnation is None
    put.assert_awaited_once()


@pytest.mark.parametrize("persisted_incarnation", [None, "versioned-incarnation"])
def test_run_admission_preserves_persisted_incarnation_value(persisted_incarnation):
    value = {
        "thread_id": uuid4(),
        "metadata": {},
        "kwargs": {},
        "if_not_exists": "reject",
    }

    with patch.object(
        auth_module,
        "_ensure_standalone_thread_incarnation",
        AsyncMock(return_value=persisted_incarnation),
    ):
        asyncio.run(
            add_owner_filter(
                _make_ctx("user-a", action="create_run"),
                value,
            )
        )

    assert THREAD_INCARNATION_CONTEXT_KEY not in value["metadata"]
    assert value["kwargs"]["context"][THREAD_INCARNATION_CONTEXT_KEY] is persisted_incarnation
    assert value["kwargs"]["context"][THREAD_INCARNATION_METADATA_GUARD_KEY] is True


def test_run_admission_does_not_invent_incarnation_for_missing_rejected_thread():
    value = {
        "thread_id": uuid4(),
        "metadata": {THREAD_INCARNATION_CONTEXT_KEY: "attacker"},
        "kwargs": {
            "context": {THREAD_INCARNATION_CONTEXT_KEY: "attacker"},
        },
        "if_not_exists": "reject",
    }

    with patch.object(
        auth_module,
        "_ensure_standalone_thread_incarnation",
        AsyncMock(return_value=auth_module._MISSING),
    ):
        asyncio.run(
            add_owner_filter(
                _make_ctx("user-a", action="create_run"),
                value,
            )
        )

    assert THREAD_INCARNATION_CONTEXT_KEY not in value["metadata"]
    assert THREAD_INCARNATION_CONTEXT_KEY not in value["kwargs"]["context"]
    assert THREAD_INCARNATION_METADATA_GUARD_KEY not in value["kwargs"]["context"]


def test_run_admission_rejects_invalid_persisted_incarnation():
    value = {
        "thread_id": uuid4(),
        "metadata": {},
        "kwargs": {},
        "if_not_exists": "reject",
    }

    with (
        patch.object(
            auth_module,
            "_read_standalone_thread",
            AsyncMock(
                return_value={
                    "metadata": {THREAD_INCARNATION_CONTEXT_KEY: ""},
                }
            ),
        ),
        pytest.raises(
            RuntimeError,
            match="invalid incarnation",
        ),
    ):
        asyncio.run(
            add_owner_filter(
                _make_ctx("user-a", action="create_run"),
                value,
            )
        )


def test_temporary_run_gets_explicit_legacy_incarnation():
    value = {
        "thread_id": None,
        "metadata": {},
        "kwargs": {
            "context": {THREAD_INCARNATION_CONTEXT_KEY: "attacker"},
        },
        "if_not_exists": "reject",
    }

    asyncio.run(
        add_owner_filter(
            _make_ctx("user-a", action="create_run"),
            value,
        )
    )

    assert value["kwargs"]["context"][THREAD_INCARNATION_CONTEXT_KEY] is None


@pytest.mark.parametrize("action", ["read", "search"])
def test_studio_user_assistant_discovery_includes_system_and_studio_owned_assistants(action):
    value = {}
    result = asyncio.run(add_owner_filter(_studio_ctx(action=action), value))

    assert result == {
        "$or": [
            {"created_by": "system"},
            {"user_id": "langgraph-studio-user"},
        ]
    }
    assert value == {}


@pytest.mark.parametrize("action", ["create", "update"])
def test_studio_assistant_writes_stamp_server_owned_provenance(action):
    value = {"metadata": {"created_by": "system"}}
    result = asyncio.run(add_owner_filter(_studio_ctx(action=action), value))

    assert value["metadata"] == {
        "created_by": "user",
        "user_id": "langgraph-studio-user",
    }
    assert result == {"user_id": "langgraph-studio-user"}


def test_studio_user_non_assistant_operations_remain_owner_scoped():
    value = {}
    result = asyncio.run(
        add_owner_filter(
            _studio_ctx(resource="threads", action="search"),
            value,
        )
    )

    assert value["metadata"]["user_id"] == "langgraph-studio-user"
    assert result == {"user_id": "langgraph-studio-user"}


def test_identity_string_does_not_impersonate_studio_user():
    value = {}
    result = asyncio.run(
        add_owner_filter(
            _make_ctx(
                "langgraph-studio-user",
                resource="assistants",
                action="search",
            ),
            value,
        )
    )

    assert value["metadata"]["user_id"] == "langgraph-studio-user"
    assert result == {"user_id": "langgraph-studio-user"}


def test_missing_studio_user_type_degrades_to_owner_scoped_behavior():
    value = {}
    with patch("app.gateway.langgraph_auth._STUDIO_USER_TYPE", None):
        result = asyncio.run(add_owner_filter(_studio_ctx(), value))

    assert value["metadata"]["user_id"] == "langgraph-studio-user"
    assert result == {"user_id": "langgraph-studio-user"}


def test_regular_user_assistant_search_remains_owner_scoped():
    value = {}
    result = asyncio.run(
        add_owner_filter(
            _make_ctx("user-a", resource="assistants", action="search"),
            value,
        )
    )

    assert value["metadata"]["user_id"] == "user-a"
    assert result == {"user_id": "user-a"}


@pytest.mark.parametrize("action", ["create", "update"])
def test_regular_user_cannot_forge_system_assistant_provenance(action):
    value = {"metadata": {"created_by": "system", "label": "forged"}}
    result = asyncio.run(
        add_owner_filter(
            _make_ctx("user-a", resource="assistants", action=action),
            value,
        )
    )

    assert value["metadata"] == {
        "created_by": "user",
        "label": "forged",
        "user_id": "user-a",
    }
    assert result == {"user_id": "user-a"}


@pytest.mark.parametrize(
    "ctx,user_id",
    [
        (_studio_ctx(action="update"), "langgraph-studio-user"),
        (_make_ctx("user-a", resource="assistants", action="update"), "user-a"),
    ],
)
def test_assistant_version_selection_remains_owner_scoped(ctx, user_id):
    value = {"assistant_id": uuid4(), "version": 1}

    result = asyncio.run(add_owner_filter(ctx, value))

    assert value["metadata"] == {
        "created_by": "user",
        "user_id": user_id,
    }
    assert result == {"user_id": user_id}


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
