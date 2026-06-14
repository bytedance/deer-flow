import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway import authz
from app.gateway.routers import models as models_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(models_router.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _authenticated_models_writer(monkeypatch):
    async def fake_authenticate(request):  # noqa: ARG001
        return authz.AuthContext(
            user=SimpleNamespace(id="test-user"),
            permissions=[*authz._ALL_PERMISSIONS, "models:write"],
        )

    monkeypatch.setattr(authz, "_authenticate", fake_authenticate)


def test_detect_models_reads_openai_compatible_payload(monkeypatch):
    async def fake_validate(base_url):  # noqa: ARG001
        return None

    monkeypatch.setattr(models_router, "_validate_detection_base_url", fake_validate)

    async def fake_get(self, url, headers=None):  # noqa: ARG001
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gpt-4o",
                        "context_length": 128000,
                        "modalities": ["text", "vision"],
                    }
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with _client() as client:
        response = client.post(
            "/api/models/detect",
            json={"base_url": "https://api.example.com/v1", "api_key": "key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint"] == "https://api.example.com/v1/models"
    assert body["models"][0]["id"] == "gpt-4o"
    assert body["models"][0]["context_length"] == 128000
    assert body["models"][0]["supports_vision"] is True


def test_detect_models_returns_safe_error_detail(monkeypatch):
    async def fake_validate(base_url):  # noqa: ARG001
        return None

    async def fake_get(self, url, headers=None):  # noqa: ARG001
        raise httpx.ConnectError("internal dial failure with token=secret", request=httpx.Request("GET", url))

    monkeypatch.setattr(models_router, "_validate_detection_base_url", fake_validate)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with _client() as client:
        response = client.post(
            "/api/models/detect",
            json={"base_url": "https://api.example.com/v1", "api_key": "key"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to detect models from provider"
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_validate_detection_base_url_uses_async_dns(monkeypatch):
    loop = asyncio.get_running_loop()
    getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("93.184.216.34", 0))])
    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)

    await models_router._validate_detection_base_url("https://api.example.com/v1")

    getaddrinfo.assert_awaited_once_with("api.example.com", None)


def test_detect_models_rejects_localhost_url():
    with _client() as client:
        response = client.post(
            "/api/models/detect",
            json={"base_url": "http://127.0.0.1:11434/v1", "api_key": "key"},
        )

    assert response.status_code == 422
    assert "public address" in response.json()["detail"]
