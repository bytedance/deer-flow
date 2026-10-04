"""Exercise the manual OAuth exporter with synthetic Keychain responses."""

import importlib.util
import json
import shlex
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def exporter(monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts" / "export_claude_code_oauth.py"
    spec = importlib.util.spec_from_file_location("claude_keychain_export", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    return module


def mock_keychain(exporter, monkeypatch, payload):
    response = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(exporter, "subprocess", SimpleNamespace(run=lambda *args, **kwargs: response))


INVALID_CONTAINERS = [
    None,
    [],
    "synthetic-secret",
    42,
    {"claudeAiOauth": None},
    {"claudeAiOauth": []},
    {"claudeAiOauth": "synthetic-secret"},
    {"claudeAiOauth": {"accessToken": None}},
    {"claudeAiOauth": {"accessToken": True}},
    {"claudeAiOauth": {"accessToken": 42}},
    {"claudeAiOauth": {"accessToken": ["synthetic-secret"]}},
    {"claudeAiOauth": {"accessToken": {"value": "synthetic-secret"}}},
    {"claudeAiOauth": {"accessToken": ""}},
    {"claudeAiOauth": {"accessToken": " \t\n"}},
]


@pytest.mark.parametrize("payload", INVALID_CONTAINERS)
@pytest.mark.parametrize("action", ["print_token", "print_export", "write_credentials"])
def test_invalid_keychain_container_fails_without_exporting(exporter, monkeypatch, tmp_path, capsys, payload, action):
    mock_keychain(exporter, monkeypatch, payload)
    destination = tmp_path / "credentials.json"
    args = Namespace(service="synthetic-service", account="synthetic-account", show_target=False, print_token=False, print_export=False, write_credentials=None)
    setattr(args, action, destination if action == "write_credentials" else True)
    monkeypatch.setattr(exporter, "parse_args", lambda: args)

    assert exporter.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Claude Code Keychain item did not contain claudeAiOauth.accessToken.\n"
    assert "synthetic-secret" not in captured.err
    assert not destination.exists()


def test_valid_container_preserves_all_export_modes(exporter, monkeypatch, tmp_path, capsys):
    token = "synthetic-token'with-shell-quote"
    payload = {"claudeAiOauth": {"accessToken": token, "refreshToken": "synthetic-refresh", "expiresAt": 123}, "metadata": "preserved"}
    mock_keychain(exporter, monkeypatch, payload)
    destination = tmp_path / "credentials.json"
    args = Namespace(service="synthetic-service", account="synthetic-account", show_target=False, print_token=True, print_export=True, write_credentials=destination)
    monkeypatch.setattr(exporter, "parse_args", lambda: args)

    assert exporter.main() == 0

    captured = capsys.readouterr()
    assert captured.out == f"{token}\nexport CLAUDE_CODE_OAUTH_TOKEN={shlex.quote(token)}\n"
    assert captured.err == f"Wrote Claude Code credentials to {destination}\n"
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
