"""``/api/models`` projects the normalized reasoning contract beside the legacy booleans (issue #5073)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import models as models_router
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.token_usage_config import TokenUsageConfig


def _app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        token_usage=TokenUsageConfig(enabled=False),
        authorization=AuthorizationConfig(),
    )


def _legacy_model() -> ModelConfig:
    return ModelConfig(name="legacy", model="legacy", use="langchain_openai:ChatOpenAI", supports_thinking=True, supports_reasoning_effort=True)


def _contract_model() -> ModelConfig:
    return ModelConfig(
        name="glm-5.3-flash",
        model="glm-5.3-flash",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        reasoning={
            "thinking": "required",
            "dialect": "openai_extra_body",
            "history": "clear",
            "effort": {"values": ["low", "high", "max"], "default": "max", "aliases": {"minimal": "low", "medium": "high"}},
        },
    )


@pytest.fixture
def client(monkeypatch):
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.routers.models.get_optional_user_from_request", AsyncMock(return_value=None))

    app = FastAPI()
    app.include_router(models_router.router)
    app.dependency_overrides[models_router.get_config] = lambda: _app_config([_legacy_model(), _contract_model()])
    with TestClient(app) as test_client:
        yield test_client


def test_list_models_projects_reasoning_for_every_model(client):
    response = client.get("/api/models")

    assert response.status_code == 200
    by_name = {m["name"]: m for m in response.json()["models"]}

    legacy = by_name["legacy"]
    assert legacy["supports_thinking"] is True
    assert legacy["supports_reasoning_effort"] is True
    assert legacy["reasoning"] == {
        "thinking": "optional",
        "effort": {"values": ["minimal", "low", "medium", "high"], "default": None, "aliases": {}},
        "history": None,
        "source": "legacy",
    }

    contract = by_name["glm-5.3-flash"]
    # Deprecation-window projection: the booleans are derived from the contract.
    assert contract["supports_thinking"] is True
    assert contract["supports_reasoning_effort"] is True
    assert contract["reasoning"] == {
        "thinking": "required",
        "effort": {"values": ["low", "high", "max"], "default": "max", "aliases": {"minimal": "low", "medium": "high"}},
        "history": "clear",
        "source": "contract",
    }


def test_get_model_projects_reasoning(client):
    response = client.get("/api/models/glm-5.3-flash")

    assert response.status_code == 200
    body = response.json()
    assert body["reasoning"]["thinking"] == "required"
    assert body["reasoning"]["effort"]["values"] == ["low", "high", "max"]


def test_model_control_preview_does_not_change_config_or_create_a_run(client):
    response = client.post("/api/models/resolve", json={"text": "这次用 legacy 帮我算一下"})
    assert response.status_code == 200
    assert response.json()["model_name"] == "legacy"
    assert response.json()["scope"] == "turn"
    assert client.get("/api/models").json()["models"][0]["name"] == "legacy"


def test_model_control_unknown_version_is_not_replaced(client):
    response = client.post("/api/models/resolve", json={"text": "这次用 opus v4 pro 帮我算一下"})
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["model_name"] is None


def test_model_control_enforces_use_after_visibility(client, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(models_router, "get_optional_user_from_request", AsyncMock(return_value=object()))
    monkeypatch.setattr(models_router, "_resolve_bound_owner_for_model_list", AsyncMock(return_value=None))
    monkeypatch.setattr(models_router, "resolve_model_authorization", lambda *args, **kwargs: (None, None))

    def deny(*args, **kwargs):
        raise HTTPException(status_code=403, detail="Model denied")

    monkeypatch.setattr(models_router, "authorize_model_use", deny)
    assert client.post("/api/models/resolve", json={"text": "这次用 legacy 帮我算一下"}).status_code == 403
