"""Unit tests for scripts/mineru_client.py."""
import io
import urllib.error
from unittest import mock

import pytest

from mineru_client import MinerUError, ocr_to_markdown


def test_ocr_to_markdown_sends_post_with_file_and_returns_markdown(mineru_env, tmp_path):
    fake_file = tmp_path / "scan.png"
    fake_file.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    fake_response = io.BytesIO(b'{"markdown": "# Page 1\\n\\nHello OCR world"}')
    fake_response.headers = {"Content-Type": "application/json"}

    with mock.patch("urllib.request.urlopen", return_value=fake_response) as m_open:
        result = ocr_to_markdown(str(fake_file))

    assert result == "# Page 1\n\nHello OCR world"
    # Verify the request was a POST to the right URL with the right headers
    call_args = m_open.call_args
    request_obj = call_args.args[0]
    assert request_obj.full_url == "http://mineru.lan:8000/ocr"
    assert request_obj.get_method() == "POST"
    assert request_obj.get_header("Authorization") == "Bearer test-key-abc123"
    assert request_obj.get_header("Content-type", "").startswith("multipart/form-data")


def test_ocr_to_markdown_raises_when_url_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MINERU_API_URL", raising=False)
    monkeypatch.setenv("MINERU_API_KEY", "k")
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    with pytest.raises(MinerUError, match="MINERU_API_URL is not set"):
        ocr_to_markdown(str(fake))


def test_ocr_to_markdown_raises_when_key_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_API_URL", "http://x")
    monkeypatch.delenv("MINERU_API_KEY", raising=False)
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    with pytest.raises(MinerUError, match="MINERU_API_KEY is not set"):
        ocr_to_markdown(str(fake))


def test_ocr_to_markdown_raises_mineru_error_on_500(mineru_env, tmp_path):
    fake = tmp_path / "x.png"
    fake.write_bytes(b"x")
    err = urllib.error.HTTPError(
        "http://mineru.lan:8000/ocr", 500, "Internal Server Error", {}, io.BytesIO(b"oops")
    )
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(MinerUError) as exc_info:
            ocr_to_markdown(str(fake))
    assert exc_info.value.status == 500
    assert exc_info.value.body == "oops"
