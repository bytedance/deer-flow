"""Tests for deerflow.models.credential_loader — CLI credential loading."""

from __future__ import annotations

import json
import time
from pathlib import Path

from deerflow.models.credential_loader import (
    ClaudeCodeCredential,
    is_oauth_token,
    load_claude_code_credential,
    load_codex_cli_credential,
)

# ---------------------------------------------------------------------------
# is_oauth_token
# ---------------------------------------------------------------------------


class TestIsOauthToken:
    def test_detects_oauth_prefix(self):
        assert is_oauth_token("sk-ant-oat01-abc123") is True

    def test_rejects_standard_api_key(self):
        assert is_oauth_token("sk-ant-api03-abc123") is False

    def test_rejects_empty_string(self):
        assert is_oauth_token("") is False

    def test_rejects_non_string(self):
        assert is_oauth_token(None) is False  # type: ignore[arg-type]
        assert is_oauth_token(123) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ClaudeCodeCredential
# ---------------------------------------------------------------------------


class TestClaudeCodeCredential:
    def test_not_expired_when_no_expiry(self):
        cred = ClaudeCodeCredential(access_token="tok", expires_at=0)
        assert cred.is_expired is False

    def test_not_expired_when_future(self):
        future_ms = int((time.time() + 3600) * 1000)
        cred = ClaudeCodeCredential(access_token="tok", expires_at=future_ms)
        assert cred.is_expired is False

    def test_expired_when_past(self):
        past_ms = int((time.time() - 3600) * 1000)
        cred = ClaudeCodeCredential(access_token="tok", expires_at=past_ms)
        assert cred.is_expired is True


# ---------------------------------------------------------------------------
# load_claude_code_credential
# ---------------------------------------------------------------------------


class TestLoadClaudeCodeCredential:
    def _write_cred(self, home: Path, data: dict) -> None:
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / ".credentials.json").write_text(json.dumps(data))

    def test_loads_valid_credential(self, tmp_path, monkeypatch):
        future_ms = int((time.time() + 3600) * 1000)
        self._write_cred(
            tmp_path,
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-test",
                    "refreshToken": "sk-ant-ort01-refresh",
                    "expiresAt": future_ms,
                }
            },
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cred = load_claude_code_credential()
        assert cred is not None
        assert cred.access_token == "sk-ant-oat01-test"
        assert cred.refresh_token == "sk-ant-ort01-refresh"
        assert cred.source == "claude-cli"

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_claude_code_credential() is None

    def test_returns_none_when_no_access_token(self, tmp_path, monkeypatch):
        self._write_cred(tmp_path, {"claudeAiOauth": {}})
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_claude_code_credential() is None

    def test_returns_none_when_expired(self, tmp_path, monkeypatch):
        past_ms = int((time.time() - 3600) * 1000)
        self._write_cred(tmp_path, {"claudeAiOauth": {"accessToken": "tok", "expiresAt": past_ms}})
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_claude_code_credential() is None

    def test_returns_none_on_invalid_json(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / ".credentials.json").write_text("not-json{{{")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_claude_code_credential() is None


# ---------------------------------------------------------------------------
# load_codex_cli_credential
# ---------------------------------------------------------------------------


class TestLoadCodexCliCredential:
    def _write_cred(self, home: Path, data: dict) -> None:
        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "auth.json").write_text(json.dumps(data))

    def test_loads_from_tokens_access_token(self, tmp_path, monkeypatch):
        self._write_cred(tmp_path, {"tokens": {"access_token": "eyJ-test-token", "account_id": "acc-123"}})
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cred = load_codex_cli_credential()
        assert cred is not None
        assert cred.access_token == "eyJ-test-token"

    def test_loads_from_top_level_access_token(self, tmp_path, monkeypatch):
        self._write_cred(tmp_path, {"access_token": "eyJ-top-level"})
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cred = load_codex_cli_credential()
        assert cred is not None
        assert cred.access_token == "eyJ-top-level"

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_codex_cli_credential() is None

    def test_returns_none_when_no_token(self, tmp_path, monkeypatch):
        self._write_cred(tmp_path, {"tokens": {}})
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_codex_cli_credential() is None

    def test_returns_none_on_invalid_json(self, tmp_path, monkeypatch):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir(parents=True)
        (codex_dir / "auth.json").write_text("{broken")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert load_codex_cli_credential() is None
