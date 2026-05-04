"""Tests for AuthConfig — defaults, loading, and singleton lifecycle."""

import pytest

from deerflow.config.auth_config import (
    AuthConfig,
    get_auth_config,
    load_auth_config_from_dict,
    reset_auth_config,
)


class TestAuthConfigDefaults:
    def test_default_disabled(self):
        reset_auth_config()
        config = get_auth_config()
        assert config.enabled is False
        assert config.jwt_algorithm == "HS256"
        assert config.jwt_expire_minutes == 1440
        assert config.api_key_enabled is True
        assert config.admin_username == "admin"
        assert config.admin_password_hash == ""

    def test_default_jwt_secret_empty(self):
        reset_auth_config()
        config = get_auth_config()
        assert config.jwt_secret == ""


class TestAuthConfigLoading:
    def test_load_from_dict(self):
        data = {
            "enabled": True,
            "jwt_secret": "my-secret",
            "jwt_algorithm": "HS512",
            "jwt_expire_minutes": 60,
            "api_key_enabled": False,
            "admin_username": "root",
            "admin_password_hash": "$2b$12$hash",
        }
        config = load_auth_config_from_dict(data)
        assert config.enabled is True
        assert config.jwt_secret == "my-secret"
        assert config.jwt_algorithm == "HS512"
        assert config.jwt_expire_minutes == 60
        assert config.api_key_enabled is False
        assert config.admin_username == "root"
        assert config.admin_password_hash == "$2b$12$hash"

    def test_load_partial_dict_fills_defaults(self):
        config = load_auth_config_from_dict({"enabled": True})
        assert config.enabled is True
        assert config.jwt_algorithm == "HS256"

    def test_get_returns_loaded_config(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        config = get_auth_config()
        assert config.enabled is True
        assert config.jwt_secret == "s"


class TestAuthConfigSingleton:
    def test_reset_clears_cache(self):
        load_auth_config_from_dict({"enabled": True})
        reset_auth_config()
        config = get_auth_config()
        assert config.enabled is False

    def test_get_creates_default_when_none_loaded(self):
        reset_auth_config()
        config = get_auth_config()
        assert isinstance(config, AuthConfig)
        assert config.enabled is False
