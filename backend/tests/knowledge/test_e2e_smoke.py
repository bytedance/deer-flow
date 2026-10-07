"""Live end-to-end smoke for the RAG knowledge base (plan Task 11).

Drives the REAL chain over HTTP (ASGI): upload one small PDF (real MinerU
parse) and one markdown file (local short-circuit) → background worker
(status machine + DashScope embeddings against the production-prefixed Qdrant
collections) → chunk/vector assertions → cascade delete verified.

Gated behind ``RAG_E2E_LIVE=1`` plus the three live keys, because it calls
paid third-party APIs (MinerU / DashScope). Run with:

    cd backend && RAG_E2E_LIVE=1 uv run pytest tests/knowledge/test_e2e_smoke.py -q

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
from qdrant_client.models import FieldCondition, Filter, MatchValue  # noqa: E402

from app.gateway.auth.models import User  # noqa: E402
from app.gateway.routers import knowledge_bases  # noqa: E402
from app.gateway.services.knowledge_service import KnowledgeService  # noqa: E402
from deerflow.knowledge.store import KnowledgeStore  # noqa: E402
from deerflow.knowledge.vector_store import KnowledgeVectorStore  # noqa: E402
from deerflow.knowledge.worker import KnowledgeIndexWorker  # noqa: E402

from .conftest import QDRANT_TEST_URL, requires_qdrant  # noqa: E402

REQUIRED_KEYS = (
    "MINERU_API_TOKEN",
    "DASHSCOPE_EMBEDDING_API_KEY",
    "DASHSCOPE_RERANK_API_KEY",
)
requires_live_keys = pytest.mark.skipif(
    os.environ.get("RAG_E2E_LIVE") != "1" or any(not os.environ.get(key) for key in REQUIRED_KEYS),
    reason="live smoke disabled: set RAG_E2E_LIVE=1 with live keys in .env (calls paid APIs)",
)

pytestmark = [pytest.mark.integration, requires_qdrant, requires_live_keys, pytest.mark.asyncio]

DOC_READY_TIMEOUT = 900.0
POLL_INTERVAL = 5.0

SAMPLE_MD = Path(__file__).parent / "fixtures" / "sample.md"


def _make_pdf() -> bytes:
    """Smallest valid one-page text PDF (Helvetica, latin text) for MinerU."""
    content = (
        b"BT /F1 16 Tf 72 720 Td (DeerFlow RAG Smoke Test) Tj ET\n"
        b"BT /F1 12 Tf 72 692 Td (DeerFlow is a LangGraph-based super agent system.) Tj ET\n"
        b"BT /F1 12 Tf 72 672 Td (The Gateway coordinates agents, tools and sandboxes.) Tj ET\n"
        b"BT /F1 12 Tf 72 652 Td (Qdrant stores chunk vectors for hybrid retrieval.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(pdf)


@pytest_asyncio.fixture
async def smoke(session_factory, tmp_path):
    """Real chain: API (ASGI) → service → worker → MinerU/DashScope/Qdrant.

    The business DB is a throwaway sqlite; Qdrant uses the production-prefixed
    ``kb_*`` collections (the point of the smoke) and is cleaned by the
    cascade-delete assertion plus this teardown's best-effort sweep.
    """
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
    app = make_authed_test_app(user_factory=lambda: User(email="smoke@example.com", password_hash="x", system_role="user", id=owner_id))
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


async def _wait_for_ready(api: httpx.AsyncClient, kb_id: str, expected: int) -> list[dict]:
    deadline = time.monotonic() + DOC_READY_TIMEOUT
    while True:
        response = await api.get(f"/api/knowledge-bases/{kb_id}/documents")
        assert response.status_code == 200, response.text
        docs = response.json()
        failed = [doc for doc in docs if doc["status"] == "failed"]
        if failed:
            pytest.fail(f"indexing failed: {[(d['name'], d['error']) for d in failed]}")
        if len(docs) == expected and all(doc["status"] == "ready" for doc in docs):
            return docs
        if time.monotonic() > deadline:
            pytest.fail(f"timeout waiting for ready; statuses={[(d['name'], d['status'], d['progress_percent']) for d in docs]}")
        await asyncio.sleep(POLL_INTERVAL)


async def _kb_point_count(qdrant: AsyncQdrantClient, collection: str, kb_id: str) -> int:
    points, _ = await qdrant.scroll(
        collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        limit=1,
    )
    return len(points)


async def test_e2e_smoke_full_lifecycle(smoke):
    # 1. create kb
    response = await smoke.api.post("/api/knowledge-bases", json={"name": "smoke-验收库", "description": "e2e live smoke"})
    assert response.status_code == 201, response.text
    kb_id = response.json()["id"]

    # 2. upload one PDF (real MinerU) and one MD (local short-circuit)
    pdf_upload = await smoke.api.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("smoke.pdf", _make_pdf(), "application/pdf")},
    )
    assert pdf_upload.status_code == 202, pdf_upload.text
    assert pdf_upload.json()["status"] == "uploaded"

    md_upload = await smoke.api.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("sample.md", SAMPLE_MD.read_bytes(), "text/markdown")},
    )
    assert md_upload.status_code == 202, md_upload.text
    md_doc_id = md_upload.json()["id"]

    # 3. wait for the worker to drive both documents to ready
    docs = await _wait_for_ready(smoke.api, kb_id, expected=2)
    for doc in docs:
        assert doc["chunk_count"] and doc["chunk_count"] > 0, f"{doc['name']} has no chunks"
        assert doc["progress_percent"] == 100

    # 4. chunk preview: the markdown document's slices are readable
    chunks = await smoke.api.get(f"/api/knowledge-bases/{kb_id}/documents/{md_doc_id}/chunks")
    assert chunks.status_code == 200, chunks.text
    items = chunks.json()["items"]
    assert items and chunks.json()["total"] > 0

    # 5. vector path: chunk points exist in Qdrant
    assert await _kb_point_count(smoke.qdrant, "kb_chunks", kb_id) > 0

    # 6. cascade delete: business rows + Qdrant points all gone
    response = await smoke.api.delete(f"/api/knowledge-bases/{kb_id}")
    assert response.status_code == 204, response.text
    assert await smoke.store.get_kb(kb_id) is None
    assert await _kb_point_count(smoke.qdrant, "kb_chunks", kb_id) == 0, f"kb_chunks still has points for {kb_id}"
