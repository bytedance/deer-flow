"""Exercise the documented podcast command, including its process status."""

import base64
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import requests

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/podcast-generation/scripts/generate.py"
)
SCRIPT_DATA = {"lines": [{"speaker": "male", "paragraph": "Hello"}]}


@pytest.fixture(autouse=True)
def isolated_provider_env(monkeypatch):
    for name in (
        "PODCAST_GENERATION_PROVIDER",
        "VOLCENGINE_TTS_APPID",
        "VOLCENGINE_TTS_ACCESS_TOKEN",
        "MINIMAX_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIMAX_TTS_MAX_RETRIES", "0")


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("missing-file", "FileNotFoundError"),
        ("invalid-json", "JSONDecodeError"),
        ("empty-script", "Script contains no lines"),
        ("no-credentials", "No credentials found"),
        ("volcengine", "VOLCENGINE_TTS_APPID"),
        ("minimax", "MINIMAX_API_KEY is not set"),
    ],
)
def test_cli_failure_status(monkeypatch, tmp_path, case, error):
    script = tmp_path / "script.json"
    if case != "missing-file":
        data = {"lines": []} if case == "empty-script" else SCRIPT_DATA
        script.write_text(
            "{" if case == "invalid-json" else json.dumps(data), encoding="utf-8"
        )
    if case in ("volcengine", "minimax"):
        monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", case)
    output = tmp_path / "episode.mp3"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--script-file",
            str(script),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Error generating podcast:" in result.stderr
    assert error in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("provider", ["volcengine", "minimax"])
@pytest.mark.parametrize(
    "outcome", ["success", "http-error", "connection-error", "empty-audio"]
)
def test_cli_provider_outcome(monkeypatch, tmp_path, capsys, provider, outcome):
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", provider)
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "test-app")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT_DATA), encoding="utf-8")
    output = tmp_path / "episode.mp3"
    output.write_bytes(b"previous episode")
    transcript = tmp_path / "episode.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--script-file",
            str(script),
            "--output-file",
            str(output),
            "--transcript-file",
            str(transcript),
        ],
    )

    def post(*args, **kwargs):
        if outcome == "connection-error":
            raise requests.ConnectionError("provider unavailable")
        response = requests.Response()
        response.status_code = 403 if outcome == "http-error" else 200
        audio = b"" if outcome == "empty-audio" else b"new episode"
        if provider == "volcengine":
            payload = {"code": 3000, "data": base64.b64encode(audio).decode("ascii")}
        else:
            payload = {"base_resp": {"status_code": 0}, "data": {"audio": audio.hex()}}
        response._content = json.dumps(payload).encode("utf-8")
        return response

    monkeypatch.setattr(requests, "post", post)

    if outcome == "success":
        runpy.run_path(str(SCRIPT), run_name="__main__")
        assert output.read_bytes() == b"new episode"
        assert "**Host (Male)**: Hello" in transcript.read_text(encoding="utf-8")
        captured = capsys.readouterr()
        assert "Successfully generated podcast" in captured.out
        assert captured.err == ""
    else:
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        assert exc.value.code == 1
        assert output.read_bytes() == b"previous episode"
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error generating podcast:" in captured.err


def test_cli_argument_error_remains_nonzero():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert "--script-file" in result.stderr
