import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from deerflow.models import credential_loader
from deerflow.models.claude_provider import ClaudeChatModel


@pytest.fixture(autouse=True)
def _isolate_credentials(tmp_path, monkeypatch):
    for name in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_CREDENTIALS_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(credential_loader, "_fd_secret_cache", {})


@contextmanager
def _handoff(payload: bytes, monkeypatch) -> Iterator[int]:
    read_fd, write_fd = os.pipe()
    try:
        try:
            os.write(write_fd, payload)
        finally:
            os.close(write_fd)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", str(read_fd))
        yield read_fd
    finally:
        os.close(read_fd)


def _credential_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-file-fallback"}}), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "payload",
    [b"sk-ant-oat01-invalid-byte\xff", b"\xff\xfe" + "sk-ant-oat01-utf16".encode("utf-16-le"), b"sk-ant-oat01-truncated\xe2\x82"],
    ids=["invalid-byte", "utf16", "truncated-utf8"],
)
@pytest.mark.parametrize("fallback", ["none", "override", "default"])
def test_undecodable_descriptor_skips_to_file_credentials(tmp_path, monkeypatch, caplog, payload, fallback):
    if fallback == "override":
        monkeypatch.setenv("CLAUDE_CODE_CREDENTIALS_PATH", str(_credential_file(tmp_path / "override.json")))
    elif fallback == "default":
        _credential_file(tmp_path / ".claude" / ".credentials.json")

    with caplog.at_level(logging.WARNING, logger=credential_loader.__name__), _handoff(payload, monkeypatch) as read_fd:
        # A failed handoff must not strand either the first model or later loads.
        credentials = [credential_loader.load_claude_code_credential() for _ in range(2)]
        os.fstat(read_fd)  # The loader does not own or close the descriptor.

    if fallback == "none":
        assert credentials == [None, None]
    else:
        assert all(cred is not None and cred.access_token == "sk-ant-oat01-file-fallback" and cred.source == "claude-cli-file" for cred in credentials)
    assert credential_loader._fd_secret_cache == {}
    assert "Failed to read CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR" in caplog.text
    assert "sk-ant-oat01" not in caplog.text


def test_claude_models_use_file_fallback_after_undecodable_descriptor(tmp_path, monkeypatch):
    _credential_file(tmp_path / ".claude" / ".credentials.json")

    with _handoff(b"sk-ant-oat01-model-handoff\xff", monkeypatch):
        models = [ClaudeChatModel(model="claude-sonnet-4-6") for _ in range(2)]

    for model in models:
        assert model._is_oauth is True
        assert model._client.api_key is None
        assert model._client.auth_token == "sk-ant-oat01-file-fallback"


def test_valid_descriptor_still_wins_over_file_and_reuses_cached_token(tmp_path, monkeypatch):
    _credential_file(tmp_path / ".claude" / ".credentials.json")

    with _handoff(b"  sk-ant-oat01-valid-handoff\n", monkeypatch):
        credentials = [credential_loader.load_claude_code_credential() for _ in range(2)]

    assert all(cred is not None and cred.access_token == "sk-ant-oat01-valid-handoff" and cred.source == "claude-cli-fd" for cred in credentials)


def test_direct_environment_token_precedes_undecodable_descriptor(monkeypatch, caplog):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-direct")

    with _handoff(b"sk-ant-oat01-bad-handoff\xff", monkeypatch) as read_fd:
        cred = credential_loader.load_claude_code_credential()
        assert os.read(read_fd, 1024) == b"sk-ant-oat01-bad-handoff\xff"

    assert cred is not None and cred.access_token == "sk-ant-oat01-direct" and cred.source == "claude-cli-env"
    assert "Failed to read" not in caplog.text
