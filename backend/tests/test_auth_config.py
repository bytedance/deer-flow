"""Tests for AuthConfig typed configuration."""

import os
from unittest.mock import patch

import pytest

import app.gateway.auth.config as cfg


def test_auth_config_defaults():
    config = cfg.AuthConfig(jwt_secret="test-secret-key-123")
    assert config.token_expiry_days == 7


def test_auth_config_token_expiry_range():
    cfg.AuthConfig(jwt_secret="s", token_expiry_days=1)
    cfg.AuthConfig(jwt_secret="s", token_expiry_days=30)
    with pytest.raises(Exception):
        cfg.AuthConfig(jwt_secret="s", token_expiry_days=0)
    with pytest.raises(Exception):
        cfg.AuthConfig(jwt_secret="s", token_expiry_days=31)


def test_auth_config_from_env():
    env = {"AUTH_JWT_SECRET": "test-jwt-secret-from-env"}
    with patch.dict(os.environ, env, clear=False):
        old = cfg._auth_config
        cfg._auth_config = None
        try:
            config = cfg.get_auth_config()
            assert config.jwt_secret == "test-jwt-secret-from-env"
        finally:
            cfg._auth_config = old


def test_auth_config_missing_secret_generates_and_persists(tmp_path, caplog):
    import logging

    from deerflow.config.paths import Paths

    old = cfg._auth_config
    cfg._auth_config = None
    secret_file = tmp_path / ".jwt_secret"
    try:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)), caplog.at_level(logging.WARNING):
                config = cfg.get_auth_config()
            assert config.jwt_secret
            assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)
            assert secret_file.exists()
            assert secret_file.read_text().strip() == config.jwt_secret
    finally:
        cfg._auth_config = old


def test_auth_config_reuses_persisted_secret(tmp_path):
    from deerflow.config.paths import Paths

    old = cfg._auth_config
    cfg._auth_config = None
    persisted = "persisted-secret-from-file-min-32-chars!!"
    (tmp_path / ".jwt_secret").write_text(persisted, encoding="utf-8")
    try:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
                config = cfg.get_auth_config()
            assert config.jwt_secret == persisted
    finally:
        cfg._auth_config = old


def test_auth_config_empty_secret_file_generates_new(tmp_path):
    from deerflow.config.paths import Paths

    old = cfg._auth_config
    cfg._auth_config = None
    (tmp_path / ".jwt_secret").write_text("", encoding="utf-8")
    try:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
                config = cfg.get_auth_config()
            assert config.jwt_secret
            assert len(config.jwt_secret) > 20
            assert (tmp_path / ".jwt_secret").read_text().strip() == config.jwt_secret
    finally:
        cfg._auth_config = old
