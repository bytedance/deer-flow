"""Exercise real config reads and multipart disk spooling under Blockbuster."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.gateway.routers import knowledge_base as kb


@pytest.mark.asyncio
async def test_large_upload_and_config_reads_do_not_block_event_loop(tmp_path, monkeypatch):
    config_path = tmp_path / "ragflow.json"
    await asyncio.to_thread(config_path.write_text, json.dumps({"api_key": "test-key", "base_url": "http://ragflow.test"}), encoding="utf-8")

    def load_config():
        extra = json.loads(config_path.read_text(encoding="utf-8"))
        return SimpleNamespace(authorization=SimpleNamespace(enabled=False), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool", model_extra=extra))

    remote = SimpleNamespace(list_datasets=AsyncMock(return_value=[{"id": "ds1"}]), upload_document=AsyncMock(return_value=[{"id": "doc1", "name": "large.txt"}]), parse_documents=AsyncMock())
    monkeypatch.setattr(kb, "get_app_config", load_config)
    monkeypatch.setattr(kb, "_build_client", lambda _: remote)
    app = FastAPI()
    app.include_router(kb.router)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id="admin", system_role="admin")
        request.state.auth_source = "session"
        return await call_next(request)

    content = b"a" * (2 * 1024 * 1024)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/knowledge-base/datasets/ds1/documents", files={"file": ("large.txt", content, "text/plain")})
    assert response.status_code == 200
    assert response.json()["parsing_started"] is True
    assert remote.upload_document.call_args.kwargs["content"] == content
