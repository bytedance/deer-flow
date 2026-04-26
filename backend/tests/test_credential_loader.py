import json
import os

from deerflow.models.credential_loader import (
    load_claude_code_credential,
    load_codex_cli_credential,
)


def _clear_claude_code_env(monkeypatch) -> None:
    for env_var in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_CREDENTIALS_PATH",
    ):
        monkeypatch.delenv(env_var, raising=False)


def test_load_claude_code_credential_from_direct_env(monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "  sk-ant-oat01-env  ")

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-env"
    assert cred.refresh_token == ""
    assert cred.source == "claude-cli-env"


def test_load_claude_code_credential_from_anthropic_auth_env(monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-anthropic-auth")

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-anthropic-auth"
    assert cred.source == "claude-cli-env"


def test_load_claude_code_credential_from_file_descriptor(monkeypatch):
    _clear_claude_code_env(monkeypatch)

    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"sk-ant-oat01-fd")
        os.close(write_fd)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))

        cred = load_claude_code_credential()
    finally:
        os.close(read_fd)

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-fd"
    assert cred.refresh_token == ""
    assert cred.source == "claude-cli-fd"


def test_load_claude_code_credential_from_override_path(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    cred_path = tmp_path / "claude-credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-test",
                    "refreshToken": "sk-ant-ort01-test",
                    "expiresAt": 4_102_444_800_000,
                }
            }
        )
    )
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_path))

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-test"
    assert cred.refresh_token == "sk-ant-ort01-test"
    assert cred.source == "claude-cli-file"


def test_load_claude_code_credential_ignores_directory_path(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    cred_dir = tmp_path / "claude-creds-dir"
    cred_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_dir))

    assert load_claude_code_credential() is None


def test_load_claude_code_credential_falls_back_to_default_file_when_override_is_invalid(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    cred_dir = tmp_path / "claude-creds-dir"
    cred_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_dir))

    default_path = tmp_path / ".claude" / ".credentials.json"
    default_path.parent.mkdir()
    default_path.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-default",
                    "refreshToken": "sk-ant-ort01-default",
                    "expiresAt": 4_102_444_800_000,
                }
            }
        )
    )

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-default"
    assert cred.refresh_token == "sk-ant-ort01-default"
    assert cred.source == "claude-cli-file"


def test_load_codex_cli_credential_supports_nested_tokens_shape(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "codex-access-token",
                    "account_id": "acct_123",
                }
            }
        )
    )
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    cred = load_codex_cli_credential()

    assert cred is not None
    assert cred.access_token == "codex-access-token"
    assert cred.account_id == "acct_123"
    assert cred.source == "codex-cli"


def test_load_codex_cli_credential_supports_legacy_top_level_shape(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"access_token": "legacy-access-token"}))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    cred = load_codex_cli_credential()

    assert cred is not None
    assert cred.access_token == "legacy-access-token"
    assert cred.account_id == ""
