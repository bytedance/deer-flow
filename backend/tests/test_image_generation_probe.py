"""Provider probes return bounded result codes without returning remote bodies."""

import base64

import httpx

from app.gateway import image_generation_probe as probe
from deerflow.config.image_generation import ImageGenerationProfile


def profile():
    return ImageGenerationProfile(provider="openai", model="image-model", base_url="https://images.example/v1", api_key="synthetic-secret")


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


def test_unsupported_edit_and_invalid_response(monkeypatch):
    def not_found(_request):
        return httpx.Response(404)

    client_with(not_found, monkeypatch)
    assert probe.probe_image_profile(profile(), "edit") == "unsupported_edit"

    def empty(_request):
        return httpx.Response(200, json={"data": []})

    client_with(empty, monkeypatch)
    assert probe.probe_image_profile(profile(), "generation") == "invalid_response"
