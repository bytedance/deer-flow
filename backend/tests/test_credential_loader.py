import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from deerflow.models import credential_loader
from deerflow.models.claude_provider import ClaudeChatModel
from deerflow.models.credential_loader import (
    load_claude_code_credential,
    load_codex_cli_credential,
)
from deerflow.models.openai_codex_provider import CodexChatModel


@pytest.fixture(autouse=True)
def _isolate_file_descriptor_secret_cache(monkeypatch):
    # Descriptor numbers are recycled across tests, so a shared cache would leak tokens.
    monkeypatch.setattr(credential_loader, "_fd_secret_cache", {})


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


def _pipe_with_secret(secret: bytes) -> int:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    return read_fd


def test_load_claude_code_credential_reuses_drained_file_descriptor(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    read_fd = _pipe_with_secret(b"sk-ant-oat01-fd")
    try:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))

        first = load_claude_code_credential()
        second = load_claude_code_credential()
    finally:
        os.close(read_fd)

    assert first is not None
    assert second is not None
    assert second.access_token == first.access_token == "sk-ant-oat01-fd"
    assert second.source == "claude-cli-fd"


def test_load_claude_code_credential_rereads_when_file_descriptor_changes(monkeypatch):
    _clear_claude_code_env(monkeypatch)

    first_fd = _pipe_with_secret(b"sk-ant-oat01-first")
    second_fd = _pipe_with_secret(b"sk-ant-oat01-second")
    try:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(first_fd))
        first = load_claude_code_credential()
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(second_fd))
        second = load_claude_code_credential()
    finally:
        os.close(first_fd)
        os.close(second_fd)

    assert first is not None and first.access_token == "sk-ant-oat01-first"
    assert second is not None and second.access_token == "sk-ant-oat01-second"


def test_load_claude_code_credential_survives_closed_file_descriptor(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    read_fd = _pipe_with_secret(b"sk-ant-oat01-fd")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))
    first = load_claude_code_credential()
    # Closing a drained handoff must not strand the models built after it.
    os.close(read_fd)
    second = load_claude_code_credential()

    assert first is not None and first.access_token == "sk-ant-oat01-fd"
    assert second is not None and second.access_token == "sk-ant-oat01-fd"


def test_concurrent_loads_drain_file_descriptor_once(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    read_fd = _pipe_with_secret(b"sk-ant-oat01-fd")
    real_read = os.read
    handoff_reads = []

    def slow_read(fd, length):
        if fd == read_fd:
            handoff_reads.append(fd)
            # Hold the first reader inside os.read so an unguarded second reader drains EOF.
            time.sleep(0.1)
        return real_read(fd, length)

    monkeypatch.setattr(os, "read", slow_read)
    barrier = threading.Barrier(2)

    def load():
        barrier.wait()
        return load_claude_code_credential()

    try:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))
        with ThreadPoolExecutor(max_workers=2) as pool:
            creds = list(pool.map(lambda _: load(), range(2)))
    finally:
        os.close(read_fd)

    assert [cred.access_token if cred else None for cred in creds] == ["sk-ant-oat01-fd"] * 2
    assert handoff_reads == [read_fd]


def test_claude_chat_model_instances_share_file_descriptor_token(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    read_fd = _pipe_with_secret(b"sk-ant-oat01-fd")
    try:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))
        # Each run builds fresh models (lead agent, title, subagents) from the same handoff.
        models = [ClaudeChatModel(model="claude-sonnet-4-6") for _ in range(2)]
    finally:
        os.close(read_fd)

    for model in models:
        assert model._is_oauth is True
        assert model._client.api_key is None
        assert model._client.auth_token == "sk-ant-oat01-fd"


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
    # Redirect HOME so the default ~/.claude/.credentials.json doesn't exist
    monkeypatch.setenv("HOME", str(tmp_path))
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


@pytest.mark.parametrize(
    "payload",
    [
        {"claudeAiOauth": None},
        {"claudeAiOauth": "sk-ant-oat01-raw"},
        {"claudeAiOauth": []},
        {"claudeAiOauth": 5},
        [],
    ],
)
def test_load_claude_code_credential_ignores_malformed_oauth_container(tmp_path, monkeypatch, payload):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_file))

    assert load_claude_code_credential() is None


def test_load_claude_code_credential_falls_back_to_default_when_override_container_is_malformed(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    override_path = tmp_path / "credentials.json"
    override_path.write_text(json.dumps({"claudeAiOauth": None}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(override_path))

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
        ),
        encoding="utf-8",
    )

    cred = load_claude_code_credential()

    assert cred is not None
    assert cred.access_token == "sk-ant-oat01-default"
    assert cred.refresh_token == "sk-ant-ort01-default"
    assert cred.source == "claude-cli-file"


@pytest.mark.parametrize(
    "expires_at",
    [
        "1773430695128",
        None,
        [],
        {},
    ],
)
def test_load_claude_code_credential_ignores_non_numeric_expires_at(tmp_path, monkeypatch, expires_at):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-test", "expiresAt": expires_at}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(cred_file))

    assert load_claude_code_credential() is None


def test_load_claude_code_credential_falls_back_to_default_when_override_expires_at_is_non_numeric(tmp_path, monkeypatch):
    _clear_claude_code_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    override_path = tmp_path / "credentials.json"
    override_path.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-override", "expiresAt": "1773430695128"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(override_path))

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
        ),
        encoding="utf-8",
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


@pytest.mark.parametrize("payload", [[], "codex-access-token", 5])
def test_load_codex_cli_credential_ignores_non_object_auth_file(tmp_path, monkeypatch, payload):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps(payload))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    assert load_codex_cli_credential() is None


def test_codex_chat_model_reports_missing_credential_for_non_object_auth_file(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps([]))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    with pytest.raises(ValueError, match="Codex CLI credential not found"):
        CodexChatModel(model="gpt-5.4")


def test_load_codex_cli_credential_defaults_null_account_id(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "codex-access-token",
                    "account_id": None,
                }
            }
        )
    )
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    cred = load_codex_cli_credential()

    assert cred is not None
    assert cred.access_token == "codex-access-token"
    assert cred.account_id == ""


def test_load_codex_cli_credential_ignores_non_string_account_id(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "codex-access-token",
                    "account_id": 12345,
                }
            }
        )
    )
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    cred = load_codex_cli_credential()

    assert cred is not None
    assert cred.access_token == "codex-access-token"
    assert cred.account_id == ""
