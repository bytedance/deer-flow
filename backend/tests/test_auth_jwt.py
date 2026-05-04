"""Tests for JWT token creation, decoding, and validation."""

import time

import pytest

from app.gateway.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config


@pytest.fixture(autouse=True)
def _setup_auth_config():
    reset_auth_config()
    load_auth_config_from_dict({
        "enabled": True,
        "jwt_secret": "test-secret-key",
        "jwt_algorithm": "HS256",
        "jwt_expire_minutes": 60,
    })
    yield
    reset_auth_config()


class TestCreateAccessToken:
    def test_creates_valid_token(self):
        token = create_access_token(tenant_id="default", username="admin", role="admin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_decodes_correctly(self):
        token = create_access_token(tenant_id="t1", username="alice", role="member")
        payload = decode_token(token)
        assert payload["sub"] == "alice"
        assert payload["tenant_id"] == "t1"
        assert payload["role"] == "member"
        assert payload["type"] == "access"

    def test_token_has_expiry(self):
        token = create_access_token(tenant_id="default", username="admin")
        payload = decode_token(token)
        assert "exp" in payload
        assert "iat" in payload


class TestCreateRefreshToken:
    def test_creates_refresh_token(self):
        token = create_refresh_token(tenant_id="default", username="admin")
        payload = decode_token(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "admin"

    def test_refresh_token_longer_expiry(self):
        token = create_refresh_token(tenant_id="default", username="admin")
        payload = decode_token(token)
        # Refresh tokens live 7 days; access tokens live 60 minutes
        assert payload["exp"] > payload["iat"] + 3600


class TestDecodeToken:
    def test_decode_valid_token(self):
        token = create_access_token(tenant_id="default", username="admin")
        payload = decode_token(token)
        assert payload["sub"] == "admin"

    def test_decode_tampered_token_raises(self):
        token = create_access_token(tenant_id="default", username="admin")
        tampered = token[:-5] + "xxxxx"
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(tampered)

    def test_decode_with_wrong_secret_raises(self):
        token = create_access_token(tenant_id="default", username="admin")
        # Change the secret
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "different-secret",
            "jwt_algorithm": "HS256",
            "jwt_expire_minutes": 60,
        })
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(token)

    def test_decode_expired_token_raises(self):
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "test-secret-key",
            "jwt_algorithm": "HS256",
            "jwt_expire_minutes": -1,  # Expired immediately
        })
        token = create_access_token(tenant_id="default", username="admin")
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(token)
