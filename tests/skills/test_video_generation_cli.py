"""The video CLI must expose generation failures to its shell caller."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import requests

SCRIPT = Path(__file__).resolve().parents[2] / "skills/public/video-generation/scripts/generate.py"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "GEMINI_API_KEY",
        "MINIMAX_API_KEY",
        "BYTEPLUS_AGENTPLAN_API_KEY",
        "VIDEO_GENERATION_PROVIDER",
        "MINIMAX_API_HOST",
        "MINIMAX_VIDEO_RESOLUTION",
        "MINIMAX_VIDEO_DURATION",
        "BYTEPLUS_AGENTPLAN_BASE_URL",
        "BYTEPLUS_AGENTPLAN_VIDEO_MODEL",
        "BYTEPLUS_AGENTPLAN_VIDEO_RESOLUTION",
        "BYTEPLUS_AGENTPLAN_VIDEO_DURATION",
        "BYTEPLUS_AGENTPLAN_GENERATE_AUDIO",
        "BYTEPLUS_AGENTPLAN_VIDEO_DOWNLOAD_HOSTS",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("missing-prompt", "Error while generating video:"),
        ("no-credentials", "No credentials found"),
        ("gemini", "GEMINI_API_KEY is not set"),
        ("google", "GEMINI_API_KEY is not set"),
        ("minimax", "MINIMAX_API_KEY is not set"),
        ("byteplus_agentplan", "BYTEPLUS_AGENTPLAN_API_KEY is not set"),
        ("unknown", "Unknown video provider"),
    ],
)
def test_cli_generation_failure_is_nonzero(monkeypatch, tmp_path, case, error):
    prompt = tmp_path / "prompt.json"
    if case != "missing-prompt":
        prompt.write_text('{"prompt": "A cat runs"}', encoding="utf-8")
    if case not in ("missing-prompt", "no-credentials"):
        monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", case)
    output = tmp_path / "video.mp4"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--prompt-file", str(prompt), "--output-file", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert error in result.stderr
    assert result.stdout == ""
    assert not output.exists()


@pytest.mark.parametrize("provider", ["gemini", "minimax", "byteplus_agentplan"])
@pytest.mark.parametrize("http_error", [False, True], ids=["success", "http-error"])
def test_cli_provider_result(monkeypatch, tmp_path, capsys, provider, http_error):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("BYTEPLUS_AGENTPLAN_API_KEY", "test-key")
    download_urls = {
        "minimax": "https://filecdn.minimax.chat/video.mp4",
        "gemini": "https://generativelanguage.googleapis.com/video.mp4",
        "byteplus_agentplan": "https://bucket.tos-ap-southeast-1.volces.com/video.mp4",
    }
    download_url = download_urls[provider]
    prompt = tmp_path / "prompt.json"
    prompt.write_text('{"prompt": "A cat runs"}', encoding="utf-8")
    output = tmp_path / "video.mp4"
    original = b"existing video"
    output.write_bytes(original)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--prompt-file", str(prompt), "--output-file", str(output)])

    def response(payload=None, *, status=200, content=b""):
        result = requests.Response()
        result.status_code = status
        result._content = json.dumps(payload).encode("utf-8") if payload is not None else content
        return result

    def post(*args, **kwargs):
        if http_error:
            return response(status=500)
        if provider == "minimax":
            return response({"task_id": "task-1"})
        if provider == "byteplus_agentplan":
            return response({"id": "cgt-task-1"})
        return response({"name": "operations/test"})

    def get(url, **kwargs):
        if url.endswith("/query/video_generation"):
            return response({"status": "Success", "file_id": "file-1"})
        if url.endswith("/files/retrieve"):
            return response({"file": {"download_url": download_url}})
        if url.endswith("/contents/generations/tasks/cgt-task-1"):
            return response({"id": "cgt-task-1", "status": "succeeded", "content": {"video_url": download_url}})
        if url.endswith("/operations/test"):
            return response({"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": download_url}}]}}})
        assert url == download_url
        return response(content=b"test video")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)

    if http_error:
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        assert exc.value.code == 1
        assert output.read_bytes() == original
        captured = capsys.readouterr()
        assert "Error while generating video:" in captured.err
        assert captured.out == ""
    else:
        runpy.run_path(str(SCRIPT), run_name="__main__")
        assert output.read_bytes() == b"test video"
        captured = capsys.readouterr()
        assert "generated successfully" in captured.out
        assert captured.err == ""
