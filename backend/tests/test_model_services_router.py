from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import model_services, models
from deerflow.config.app_config import reset_app_config
from deerflow.config.model_services_config import reset_model_services_config


def _write_base_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    model_services_path = tmp_path / "model_services.json"

    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": "static-model",
                        "display_name": "Static Model",
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-4o-mini",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    model_services_path.write_text(json.dumps({"providers": [], "defaults": {}}), encoding="utf-8")
    return config_path, extensions_path, model_services_path


def test_put_model_services_persists_and_updates_models(tmp_path, monkeypatch):
    config_path, extensions_path, model_services_path = _write_base_files(tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH", str(model_services_path))
    reset_app_config()
    reset_model_services_config()

    app = FastAPI()
    app.include_router(model_services.router)
    app.include_router(models.router)

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/model-services",
                json={
                    "providers": [
                        {
                            "id": "relay",
                            "name": "Relay",
                            "provider_type": "openai-compatible",
                            "enabled": True,
                            "base_url": "https://relay.example/v1",
                            "api_key": "relay-key",
                            "api_key_mode": "replace",
                            "headers": {},
                            "homepage": "https://relay.example",
                            "notes": "",
                            "modalities": ["text", "image"],
                            "models": [
                                {
                                    "id": "relay-gpt-5",
                                    "name": "relay-gpt-5",
                                    "display_name": "Relay GPT-5",
                                    "model": "gpt-5",
                                    "enabled": True,
                                    "modalities": ["text"],
                                    "supports_thinking": True,
                                    "supports_reasoning_effort": True,
                                    "supports_vision": False,
                                }
                            ],
                        }
                    ],
                    "defaults": {"text_model_name": "relay-gpt-5"},
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["providers"][0]["api_key_configured"] is True
            assert payload["providers"][0]["api_key_masked"]

            models_response = client.get("/api/models")
            assert models_response.status_code == 200
            model_names = [item["name"] for item in models_response.json()["models"]]
            assert model_names[0] == "relay-gpt-5"
            assert "static-model" in model_names
    finally:
        reset_app_config()
        reset_model_services_config()


def test_put_model_services_rejects_duplicate_model_names(tmp_path, monkeypatch):
    config_path, extensions_path, model_services_path = _write_base_files(tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH", str(model_services_path))
    reset_app_config()
    reset_model_services_config()

    app = FastAPI()
    app.include_router(model_services.router)
    app.include_router(models.router)

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/model-services",
                json={
                    "providers": [
                        {
                            "id": "relay",
                            "name": "Relay",
                            "provider_type": "openai-compatible",
                            "enabled": True,
                            "base_url": "https://relay.example/v1",
                            "api_key": "relay-key",
                            "api_key_mode": "replace",
                            "headers": {},
                            "homepage": "",
                            "notes": "",
                            "modalities": ["text"],
                            "models": [
                                {
                                    "id": "dup",
                                    "name": "static-model",
                                    "display_name": "Duplicate",
                                    "model": "gpt-5",
                                    "enabled": True,
                                    "modalities": ["text"],
                                    "supports_thinking": False,
                                    "supports_reasoning_effort": False,
                                    "supports_vision": False,
                                }
                            ],
                        }
                    ],
                    "defaults": {},
                },
            )
            assert response.status_code == 400
    finally:
        reset_app_config()
        reset_model_services_config()


def test_test_and_sync_provider_endpoints(tmp_path, monkeypatch):
    config_path, extensions_path, model_services_path = _write_base_files(tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH", str(model_services_path))
    reset_app_config()
    reset_model_services_config()

    app = FastAPI()
    app.include_router(model_services.router)
    app.include_router(models.router)

    try:
        with TestClient(app) as client:
            client.put(
                "/api/model-services",
                json={
                    "providers": [
                        {
                            "id": "relay",
                            "name": "Relay",
                            "provider_type": "openai-compatible",
                            "enabled": True,
                            "base_url": "https://relay.example/v1",
                            "api_key": "relay-key",
                            "api_key_mode": "replace",
                            "headers": {},
                            "homepage": "",
                            "notes": "",
                            "modalities": ["text"],
                            "models": [],
                        }
                    ],
                    "defaults": {},
                },
            )

            with patch(
                "app.gateway.routers.model_services._request_json",
                side_effect=[
                    {"data": [{"id": "gpt-5"}]},
                    {"id": "chatcmpl-test"},
                    {"data": [{"id": "gpt-5"}, {"id": "gpt-4o-mini"}]},
                ],
            ):
                test_response = client.post("/api/model-services/providers/relay/test")
                assert test_response.status_code == 200
                assert test_response.json()["ok"] is True

                sync_response = client.post("/api/model-services/providers/relay/sync-models")
                assert sync_response.status_code == 200
                synced_models = sync_response.json()["models"]
                assert len(synced_models) == 2
                assert {item["model"] for item in synced_models} == {"gpt-5", "gpt-4o-mini"}
    finally:
        reset_app_config()
        reset_model_services_config()


def test_discover_models_endpoint(tmp_path, monkeypatch):
    config_path, extensions_path, model_services_path = _write_base_files(tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH", str(model_services_path))
    reset_app_config()
    reset_model_services_config()

    app = FastAPI()
    app.include_router(model_services.router)
    app.include_router(models.router)

    try:
        with TestClient(app) as client:
            client.put(
                "/api/model-services",
                json={
                    "providers": [
                        {
                            "id": "relay",
                            "name": "Relay",
                            "provider_type": "openai-compatible",
                            "enabled": True,
                            "base_url": "https://relay.example/v1",
                            "api_key": "relay-key",
                            "api_key_mode": "replace",
                            "headers": {},
                            "homepage": "",
                            "notes": "",
                            "modalities": ["text"],
                            "models": [
                                {
                                    "id": "relay-gpt-5",
                                    "name": "relay-gpt-5",
                                    "display_name": "Relay GPT-5",
                                    "model": "gpt-5",
                                    "enabled": True,
                                    "modalities": ["text"],
                                    "supports_thinking": False,
                                    "supports_reasoning_effort": False,
                                    "supports_vision": False,
                                }
                            ],
                        }
                    ],
                    "defaults": {},
                },
            )

            with patch(
                "app.gateway.routers.model_services._request_json",
                return_value={
                    "data": [
                        {"id": "gpt-4o-mini", "owned_by": "openai"},
                        {"id": "gpt-5", "owned_by": "openai"},
                    ]
                },
            ):
                response = client.post(
                    "/api/model-services/providers/relay/discover-models"
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["models"][0]["id"] == "gpt-4o-mini"
                assert payload["models"][1]["id"] == "gpt-5"
                assert payload["models"][1]["already_configured"] is True
    finally:
        reset_app_config()
        reset_model_services_config()
