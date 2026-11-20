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


def test_jwt_secret_creation_keeps_a_peer_replica_value(tmp_path, monkeypatch):
    """Two replicas cold-starting on a shared home volume must sign with one key.

    Deterministic interleaving: the peer creates ``.jwt_secret`` after this
    process found none but before it writes. A truncating write would replace
    the peer's value and both replicas would keep different secrets.
    """
    from deerflow.config.paths import Paths

    secret_file = tmp_path / ".jwt_secret"

    def peer_wins_the_race(_nbytes):
        secret_file.write_text("peer-replica-secret-value-0123456789", encoding="utf-8")
        return "this-replica-secret-value-0123456789"

    monkeypatch.setattr(cfg.secrets, "token_urlsafe", peer_wins_the_race)
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
        secret = cfg._load_or_create_secret()

    assert secret == "peer-replica-secret-value-0123456789"
    assert secret_file.read_text(encoding="utf-8") == "peer-replica-secret-value-0123456789"


def test_concurrent_jwt_secret_creators_converge(tmp_path):
    import threading

    from deerflow.config.paths import Paths

    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def run():
        barrier.wait(timeout=10)
        value = cfg._load_or_create_secret()
        with lock:
            results.append(value)

    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
        threads = [threading.Thread(target=run) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

    assert len(results) == workers
    assert len(set(results)) == 1
    assert (tmp_path / ".jwt_secret").read_text(encoding="utf-8") == results[0]
    if os.name == "posix":
        assert (tmp_path / ".jwt_secret").stat().st_mode & 0o777 == 0o600


def test_unusable_jwt_secret_location_keeps_the_actionable_error(tmp_path):
    from deerflow.config.paths import Paths

    not_a_directory = tmp_path / "home"
    not_a_directory.write_text("", encoding="utf-8")
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=not_a_directory)), pytest.raises(RuntimeError, match="AUTH_JWT_SECRET"):
        cfg._load_or_create_secret()
