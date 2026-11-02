"""Gemini 下载凭据不得跟随媒体 URL 跨越 API 的来源边界。"""

import sys
from pathlib import Path
from typing import Any

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import load  # noqa: E402

vid = load("video-generation")
API_URL = "https://generativelanguage.googleapis.com/v1beta/files/video:download"


@pytest.mark.parametrize(
    "destination",
    [
        "https://media.example/video.mp4",
        "https://generativelanguage.googleapis.com.evil.example/video",
        "https://generativelanguage.googleapis.com:444/video",
    ],
)
def test_external_download_never_receives_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, destination: str
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    seen = []

    def send(
        self: requests.adapters.HTTPAdapter,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        seen.append(request)
        response = requests.Response()
        response.status_code = 200
        response._content = b"video"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    vid.download(destination, str(tmp_path / "video.mp4"))
    assert len(seen) == 1
    assert "x-goog-api-key" not in seen[0].headers


def test_redirect_strips_key_but_still_downloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    seen = []

    def send(
        self: requests.adapters.HTTPAdapter,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        seen.append(request)
        response = requests.Response()
        response.status_code = 302 if len(seen) == 1 else 200
        response.headers["Location"] = "https://media.example/video.mp4"
        response._content = b"video"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    output = tmp_path / "video.mp4"
    vid.download(API_URL, str(output))
    assert len(seen) == 2
    assert seen[0].headers["x-goog-api-key"] == "synthetic-test-key"
    assert "x-goog-api-key" not in seen[1].headers
    assert output.read_bytes() == b"video"


@pytest.mark.parametrize(
    "location",
    ["http://media.example/video", "https://user:password@media.example/video"],
)
def test_unsafe_redirect_rejected_before_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, location: str
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    seen = []

    def send(
        self: requests.adapters.HTTPAdapter,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        seen.append(request)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = location
        response._content = b""
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    output = tmp_path / "video.mp4"
    with pytest.raises(ValueError, match="HTTPS"):
        vid.download(API_URL, str(output))
    assert len(seen) == 1
    assert not output.exists()


def test_same_origin_relative_redirects_are_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    seen = []

    def send(
        self: requests.adapters.HTTPAdapter,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        seen.append(request)
        assert request.headers["x-goog-api-key"] == "synthetic-test-key"
        assert request.url.startswith("https://generativelanguage.googleapis.com/")
        response = requests.Response()
        response.status_code = 307
        response.headers["Location"] = "/next"
        response._content = b""
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    output = tmp_path / "video.mp4"
    with pytest.raises(requests.TooManyRedirects):
        vid.download(API_URL, str(output))
    assert len(seen) == 11
    assert not output.exists()
