import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway import authz
from app.gateway.routers import models as models_router
from deerflow.config.app_config import reset_app_config


def _write_config(path: Path) -> None:
    path.write_text(
        """
config_version: 7
log_level: info
models:
  - name: existing
    display_name: Existing
    use: langchain_openai:ChatOpenAI
    model: existing-model
    api_key: old-key
  - name: second
    display_name: Second
    use: langchain_openai:ChatOpenAI
    model: second-model
    api_key: second-key
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip(),
        encoding="utf-8",
    )


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


def test_create_model_writes_config_and_redacts_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    reset_app_config()

    with _client() as client:
        response = client.post(
            "/api/models",
            json={
                "name": "My GPT",
                "model": "gpt-4o",
                "display_name": "My GPT",
                "base_url": "https://api.example.com/v1",
                "api_key": "secret-key",
                "context_length": 128000,
                "temperature": 0.7,
                "supports_vision": True,
                "modalities": ["text", "vision"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "my-gpt"
    assert body["base_url"] == "https://api.example.com/v1"
    assert "api_key" not in body
    saved = config_path.read_text(encoding="utf-8")
    assert "name: my-gpt" in saved
    assert "api_key: secret-key" in saved


def test_update_model_keeps_existing_api_key_when_blank(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    reset_app_config()

    with _client() as client:
        response = client.put(
            "/api/models/existing",
            json={
                "name": "existing",
                "model": "new-model",
                "display_name": "Existing New",
                "api_key": "",
            },
        )

    assert response.status_code == 200
    saved = config_path.read_text(encoding="utf-8")
    assert "model: new-model" in saved
    assert "api_key: old-key" in saved


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


def test_update_model_rejects_duplicate_target_name(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    reset_app_config()

    with _client() as client:
        response = client.put(
            "/api/models/existing",
            json={
                "name": "second",
                "model": "new-model",
                "display_name": "Duplicate",
                "api_key": "",
            },
        )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_delete_model_rejects_last_model(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
config_version: 7
log_level: info
models:
  - name: only
    use: langchain_openai:ChatOpenAI
    model: only-model
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    reset_app_config()

    with _client() as client:
        response = client.delete("/api/models/only")

    assert response.status_code == 409
    assert "last configured model" in response.json()["detail"]
