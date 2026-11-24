"""Provider probes return bounded result codes without returning remote bodies."""

import base64
import struct
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.gateway import image_generation_probe as probe
from deerflow.config.image_generation import ImageGenerationProfile


def profile():
    return ImageGenerationProfile(provider="openai", model="image-model", base_url="https://images.example/v1", api_key="synthetic-secret")


def provider_profile(provider):
    return ImageGenerationProfile(provider=provider, model="image-model", base_url="https://images.example/v1" if provider == "openai" else None, api_key="synthetic-secret")


def client_with(handler, monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(probe.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_generation_and_edit_use_distinct_endpoints(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(probe._solid_png()).decode()}]})

    client_with(handler, monkeypatch)
    assert probe.probe_image_profile(profile(), "generation") == "success"
    assert probe.probe_image_profile(profile(), "edit") == "success"
    assert [request.url.path for request in calls] == ["/v1/images/generations", "/v1/images/edits"]
    assert all(request.headers["Authorization"] == "Bearer synthetic-secret" for request in calls)


def test_status_and_malformed_provider_response_are_redacted(monkeypatch):
    def denied(_request):
        return httpx.Response(401, json={"error": "synthetic-secret must never be returned"})

    client_with(denied, monkeypatch)
    result = probe.probe_image_profile(profile(), "generation")
    assert result == "authentication_failed"
    assert "synthetic-secret" not in result


@pytest.mark.parametrize("status_code,operation", [(500, "generation"), (501, "edit"), (502, "generation"), (503, "generation"), (504, "generation")])
def test_provider_outage_is_unreachable_without_exposing_response(monkeypatch, status_code, operation):
    client_with(lambda _request: httpx.Response(status_code, json={"error": "synthetic-secret must stay private"}), monkeypatch)

    result = probe.probe_image_profile(profile(), operation)

    assert result == "unreachable"
    assert "synthetic-secret" not in result


def test_unsupported_edit_and_invalid_response(monkeypatch):
    def not_found(_request):
        return httpx.Response(404)

    client_with(not_found, monkeypatch)
    assert probe.probe_image_profile(profile(), "edit") == "unsupported_edit"

    def empty(_request):
        return httpx.Response(200, json={"data": []})

    client_with(empty, monkeypatch)
    assert probe.probe_image_profile(profile(), "generation") == "invalid_response"


@pytest.mark.parametrize("provider", ["openai", "gemini", "minimax"])
@pytest.mark.parametrize("operation", ["generation", "edit"])
def test_truncated_image_is_not_recorded_as_success(monkeypatch, provider, operation):
    signature_only = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    payload = {
        "openai": {"data": [{"b64_json": signature_only}]},
        "gemini": {"candidates": [{"content": {"parts": [{"inlineData": {"data": signature_only}}]}}]},
        "minimax": {"data": {"image_base64": [signature_only]}},
    }[provider]
    client_with(lambda _request: httpx.Response(200, json=payload), monkeypatch)
    assert probe.probe_image_profile(provider_profile(provider), operation) == "invalid_response"


@pytest.mark.parametrize("provider", ["openai", "gemini", "minimax"])
def test_png_checksum_failure_returns_invalid_response(monkeypatch, provider):
    png = bytearray(probe._solid_png())
    idat_offset = 8 + 4 + 4 + 13 + 4
    idat_length = struct.unpack_from(">I", png, idat_offset)[0]
    png[idat_offset + 8 + idat_length] ^= 1
    with Image.open(BytesIO(png)) as image:
        with pytest.raises(SyntaxError, match="bad header checksum"):
            image.verify()

    encoded = base64.b64encode(png).decode("ascii")
    payload = {
        "openai": {"data": [{"b64_json": encoded}]},
        "gemini": {"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded}}]}}]},
        "minimax": {"data": {"image_base64": [encoded]}},
    }[provider]
    client_with(lambda _request: httpx.Response(200, json=payload), monkeypatch)
    assert probe.probe_image_profile(provider_profile(provider), "generation") == "invalid_response"


@pytest.mark.parametrize("provider", ["openai", "gemini", "minimax"])
@pytest.mark.parametrize("operation", ["generation", "edit"])
def test_oversized_provider_response_is_rejected_while_streaming(monkeypatch, provider, operation):
    class OversizedStream(httpx.SyncByteStream):
        def __init__(self):
            self.chunks_read = 0

        def __iter__(self):
            for _ in range(4):
                self.chunks_read += 1
                yield b"x" * (probe.MAX_PROBE_RESPONSE_BYTES // 2)

    stream = OversizedStream()
    client_with(lambda _request: httpx.Response(200, stream=stream), monkeypatch)
    assert probe.probe_image_profile(provider_profile(provider), operation) == "invalid_response"
    assert stream.chunks_read == 3


def test_compressed_probe_response_is_rejected_before_read(monkeypatch):
    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("compressed response body was read")

    client_with(lambda _request: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=UnreadableStream()), monkeypatch)
    assert probe.probe_image_profile(profile(), "generation") == "invalid_response"
