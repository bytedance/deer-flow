"""Malformed Claude credential expiry must not select an unusable source."""

import json

import doctor
import pytest

from deerflow.models.credential_loader import load_claude_code_credential


@pytest.fixture(autouse=True)
def isolate_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_CREDENTIALS_PATH"):
        monkeypatch.delenv(name, raising=False)


def write_credentials(path, expiry):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"claudeAiOauth":{"accessToken":"test-token","expiresAt":' + expiry + "}}", encoding="utf-8")


@pytest.mark.parametrize("expiry", ["NaN", "Infinity", "-Infinity", "1e309", "-1e309", "false", "true"])
@pytest.mark.parametrize("consumer", ["runtime", "doctor"])
def test_invalid_expiry_is_rejected(tmp_path, monkeypatch, expiry, consumer):
    path = tmp_path / "credentials.json"
    write_credentials(path, expiry)
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(path))
    if consumer == "runtime":
        assert load_claude_code_credential() is None
    else:
        assert doctor._claude_credentials_file_has_access_token(path) is False


@pytest.mark.parametrize("expiry", ["NaN", "Infinity", "-Infinity", "1e309", "-1e309", "false", "true"])
def test_invalid_override_falls_back_to_default(tmp_path, monkeypatch, expiry):
    path = tmp_path / "override.json"
    write_credentials(path, expiry)
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(path))
    default = tmp_path / ".claude" / ".credentials.json"
    write_credentials(default, "4102444800000")

    credential = load_claude_code_credential()

    assert credential is not None
    assert credential.source == "claude-cli-file"
    assert credential.expires_at == 4102444800000


@pytest.mark.parametrize("expiry", [0, -1, 4102444800000, 4102444800000.5, 10**400])
def test_finite_expiry_contract_is_preserved(tmp_path, monkeypatch, expiry):
    path = tmp_path / "credentials.json"
    write_credentials(path, json.dumps(expiry))
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(path))
    credential = load_claude_code_credential()
    assert credential is not None
    assert credential.expires_at == expiry
    assert doctor._claude_credentials_file_has_access_token(path) is True


def test_missing_expiry_still_means_unknown(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    path.write_text('{"claudeAiOauth":{"accessToken":"test-token"}}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(path))
    assert load_claude_code_credential().expires_at == 0
    assert doctor._claude_credentials_file_has_access_token(path) is True
