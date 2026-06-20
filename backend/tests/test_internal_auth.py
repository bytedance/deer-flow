"""Tests for Gateway internal auth token handling."""

from __future__ import annotations

import importlib


def test_internal_auth_uses_shared_env_token(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert reloaded.is_valid_internal_auth_token("shared-token") is True
        assert reloaded.is_valid_internal_auth_token("other-token") is False
    finally:
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_internal_auth_generates_process_local_fallback(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        token = reloaded.create_internal_auth_headers()[reloaded.INTERNAL_AUTH_HEADER_NAME]

        assert token
        assert reloaded.is_valid_internal_auth_token(token) is True
    finally:
        importlib.reload(reloaded)


def test_internal_auth_headers_can_carry_owner_user_id(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers(owner_user_id="owner-1")

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert headers[reloaded.INTERNAL_OWNER_USER_ID_HEADER_NAME] == "owner-1"
    finally:
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)
