"""Tests for API Key generation, hashing, verification, and storage."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from app.gateway.auth.api_key_handler import (
    create_api_key,
    generate_api_key,
    hash_key,
    list_api_keys,
    load_api_keys,
    revoke_api_key,
    save_api_keys,
    verify_and_track_api_key,
    verify_key,
)
from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config
from deerflow.config.tenant import _current_tenant_id


@pytest.fixture(autouse=True)
def _setup_auth_config():
    reset_auth_config()
    load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
    yield
    reset_auth_config()


class TestGenerateApiKey:
    def test_has_df_prefix(self):
        key = generate_api_key()
        assert key.startswith("df-")

    def test_correct_length(self):
        key = generate_api_key()
        # df- + 64 hex chars
        assert len(key) == 3 + 64

    def test_keys_are_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestHashAndVerify:
    def test_hash_is_deterministic(self):
        key = "df-abc123"
        assert hash_key(key) == hash_key(key)

    def test_verify_matching_key(self):
        key = generate_api_key()
        h = hash_key(key)
        assert verify_key(key, h) is True

    def test_verify_non_matching_key(self):
        h = hash_key("df-aaa")
        assert verify_key("df-bbb", h) is False


class TestApiKeyPersistence:
    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        assert load_api_keys() == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        keys = {
            "hash1": {"id": "k1", "name": "key1", "key_prefix": "df-aaaa", "created_at": "2025-01-01T00:00:00", "last_used_at": None, "revoked_at": None},
        }
        save_api_keys(keys)
        loaded = load_api_keys()
        assert "hash1" in loaded
        assert loaded["hash1"]["name"] == "key1"

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        deep = tmp_path / "sub" / "dir" / "api_keys.json"
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: deep)
        save_api_keys({})
        assert deep.exists()


class TestCreateApiKey:
    def test_create_returns_expected_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="test-key")
        assert "id" in result
        assert result["name"] == "test-key"
        assert "raw_key" in result
        assert result["raw_key"].startswith("df-")
        assert "key_prefix" in result
        assert "created_at" in result

    def test_created_key_appears_in_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        create_api_key(name="visible-key")
        keys = list_api_keys()
        assert len(keys) == 1
        assert keys[0]["name"] == "visible-key"


class TestListApiKeys:
    def test_excludes_revoked_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="to-revoke")
        revoke_api_key(result["id"])
        keys = list_api_keys()
        assert len(keys) == 0

    def test_includes_active_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        create_api_key(name="active-1")
        create_api_key(name="active-2")
        keys = list_api_keys()
        assert len(keys) == 2


class TestRevokeApiKey:
    def test_revoke_existing_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="revoke-me")
        assert revoke_api_key(result["id"]) is True

    def test_revoke_nonexistent_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        assert revoke_api_key("nonexistent-id") is False


class TestVerifyAndTrackApiKey:
    def test_valid_key_returns_meta(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="verify-me")
        meta = verify_and_track_api_key(result["raw_key"])
        assert meta is not None
        assert meta["name"] == "verify-me"

    def test_invalid_key_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        assert verify_and_track_api_key("df-invalid") is None

    def test_revoked_key_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="revoked-later")
        revoke_api_key(result["id"])
        assert verify_and_track_api_key(result["raw_key"]) is None

    def test_updates_last_used_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        result = create_api_key(name="track-me")
        meta = verify_and_track_api_key(result["raw_key"])
        assert meta["last_used_at"] is not None
