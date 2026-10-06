"""Live smoke for the phase-2 graph-quality chain (plan Final verification).

Drives the REAL chain over HTTP (ASGI): upload one small markdown carrying a
cross-slice alias pair (``Plugin`` / ``Plugins`` in separate sections) →
background worker (DashScope embeddings + DeepSeek graph extraction +
incremental entity re-resolution against the production-prefixed Qdrant
collections) → assertions:

1. the document reaches ``ready`` WITHOUT the ``entity-resolution failed``
   sub-marker (D3 wired into the worker and not degrading);
2. no two graph entities share an alias key (cross-slice aliases merged; the
   representative keeps the union of source_chunk_ids — printed for the
   record);
3. a graph_search question built from a real indexed entity returns evidence
   items carrying the phase-2 ``score`` field;
4. the evidence-set diff between phase-2 defaults and the phase-1 restore
   knob set is printed (comparison data for the PR description).

Gated behind ``RAG_E2E_LIVE=1`` plus the live keys, because it calls paid
third-party APIs (DashScope / DeepSeek). Run with:

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
from deerflow.knowledge.embedder import DashScopeEmbedder  # noqa: E402
from deerflow.knowledge.graph.store import GraphStore  # noqa: E402
from deerflow.knowledge.store import KnowledgeStore  # noqa: E402
from deerflow.knowledge.vector_store import KnowledgeVectorStore  # noqa: E402
from deerflow.knowledge.wiki.store import WikiStore  # noqa: E402
from deerflow.knowledge.worker import KnowledgeIndexWorker  # noqa: E402
from deerflow.models.factory import create_chat_model  # noqa: E402
from deerflow.tools.builtins.graph_search_tool import _graph_search_impl  # noqa: E402

from .conftest import QDRANT_TEST_URL, requires_qdrant  # noqa: E402

REQUIRED_KEYS = (
    "DASHSCOPE_EMBEDDING_API_KEY",
    "DEEPSEEK_API_KEY",
)
requires_live_keys = pytest.mark.skipif(
    os.environ.get("RAG_E2E_LIVE") != "1" or any(not os.environ.get(key) for key in REQUIRED_KEYS),
    reason="live smoke disabled: set RAG_E2E_LIVE=1 with live keys in .env (calls paid APIs)",
)

pytestmark = [pytest.mark.integration, requires_qdrant, requires_live_keys, pytest.mark.asyncio]

DOC_READY_TIMEOUT = 600.0
POLL_INTERVAL = 5.0

# Cross-slice alias pair by design: section 1 only ever writes ``Plugin``
# (singular), section 2 only ``Plugins`` (plural). Per-slice normalization
# cannot fold across slices — only the D3 re-resolver can merge them.
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
    graph_store = GraphStore(session_factory)
    wiki_store = WikiStore(session_factory)
    worker = KnowledgeIndexWorker(
        store=store,
        vector_store=vector_store,
        concurrency=2,
        main_llm=create_chat_model(),
    )
    service = KnowledgeService(
        store=store,
        vector_store=vector_store,
        graph_store=graph_store,
        wiki_store=wiki_store,
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
            graph_store=graph_store,
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


def _alias_key(name: str) -> str:
    """Minimal stand-in for the normalizer's alias key (lower + strip trailing s)."""
    key = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    return key[:-1] if len(key) > 3 and key.endswith("s") else key


async def test_phase2_live_smoke(smoke):
    # 1. create kb + upload the alias-pair markdown (local short-circuit parse)
    response = await smoke.api.post("/api/knowledge-bases", json={"name": "smoke-phase2", "description": "phase-2 live smoke"})
    assert response.status_code == 201, response.text
    kb_id = response.json()["id"]

    upload = await smoke.api.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("plugin-smoke.md", SMOKE_MD.encode(), "text/markdown")},
    )
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["id"]

    # 2. wait for ready; the D3 re-resolver must not leave its failure marker
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
    error = doc.get("error") or ""
    assert "entity-resolution failed" not in error, f"re-resolver degraded: {error}"

    # 3. graph populated; no two entities share an alias key (cross-slice merge)
    entities = await smoke.graph_store.list_entities(kb_id)
    assert entities, "graph extraction produced no entities"
    relations = await smoke.graph_store.list_relations(kb_id)
    print(f"\nentities ({len(entities)}): {[e['name'] for e in entities]}")
    print(f"relations ({len(relations)}): {[(r['source'], r['relation'], r['target']) for r in relations]}")
    by_alias: dict[str, list[str]] = {}
    for entity in entities:
        by_alias.setdefault(_alias_key(entity["name"]), []).append(entity["name"])
    duplicated = {key: names for key, names in by_alias.items() if len(names) > 1}
    assert not duplicated, f"alias groups survived re-resolution: {duplicated}"
    plugin_like = [e for e in entities if _alias_key(e["name"]) == "plugin"]
    if plugin_like:
        merged = plugin_like[0]
        print(f"plugin representative: name={merged['name']!r} chunk_ids={sorted(merged['source_chunk_ids'])}")
        print(f"merged description: {merged['description']!r}")

    # 4. graph_search over the live chain: evidence must carry the phase-2 score
    entity_names = [e["name"] for e in entities]
    anchor = plugin_like[0]["name"] if plugin_like else entity_names[0]
    runtime = SimpleNamespace(context={"kb_id": kb_id, "user_id": smoke.owner_id})
    embedder = DashScopeEmbedder()
    llm = create_chat_model()

    result = await _graph_search_impl(
        f"{anchor} 是如何加载的？",
        runtime,
        store=smoke.store,
        graph_store=smoke.graph_store,
        vector_store=smoke.vector_store,
        embedder=embedder,
        llm=llm,
        hops=2,
    )
    print(f"\nquery anchor: {anchor!r}")
    print(f"matched entities: {[e['name'] for e in result['entities']]}")
    print(f"evidence ({len(result['evidence'])}): {[e['chunk_id'] for e in result['evidence']]}")
    assert result["entities"], "graph_search matched no entities on live data"
    assert result["evidence"], "graph_search returned no evidence on live data"
    assert all("score" in item and isinstance(item["score"], float) for item in result["evidence"])

    # 5. comparison data: phase-2 defaults vs phase-1 restore knobs
    restored = await _graph_search_impl(
        f"{anchor} 是如何加载的？",
        runtime,
        store=smoke.store,
        graph_store=smoke.graph_store,
        vector_store=smoke.vector_store,
        embedder=embedder,
        llm=llm,
        hops=2,
        per_entity_cap=999,
        per_edge_cap=999,
        hop0_guarantee=0,
        neighbor_min_score=0.0,
    )
    default_ids = [e["chunk_id"] for e in result["evidence"]]
    restored_ids = [e["chunk_id"] for e in restored["evidence"]]
    print(f"\nphase-2-default  evidence ({len(default_ids)}): {default_ids}")
    print(f"phase-1-restored evidence ({len(restored_ids)}): {restored_ids}")
    print(f"default-only:  {sorted(set(default_ids) - set(restored_ids))}")
    print(f"restored-only: {sorted(set(restored_ids) - set(default_ids))}")

    # 6. cleanup (also exercised by the fixture teardown as a safety net)
    response = await smoke.api.delete(f"/api/knowledge-bases/{kb_id}")
    assert response.status_code == 204, response.text
