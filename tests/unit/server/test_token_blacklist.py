# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Unit tests for JWT token blacklisting (logout invalidation)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.middleware.auth import (
    add_token_to_blacklist,
    clear_token_blacklist,
    create_access_token,
    get_current_user,
    is_token_blacklisted,
    require_admin_user,
    verify_token,
    _cleanup_expired_blacklist_entries,
    _token_blacklist,
    _blacklist_expiry,
)


# Valid token payload used across tests
_TOKEN_DATA = {"sub": "user_1", "email": "user@test.com", "role": "user"}


@pytest.fixture(autouse=True)
def _clean_blacklist():
    """Ensure the blacklist is empty before and after every test."""
    clear_token_blacklist()
    yield
    clear_token_blacklist()


# ---------------------------------------------------------------------------
# Unit tests – blacklist helpers
# ---------------------------------------------------------------------------


class TestAddTokenToBlacklist:
    """Tests for add_token_to_blacklist."""

    def test_token_is_added(self):
        token = create_access_token(_TOKEN_DATA)
        add_token_to_blacklist(token)
        assert token in _token_blacklist

    def test_expiry_is_recorded(self):
        token = create_access_token(_TOKEN_DATA)
        add_token_to_blacklist(token)
        assert token in _blacklist_expiry

    def test_invalid_token_still_blacklisted(self):
        """Even a garbage string should be blacklisted so it can't be used."""
        add_token_to_blacklist("not-a-real-jwt")
        assert is_token_blacklisted("not-a-real-jwt")
        # A fallback expiry should have been set
        assert "not-a-real-jwt" in _blacklist_expiry


class TestIsTokenBlacklisted:
    """Tests for is_token_blacklisted."""

    def test_returns_false_for_fresh_token(self):
        token = create_access_token(_TOKEN_DATA)
        assert is_token_blacklisted(token) is False

    def test_returns_true_after_blacklisting(self):
        token = create_access_token(_TOKEN_DATA)
        add_token_to_blacklist(token)
        assert is_token_blacklisted(token) is True


class TestCleanupExpiredBlacklistEntries:
    """Tests for _cleanup_expired_blacklist_entries."""

    def test_expired_entries_are_removed(self):
        """Tokens whose expiry is in the past should be purged."""
        token = create_access_token(_TOKEN_DATA, expires_delta=timedelta(seconds=-1))
        # Manually add since the token is already expired
        _token_blacklist.add(token)
        from datetime import datetime, timezone
        _blacklist_expiry[token] = datetime(2000, 1, 1, tzinfo=timezone.utc)

        _cleanup_expired_blacklist_entries()

        assert token not in _token_blacklist
        assert token not in _blacklist_expiry

    def test_valid_entries_are_kept(self):
        token = create_access_token(_TOKEN_DATA, expires_delta=timedelta(hours=1))
        add_token_to_blacklist(token)

        _cleanup_expired_blacklist_entries()

        assert token in _token_blacklist


class TestClearTokenBlacklist:
    """Tests for clear_token_blacklist."""

    def test_clears_everything(self):
        for i in range(5):
            add_token_to_blacklist(create_access_token({**_TOKEN_DATA, "sub": f"u{i}"}))
        assert len(_token_blacklist) == 5

        clear_token_blacklist()

        assert len(_token_blacklist) == 0
        assert len(_blacklist_expiry) == 0


# ---------------------------------------------------------------------------
# Unit tests – verify_token rejects blacklisted tokens
# ---------------------------------------------------------------------------


class TestVerifyTokenBlacklistIntegration:
    """Ensure verify_token refuses blacklisted tokens."""

    def test_valid_token_passes(self):
        token = create_access_token(_TOKEN_DATA)
        payload = verify_token(token)
        assert payload["sub"] == "user_1"
        assert payload["email"] == "user@test.com"

    def test_blacklisted_token_is_rejected(self):
        token = create_access_token(_TOKEN_DATA)
        # Token works before blacklisting
        assert verify_token(token) != {}

        add_token_to_blacklist(token)

        # Same token is now rejected
        assert verify_token(token) == {}

    def test_other_tokens_unaffected(self):
        token_a = create_access_token({**_TOKEN_DATA, "sub": "a"})
        token_b = create_access_token({**_TOKEN_DATA, "sub": "b"})

        add_token_to_blacklist(token_a)

        assert verify_token(token_a) == {}
        assert verify_token(token_b) != {}


# ---------------------------------------------------------------------------
# Endpoint tests – POST /api/auth/logout
# ---------------------------------------------------------------------------

MOCK_USER = {"id": "user_1", "email": "user@test.com", "role": "user"}


@pytest.fixture
def auth_client():
    """TestClient with auth overrides for non-logout endpoints."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[require_admin_user] = lambda: MOCK_USER
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestLogoutEndpoint:
    """Tests for POST /api/auth/logout."""

    def test_logout_returns_success(self, auth_client):
        token = create_access_token(_TOKEN_DATA)
        response = auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    def test_logout_blacklists_token(self, auth_client):
        token = create_access_token(_TOKEN_DATA)
        auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert is_token_blacklisted(token) is True

    def test_blacklisted_token_rejected_on_subsequent_request(self, auth_client):
        """After logout, using the same token for an authenticated endpoint should fail."""
        token = create_access_token(_TOKEN_DATA)

        # Logout – blacklists the token
        resp = auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Remove the dependency override so real token verification kicks in
        app.dependency_overrides.pop(get_current_user, None)

        # Attempt to hit an authenticated endpoint with the now-blacklisted token
        resp = auth_client.get(
            "/api/auth/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_logout_without_token_returns_401(self, auth_client):
        """Calling logout with no Authorization header should be rejected."""
        # Remove overrides so the real security dependency runs
        app.dependency_overrides.clear()
        response = auth_client.post("/api/auth/logout")
        assert response.status_code == 401

    def test_different_token_still_works_after_logout(self, auth_client):
        """Logging out with token A should NOT affect token B."""
        token_a = create_access_token({**_TOKEN_DATA, "sub": "a"})
        token_b = create_access_token({**_TOKEN_DATA, "sub": "b"})

        auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        # Remove override so real verification happens
        app.dependency_overrides.pop(get_current_user, None)

        resp = auth_client.get(
            "/api/auth/validate",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 200
