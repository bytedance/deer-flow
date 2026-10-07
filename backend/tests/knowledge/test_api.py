"""Contract tests for the knowledge-base management API (spec §5.3, Phase-1 subset).

Router is thin: every endpoint resolves the caller from the stamped auth
context, enforces the Phase-1 owner-only gate (``can_access`` → 403), and
delegates to ``KnowledgeService`` (upload persistence, cascade deletes,
retry). The index worker is a mock — its own state machine is
covered in test_worker.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge import parser as knowledge_parser
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID))


def _stranger() -> User:
    return User(email="stranger@example.com", password_hash="x", system_role="user", id=uuid.UUID(int=987654321))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.delete_by_doc = AsyncMock()
    vector_store.delete_by_kb = AsyncMock()
    worker = MagicMock()
    worker.submit = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        worker=worker,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


def _stub_rag_gates(
    monkeypatch,
    *,
    table: bool = False,
    table_max_mb: int = 50,
) -> None:
    """把 parser 的配置读取器指向 stub——门控两态测试**不读本机 config.yaml**。

    预存缺陷修复（2026-09-09）：off 态用例原先依赖「测试环境默认 off」，但开发机
    的真实 config.yaml 里 `rag.table.enabled: true`，使 off 态断言恒红。stub 里
    必须带上 ``table`` 块：缺它会让 ``table_ingest_enabled()`` 走 AttributeError
    降级路，把真实行为掩盖成「恰好也是 off」。
    """
    monkeypatch.setattr(
        knowledge_parser,
        "get_app_config",
        lambda: SimpleNamespace(
            rag=SimpleNamespace(
                table=SimpleNamespace(enabled=table, max_size_mb=table_max_mb, card_mode="markdown"),
            )
        ),
    )


async def test_kb_crud_round_trip(service):
    client = _client(service)

    kb = _create_kb(client)
    assert kb["owner_id"] == OWNER_ID
    assert kb["visibility"] == "private"

    listing = client.get("/api/knowledge-bases")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [kb["id"]]

    detail = client.get(f"/api/knowledge-bases/{kb['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "产品资料"

    renamed = client.patch(f"/api/knowledge-bases/{kb['id']}", json={"name": "新名字"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "新名字"

    assert client.delete(f"/api/knowledge-bases/{kb['id']}").status_code == 204
    assert client.get(f"/api/knowledge-bases/{kb['id']}").status_code == 404


async def test_kb_validation_rejects_blank_name(service):
    client = _client(service)
    assert client.post("/api/knowledge-bases", json={"name": "  "}).status_code == 422


async def test_non_owner_gets_403_on_every_kb_scoped_route(service):
    owner_client = _client(service, _owner)
    kb = _create_kb(owner_client)
    stranger = _client(service, _stranger)

    assert stranger.get(f"/api/knowledge-bases/{kb['id']}").status_code == 403
    assert stranger.patch(f"/api/knowledge-bases/{kb['id']}", json={"name": "x"}).status_code == 403
    assert stranger.delete(f"/api/knowledge-bases/{kb['id']}").status_code == 403
    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/documents").status_code == 403
    assert stranger.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# t", "text/markdown")}).status_code == 403
    # the stranger's own listing stays empty (no cross-owner leakage)
    assert stranger.get("/api/knowledge-bases").json() == []


async def test_upload_document_returns_202_with_uploaded_row_and_enqueues(service, tmp_path):
    client = _client(service)
    kb = _create_kb(client)
    payload = "# 标题\n\n正文内容".encode()

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("手册.md", payload, "text/markdown")})

    assert response.status_code == 202, response.text
    doc = response.json()
    assert doc["status"] == "uploaded"
    assert doc["progress_percent"] == 0
    assert doc["uploader_id"] == OWNER_ID
    assert doc["name"] == "手册.md"
    assert doc["size_bytes"] == len(payload)
    service.worker.submit.assert_awaited_once_with(doc["id"])
    stored = Path(doc["storage_path"])
    assert stored.read_bytes() == payload
    assert str(tmp_path) in str(stored)


async def test_upload_compensates_when_row_creation_fails(service, tmp_path, monkeypatch):
    """文件→行半段（spec 2026-10-05 §2.1）：``create_document`` 抛错 ⇒ 请求报错、
    已写文件不残留、不进入队列。"""
    app = make_authed_test_app(user_factory=_owner)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    client = TestClient(app, raise_server_exceptions=False)
    kb = _create_kb(client)
    payload = "# 标题\n\n正文内容".encode()

    async def _boom(**kwargs):
        raise RuntimeError("row write failed")

    monkeypatch.setattr(service.store, "create_document", _boom)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("手册.md", payload, "text/markdown")})

    assert response.status_code == 500
    kb_root = tmp_path / "knowledge" / kb["id"]
    assert not kb_root.exists() or list(kb_root.iterdir()) == []
    service.worker.submit.assert_not_awaited()


async def test_upload_rejects_unsupported_suffix(service):
    """Task 6 (spec §6): allowlist gate at the upload entry; rejection lists
    the supported set and leaves no document row behind."""
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("evil.exe", b"MZ", "application/octet-stream")})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert ".exe" in detail
    assert ".md" in detail  # 拒绝文案列出支持集合
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


async def test_upload_rejects_empty_file(service):
    """空文件拦截（2026-08-30）：0 字节文件曾照收并送 MinerU，云端重试 5 次后回吐
    晦涩的 'retry limit reached'——在门口直接拒绝，不留文档行。"""
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("户号.pptx", b"", "application/octet-stream")})

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


async def test_supported_formats_endpoint_matches_parser_constant(service, monkeypatch):
    """Registered before ``/{kb_id}`` so the literal segment wins; payload is
    exactly the parser allowlist (frontend accept/intercept source)."""
    from deerflow.knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES

    _stub_rag_gates(monkeypatch)  # 表格腿 off：并集 = 文本冻结集
    client = _client(service)

    response = client.get("/api/knowledge-bases/supported-formats")

    assert response.status_code == 200
    assert response.json() == {"suffixes": sorted(SUPPORTED_UPLOAD_SUFFIXES)}


# ── 表格后缀门控两态（spec 2026-09-09 §4，plan Task 1）───────────────────


async def test_upload_rejects_table_suffix_when_table_disabled(service, monkeypatch):
    """off 态（默认）：电子表格后缀门口即拒，拒绝文案带上后缀，不留文档行。"""
    _stub_rag_gates(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("销售.xlsx", b"PK\x03\x04", "application/octet-stream")})

    assert response.status_code == 400
    assert ".xlsx" in response.json()["detail"]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


async def test_supported_formats_unions_table_suffixes_when_enabled(service, monkeypatch):
    """on 态：端点返回 文本∪表格 并集（排序）。"""
    from deerflow.knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES, TABLE_UPLOAD_SUFFIXES

    _stub_rag_gates(monkeypatch, table=True)
    client = _client(service)

    response = client.get("/api/knowledge-bases/supported-formats")

    assert response.status_code == 200
    suffixes = response.json()["suffixes"]
    assert set(suffixes) == set(SUPPORTED_UPLOAD_SUFFIXES | TABLE_UPLOAD_SUFFIXES)
    assert suffixes == sorted(suffixes)


async def test_upload_accepts_all_three_table_suffixes_when_enabled(service, monkeypatch):
    """on 态：.xlsx/.xls/.tsv 三后缀逐个过门落 uploaded 行并入队（mock worker）——
    解析腿由 Task 2/3 接线。"""
    _stub_rag_gates(monkeypatch, table=True)
    client = _client(service)
    kb = _create_kb(client)

    for name in ("销售.xlsx", "旧版.xls", "导出.tsv"):
        response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": (name, b"payload", "application/octet-stream")})
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "uploaded"

    assert service.worker.submit.await_count == 3


async def test_csv_is_accepted_regardless_of_table_gate(service, monkeypatch):
    """`.csv` 恒在文本冻结集，**不随 rag.table.enabled 门控**（spec §4 冻结边界）：
    off 态照收，on 态端点也恒含它。"""
    _stub_rag_gates(monkeypatch)  # off
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("数据.csv", b"a,b\n1,2\n", "text/csv")})

    assert response.status_code == 202, response.text
    assert ".csv" in client.get("/api/knowledge-bases/supported-formats").json()["suffixes"]

    _stub_rag_gates(monkeypatch, table=True)  # on
    assert ".csv" in client.get("/api/knowledge-bases/supported-formats").json()["suffixes"]


async def test_upload_rejects_oversized_table_when_enabled(service, monkeypatch):
    """on 态：超 rag.table.max_size_mb 的电子表格门口即拒（spec §4 行爆炸护栏），
    拒绝文案带上限额。"""
    _stub_rag_gates(monkeypatch, table=True, table_max_mb=1)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("巨型.xlsx", b"x" * (2 * 1024 * 1024), "application/octet-stream")})

    assert response.status_code == 400
    assert "1" in response.json()["detail"]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


async def test_table_size_gate_does_not_apply_to_csv(service, monkeypatch):
    """体积门只管被门控的三后缀：`.csv` 是既有文本集成员，不因 rag.table 引入
    新限制（spec §4「.csv 不门控」在体积面的推论）：同体积 .csv 仍 202。"""
    _stub_rag_gates(monkeypatch, table=True, table_max_mb=1)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("大表.csv", b"x" * (2 * 1024 * 1024), "text/csv")})

    assert response.status_code == 202, response.text


async def test_document_list_carries_indexing_fields(service):
    client = _client(service)
    kb = _create_kb(client)
    client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})

    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents")

    assert listing.status_code == 200
    (doc,) = listing.json()
    assert doc["status"] == "uploaded"
    assert doc["progress_percent"] == 0
    assert doc["chunk_count"] is None
    assert doc["uploader_id"] == OWNER_ID


async def test_document_file_serves_persisted_image(service):
    """切片图片显示链路的服务端半：worker 落盘的 images/ 经 files 路由原样返回。"""
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc = upload.json()
    images_dir = Path(doc["storage_path"]).parent / "images"
    images_dir.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\nfake"
    (images_dir / "p1.png").write_bytes(payload)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc['id']}/files/images/p1.png")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("image/png")


async def test_document_file_rejects_missing_traversal_and_non_image_paths(service):
    """files 路由只服务文档目录下的 images/ 子树：缺失文件、路径穿越、
    images/ 之外的路径（含源文档本身）一律 404。"""
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc = upload.json()
    base = f"/api/knowledge-bases/{kb['id']}/documents/{doc['id']}/files"

    assert client.get(f"{base}/images/missing.png").status_code == 404
    # URL 编码的 .. 穿越到文档目录之外（resolve 后落在 images/ 子树外）
    assert client.get(f"{base}/images/..%2F..%2Fsecret.png").status_code == 404
    # images/ 之外：源文档本身不暴露
    assert client.get(f"{base}/{doc['name']}").status_code == 404
    # 别人的 doc_id
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/other-doc/files/images/p1.png").status_code == 404


async def test_document_file_requires_kb_access(service):
    owner_client = _client(service, _owner)
    kb = _create_kb(owner_client)
    upload = owner_client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc = upload.json()
    stranger = _client(service, _stranger)

    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc['id']}/files/images/p1.png").status_code == 403


async def test_chunks_endpoint_paginates(service, session_factory):
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc_id = upload.json()["id"]
    store = KnowledgeStore(session_factory)
    await store.insert_chunks([{"chunk_id": f"{doc_id}#{i:04d}", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": i, "text": f"切片{i}", "heading_path": ["h"], "page": i, "token_count": 10} for i in range(3)])

    page1 = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/chunks", params={"offset": 0, "limit": 2})
    page2 = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/chunks", params={"offset": 2, "limit": 2})

    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert [c["chunk_index"] for c in body1["items"]] == [0, 1]
    assert body1["items"][0]["text"] == "切片0"
    assert body1["items"][0]["heading_path"] == ["h"]
    assert [c["chunk_index"] for c in page2.json()["items"]] == [2]


async def test_chunks_by_ids_endpoint_returns_requested_order_with_doc_name(service, session_factory):
    """切片血缘（2026-09-05）：GET /chunks?ids= 批量按请求序返回切片并附
    doc_name；未知 id 静默 dropped（切片可能已删，UI 用数量差提示）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.insert_chunks([{"chunk_id": f"{doc_id}#{i:04d}", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": i, "text": f"切片{i}", "heading_path": ["h"], "page": i, "token_count": 10} for i in range(2)])

    resp = client.get(f"/api/knowledge-bases/{kb['id']}/chunks", params={"ids": [f"{doc_id}#0001", f"{doc_id}#0000", "gone#0000"]})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [c["chunk_id"] for c in items] == [f"{doc_id}#0001", f"{doc_id}#0000"]
    assert items[0]["text"] == "切片1"
    assert items[0]["doc_name"] == "a.md"

    empty = client.get(f"/api/knowledge-bases/{kb['id']}/chunks", params={"ids": ["gone#0000"]})
    assert empty.status_code == 200
    assert empty.json()["items"] == []


async def test_chunks_by_ids_endpoint_never_returns_another_kbs_chunks(service, session_factory):
    """资源范围：批量按 id 取切片只返回 URL 目标库的行——他库的 chunk id
    就算被猜中也不返回。"""
    client = _client(service)
    kb_a = _create_kb(client, "A 库")
    kb_b = _create_kb(client, "B 库")
    doc_b = client.post(
        f"/api/knowledge-bases/{kb_b['id']}/documents",
        files={"file": ("b.md", b"# b", "text/markdown")},
    ).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_b}#0000",
                "doc_id": doc_b,
                "kb_id": kb_b["id"],
                "chunk_index": 0,
                "text": "B 库切片",
                "heading_path": [],
                "page": 0,
                "token_count": 10,
            }
        ]
    )

    resp = client.get(f"/api/knowledge-bases/{kb_a['id']}/chunks", params={"ids": [f"{doc_b}#0000"]})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_delete_document_cascades_vectors_and_rows(service, session_factory):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]

    assert client.delete(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}").status_code == 204

    service.vector_store.delete_by_doc.assert_awaited_once_with(doc_id)
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []
    # deleting again is a 404, not an error
    assert client.delete(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}").status_code == 404


