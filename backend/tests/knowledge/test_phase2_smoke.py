"""Live smoke for the phase-2 graph-quality chain (plan Final verification).

Trimmed to the kept chain in the first-phase slice: the graph extraction /
entity re-resolution assertions and the ``graph_search`` tool leg were
removed with the graph subsystem (``deerflow.knowledge.graph``,
``deerflow.tools.builtins.graph_search_tool``), so this module now drives a
markdown through upload → background worker (DashScope embeddings) →
``ready`` and exercises the cascade delete.

Gated behind ``RAG_E2E_LIVE=1`` plus the live keys, because it calls paid
third-party APIs (DashScope). Run with:

    cd backend && RAG_E2E_LIVE=1 uv run pytest tests/knowledge/test_phase2_smoke.py -q -s

(PowerShell: ``$env:RAG_E2E_LIVE="1"; uv run pytest ...``)
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from _router_auth_helpers import make_authed_test_app  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402

from app.gateway.auth.models import User  # noqa: E402
from app.gateway.routers import knowledge_bases  # noqa: E402
from app.gateway.services.knowledge_service import KnowledgeService  # noqa: E402
from deerflow.knowledge.store import KnowledgeStore  # noqa: E402
from deerflow.knowledge.vector_store import KnowledgeVectorStore  # noqa: E402
from deerflow.knowledge.worker import KnowledgeIndexWorker  # noqa: E402

from .conftest import QDRANT_TEST_URL, requires_qdrant  # noqa: E402

REQUIRED_KEYS = ("DASHSCOPE_EMBEDDING_API_KEY",)
requires_live_keys = pytest.mark.skipif(
    os.environ.get("RAG_E2E_LIVE") != "1" or any(not os.environ.get(key) for key in REQUIRED_KEYS),
    reason="live smoke disabled: set RAG_E2E_LIVE=1 with live keys in .env (calls paid APIs)",
)

pytestmark = [pytest.mark.integration, requires_qdrant, requires_live_keys, pytest.mark.asyncio]

DOC_READY_TIMEOUT = 600.0
POLL_INTERVAL = 5.0

SMOKE_MD = """# DeerFlow Plugin 机制

DeerFlow 的 Plugin 机制负责运行时扩展加载。每个 Plugin 在 Gateway 启动时完成注册，Plugin 的定义来自仓库根目录 config.yaml 的 plugins 列表，由操作员显式维护，刻意不放在 API 可写的配置文件里。

## 加载流程

Plugins 的定义从 config.yaml 读取后由 Gateway 逐个导入。导入失败的 Plugins 会被拒绝挂载并写入启动日志，不影响其余扩展的加载。
"""


@pytest_asyncio.fixture
async def smoke(session_factory, tmp_path):
    qdrant = AsyncQdrantClient(QDRANT_TEST_URL, timeout=60.0)
    vector_store = KnowledgeVectorStore(client=qdrant)
    store = KnowledgeStore(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=vector_store, concurrency=2)
    service = KnowledgeService(
        store=store,
        vector_store=vector_store,
        worker=worker,
        data_dir=tmp_path,
    )
    owner_id = uuid.uuid4()
    app = make_authed_test_app(user_factory=lambda: User(email="smoke2@example.com", password_hash="x", system_role="user", id=owner_id))
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)

    await worker.start()
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke", timeout=60.0)
    try:
        yield SimpleNamespace(
            api=api,
            store=store,
            vector_store=vector_store,
            qdrant=qdrant,
            owner_id=str(owner_id),
        )
    finally:
        await api.aclose()
        await worker.stop()
        for kb in await store.list_kbs(str(owner_id)):
            try:
                await vector_store.delete_by_kb(kb["id"])
            except Exception:
                pass
            await store.delete_kb(kb["id"])
        await qdrant.close()


async def test_phase2_live_smoke(smoke):
    # 1. create kb + upload the markdown (local short-circuit parse)
    response = await smoke.api.post("/api/knowledge-bases", json={"name": "smoke-phase2", "description": "phase-2 live smoke"})
    assert response.status_code == 201, response.text
    kb_id = response.json()["id"]

    upload = await smoke.api.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("plugin-smoke.md", SMOKE_MD.encode(), "text/markdown")},
    )
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["id"]

    # 2. wait for the worker to drive the document to ready
    deadline = time.monotonic() + DOC_READY_TIMEOUT
    doc = None
    while True:
        response = await smoke.api.get(f"/api/knowledge-bases/{kb_id}/documents")
        assert response.status_code == 200, response.text
        docs = response.json()
        doc = next((d for d in docs if d["id"] == doc_id), None)
        assert doc is not None
        assert doc["status"] != "failed", f"indexing failed: {doc['error']}"
        if doc["status"] == "ready":
            break
        assert time.monotonic() < deadline, f"timeout waiting for ready: {doc['status']} {doc['progress_percent']}%"
        await asyncio.sleep(POLL_INTERVAL)

    # 3. cleanup (also exercised by the fixture teardown as a safety net)
    response = await smoke.api.delete(f"/api/knowledge-bases/{kb_id}")
    assert response.status_code == 204, response.text
