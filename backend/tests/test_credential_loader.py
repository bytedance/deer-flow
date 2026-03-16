import json

from deerflow.models.credential_loader import (
    _claude_code_keychain_service_name,
    load_claude_code_credential,
    load_codex_cli_credential,
)


def test_load_claude_code_credential_from_override_path(tmp_path, monkeypatch):
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
    cred_dir = tmp_path / "claude-creds-dir"
    cred_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_dir))

    assert load_claude_code_credential() is None


def test_claude_code_keychain_service_name_defaults(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_CUSTOM_OAUTH_URL", raising=False)
    monkeypatch.delenv("USE_LOCAL_OAUTH", raising=False)
    monkeypatch.delenv("LOCAL_BRIDGE", raising=False)
    monkeypatch.delenv("USE_STAGING_OAUTH", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    assert _claude_code_keychain_service_name() == "Claude Code-credentials"


def test_load_claude_code_credential_from_keychain(monkeypatch):
    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-keychain",
                    "refreshToken": "sk-ant-ort01-keychain",
                    "expiresAt": 4_102_444_800_000,
                }
            }
        )

    monkeypatch.delenv("CLAUDE_CODE_CREDENTIALS_PATH", raising=False)
    monkeypatch.setattr("deerflow.models.credential_loader.platform.system", lambda: "Darwin")
    monkeypatch.setattr("deerflow.models.credential_loader.subprocess.run", lambda *args, **kwargs: Result())

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-keychain"
    assert cred.refresh_token == "sk-ant-ort01-keychain"
    assert cred.source == "claude-cli-keychain"


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
