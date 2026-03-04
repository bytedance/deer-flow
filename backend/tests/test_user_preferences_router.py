"""Tests for user model preference API routes."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.gateway.auth.middleware import get_current_user
from src.gateway.routers.user_preferences import router


@pytest_asyncio.fixture()
async def client(tmp_store_dir):
    app = FastAPI()

    async def _mock_current_user():
        return {
            "id": "user-123",
            "email": "user@example.com",
            "display_name": "Test User",
            "created_at": "2026-03-04T00:00:00+00:00",
        }

    app.dependency_overrides[get_current_user] = _mock_current_user
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestUserPreferencesRouter:
    @pytest.mark.asyncio
    async def test_get_defaults_when_not_set(self, client: AsyncClient) -> None:
        response = await client.get("/api/user/preferences/models")
        assert response.status_code == 200
        assert response.json() == {
            "model_name": None,
            "thinking_effort": None,
            "provider_enabled": {},
            "enabled_models": {},
            "updated_at": None,
        }

    @pytest.mark.asyncio
    async def test_set_and_get_preferences(self, client: AsyncClient) -> None:
        save_response = await client.put(
            "/api/user/preferences/models",
            json={
                "model_name": "openai:gpt-5.2:standard",
                "thinking_effort": "xhigh",
                "provider_enabled": {"openai": True},
                "enabled_models": {"openai:gpt-5.2:standard": True},
            },
        )
        assert save_response.status_code == 200
        body = save_response.json()
        assert body["model_name"] == "openai:gpt-5.2:standard"
        assert body["thinking_effort"] == "xhigh"
        assert body["provider_enabled"]["openai"] is True
        assert body["enabled_models"]["openai:gpt-5.2:standard"] is True
        assert body["updated_at"] is not None

        load_response = await client.get("/api/user/preferences/models")
        assert load_response.status_code == 200
        assert load_response.json()["model_name"] == "openai:gpt-5.2:standard"
        assert load_response.json()["thinking_effort"] == "xhigh"
        assert load_response.json()["provider_enabled"]["openai"] is True
        assert load_response.json()["enabled_models"]["openai:gpt-5.2:standard"] is True

    @pytest.mark.asyncio
    async def test_partial_update_does_not_clear_toggle_fields(self, client: AsyncClient) -> None:
        await client.put(
            "/api/user/preferences/models",
            json={
                "model_name": "openai:gpt-5.2:standard",
                "thinking_effort": "medium",
                "provider_enabled": {"openai": True},
                "enabled_models": {"openai:gpt-5.2:standard": True},
            },
        )
        await client.put(
            "/api/user/preferences/models",
            json={"thinking_effort": "high"},
        )
        load_response = await client.get("/api/user/preferences/models")
        body = load_response.json()
        assert body["model_name"] == "openai:gpt-5.2:standard"
        assert body["thinking_effort"] == "high"
        assert body["provider_enabled"]["openai"] is True
        assert body["enabled_models"]["openai:gpt-5.2:standard"] is True

