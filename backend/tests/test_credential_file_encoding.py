"""CLI credential files must decode independently of the host locale."""

import json
from pathlib import Path

import pytest

from deerflow.models.credential_loader import load_claude_code_credential, load_codex_cli_credential


@pytest.fixture(autouse=True)
def isolate_credential_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_CREDENTIALS_PATH",
        "CODEX_AUTH_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(params=["claude", "codex", "codex-legacy"])
def credential_file(request, tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    if request.param == "claude":
        monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(path))
        payload = {"claudeAiOauth": {"accessToken": "synthetic-token"}}
        loader = load_claude_code_credential
    else:
        monkeypatch.setenv("CODEX_AUTH_PATH", str(path))
        tokens = {"access_token": "synthetic-token", "account_id": "synthetic-account"}
        payload = {"tokens": tokens} if request.param == "codex" else tokens
        loader = load_codex_cli_credential
    return path, payload, loader


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_cli_credentials_accept_utf8_with_or_without_bom(credential_file, encoding):
    path, payload, loader = credential_file
    path.write_text(json.dumps(payload), encoding=encoding)

    credential = loader()

    assert credential is not None
    assert credential.access_token == "synthetic-token"
    if hasattr(credential, "account_id"):
        assert credential.account_id == "synthetic-account"


def test_cli_credentials_do_not_use_the_host_text_encoding(credential_file, monkeypatch):
    path, payload, loader = credential_file
    # U+201D contains byte 0x9d in UTF-8, which is undefined in cp1252.
    # A valid JSON file can contain Unicode metadata unrelated to authentication.
    payload["label"] = "开发者”"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_open = Path.open

    def legacy_locale_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if self == path and "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", legacy_locale_open)

    credential = loader()

    assert credential is not None
    assert credential.access_token == "synthetic-token"


@pytest.mark.parametrize("content", [b"\xff\xfeinvalid", b'{"access_token": "synthetic-token"}\xff', b"not JSON"])
def test_unreadable_credential_files_degrade_to_no_credential(credential_file, content, caplog):
    path, _, loader = credential_file
    path.write_bytes(content)

    assert loader() is None
    assert "Failed to read" in caplog.text
    assert "synthetic-token" not in caplog.text


def test_claude_falls_back_after_invalid_utf8_override(tmp_path, monkeypatch):
    override = tmp_path / "invalid.json"
    override.write_bytes(b"\xff")
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(override))
    default = tmp_path / ".claude" / ".credentials.json"
    default.parent.mkdir()
    default.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fallback-token"}}), encoding="utf-8")

    credential = load_claude_code_credential()

    assert credential is not None
    assert credential.access_token == "fallback-token"
    assert credential.source == "claude-cli-file"