async def test_delete_kb_cascades_vector_collections(service):
    client = _client(service)
    kb = _create_kb(client)

    assert client.delete(f"/api/knowledge-bases/{kb['id']}").status_code == 204

    service.vector_store.delete_by_kb.assert_awaited_once_with(kb["id"])


async def test_retry_failed_document_wipes_and_reenqueues(service, session_factory):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.update_document_status(doc_id, "failed", error="boom", chunk_count=2, progress_percent=40)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 202, response.text
    doc = response.json()
    assert doc["status"] == "uploaded"
    assert doc["progress_percent"] == 0
    assert doc["error"] is None
    assert doc["chunk_count"] is None
    # one submit for upload + one for retry
    assert service.worker.submit.await_count == 2


async def test_retry_non_failed_document_conflicts(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]

    assert client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry").status_code == 409


async def test_retry_degraded_document_wipes_and_reenqueues(service, session_factory):
    """降级文档（ready + 含 degraded 腿）可整篇重试（RFC §5.2 L162 / D1=甲）：
    受理先擦旧产物（向量→行）再入队，保留文档 ID；resume 全量重建。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.update_document_status(doc_id, "ready", chunk_count=2, path_status={"vector": "done", "caption": "degraded"})
    await store.insert_chunks(
        [
            {"chunk_id": f"{doc_id}#0000", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 0, "text": "甲", "heading_path": [], "page": None, "token_count": 1},
            {"chunk_id": f"{doc_id}#0001", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 1, "text": "乙", "heading_path": [], "page": None, "token_count": 1},
        ]
    )
    order: list[str] = []
    service.vector_store.delete_by_doc = AsyncMock(side_effect=lambda *a, **k: order.append("delete"))
    service.worker.submit = AsyncMock(side_effect=lambda *a, **k: order.append("submit"))

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 202, response.text
    doc = response.json()
    assert doc["status"] == "uploaded"
    assert doc["progress_percent"] == 0
    assert doc["error"] is None
    assert doc["chunk_count"] is None
    assert doc["path_status"] is None
    # 受理序=先删向量后入队；旧切片行清空（不重复创建有效切片、不混用旧向量）
    assert order == ["delete", "submit"]
    assert await store.list_chunks(doc_id, limit=10) == []


async def test_retry_processing_document_conflicts_with_new_copy(service, session_factory):
    """处理中文档不得重试（即便腿上带着历史 degraded 标记）——入口只认
    failed 或 ready+降级；409 文案同步更新（同一文档不重复启动重试）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.update_document_status(doc_id, "indexing", path_status={"vector": "pending", "caption": "degraded"})

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only failed or degraded documents can be retried"
