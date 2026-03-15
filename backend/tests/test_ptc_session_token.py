"""Unit tests for PTC HMAC session token creation and validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

from src.ptc.session_token import (
    _get_ptc_secret,
    create_session_token,
    validate_session_token,
)

# ---------------------------------------------------------------------------
# _get_ptc_secret
# ---------------------------------------------------------------------------


class TestGetPtcSecret:
    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "env-secret-value")
        assert _get_ptc_secret() == "env-secret-value"

    def test_from_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PTC_SECRET", raising=False)
        monkeypatch.delenv("REQUIRE_ENV_SECRETS", raising=False)

        store_dir = tmp_path / ".think-tank"
        store_dir.mkdir()
        secret_file = store_dir / "ptc-secret.key"
        secret_file.write_text("file-secret-value")

        with patch("src.ptc.session_token._STORE_DIR", store_dir), patch("src.ptc.session_token._SECRET_FILE", secret_file):
            assert _get_ptc_secret() == "file-secret-value"

    def test_auto_generate(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PTC_SECRET", raising=False)
        monkeypatch.delenv("REQUIRE_ENV_SECRETS", raising=False)

        store_dir = tmp_path / ".think-tank"
        secret_file = store_dir / "ptc-secret.key"

        with patch("src.ptc.session_token._STORE_DIR", store_dir), patch("src.ptc.session_token._SECRET_FILE", secret_file):
            secret = _get_ptc_secret()
            assert len(secret) > 20
            # Should be persisted
            assert secret_file.exists()
            assert secret_file.read_text().strip() == secret

    def test_require_env_secrets(self, monkeypatch):
        monkeypatch.delenv("PTC_SECRET", raising=False)
        monkeypatch.setenv("REQUIRE_ENV_SECRETS", "1")

        with pytest.raises(RuntimeError, match="PTC_SECRET"):
            _get_ptc_secret()


# ---------------------------------------------------------------------------
# Roundtrip: create + validate
# ---------------------------------------------------------------------------


class TestTokenRoundtrip:
    def test_create_and_validate(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret-123")

        token = create_session_token("thread-abc")
        result = validate_session_token(token)
        assert result == "thread-abc"

    def test_different_threads(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret-123")

        token1 = create_session_token("thread-1")
        token2 = create_session_token("thread-2")

        assert validate_session_token(token1) == "thread-1"
        assert validate_session_token(token2) == "thread-2"
        assert token1 != token2


# ---------------------------------------------------------------------------
# Token expiry
# ---------------------------------------------------------------------------


class TestTokenExpiry:
    def test_token_not_expired(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")

        token = create_session_token("thread-x")
        # Should be valid with default TTL
        assert validate_session_token(token) == "thread-x"

    def test_token_expired(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")

        # Manually create a token with an old timestamp
        secret = "test-secret"
        old_time = int(time.time()) - 7200  # 2 hours ago
        payload = {"thread_id": "thread-expired", "iat": old_time}
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        token = f"{payload_b64}.{sig_b64}"

        assert validate_session_token(token, ttl=3600) is None

    def test_custom_ttl(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")

        # Create token with short TTL
        token = create_session_token("thread-short")
        # Valid with generous TTL
        assert validate_session_token(token, ttl=60) == "thread-short"


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


class TestTamperDetection:
    def test_modified_payload(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")

        token = create_session_token("thread-original")

        # Extract original signature
        parts = token.split(".")
        original_sig_b64 = parts[1]

        # Build a tampered payload with the original signature
        tampered_payload = json.dumps(
            {"thread_id": "thread-hacked", "iat": int(time.time())},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        tampered_payload_b64 = base64.urlsafe_b64encode(tampered_payload).decode("ascii")
        tampered_token = f"{tampered_payload_b64}.{original_sig_b64}"

        assert validate_session_token(tampered_token) is None

    def test_wrong_secret(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "secret-A")
        token = create_session_token("thread-a")

        monkeypatch.setenv("PTC_SECRET", "secret-B")
        assert validate_session_token(token) is None

    def test_truncated_token(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        token = create_session_token("thread-x")
        # Truncate the token
        truncated = token[:10]
        assert validate_session_token(truncated) is None


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_empty_string(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        assert validate_session_token("") is None

    def test_not_base64(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        assert validate_session_token("not-valid-base64!!!") is None

    def test_no_separator(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        # Base64 string with no '.' separator
        data = base64.urlsafe_b64encode(b"no-dot-separator").decode("ascii")
        assert validate_session_token(data) is None

    def test_invalid_json_payload(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        secret = "test-secret"
        bad_payload = b"not-json"
        sig = hmac.new(secret.encode("utf-8"), bad_payload, hashlib.sha256).digest()
        payload_b64 = base64.urlsafe_b64encode(bad_payload).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        token = f"{payload_b64}.{sig_b64}"
        assert validate_session_token(token) is None

    def test_missing_thread_id(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        secret = "test-secret"
        payload = json.dumps({"iat": int(time.time())}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        token = f"{payload_b64}.{sig_b64}"
        assert validate_session_token(token) is None

    def test_missing_iat(self, monkeypatch):
        monkeypatch.setenv("PTC_SECRET", "test-secret")
        secret = "test-secret"
        payload = json.dumps({"thread_id": "t"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        token = f"{payload_b64}.{sig_b64}"
        assert validate_session_token(token) is None
