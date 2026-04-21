from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import models as models_router
from deerflow.agents.lead_agent.agent import _apply_model_system_prompt_override
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
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip(),
        encoding="utf-8",
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(models_router.router)
    return TestClient(app)


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


def test_model_system_prompt_override_is_injected():
    prompt = _apply_model_system_prompt_override("base prompt", "prefer terse answers")

    assert "base prompt" in prompt
    assert "<model_system_prompt_override>" in prompt
    assert "prefer terse answers" in prompt
