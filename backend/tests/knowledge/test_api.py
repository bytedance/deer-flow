"""Contract tests for the knowledge-base management API (spec §5.3, Phase-1 subset).

Router is thin: every endpoint resolves the caller from the stamped auth
context, enforces the Phase-1 owner-only gate (``can_access`` → 403), and
delegates to ``KnowledgeService`` (upload persistence, cascade deletes,
retry, wiki trigger). The index worker is a mock — its own state machine is
covered in test_worker.py.
"""

from __future__ import annotations

import asyncio
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
from deerflow.knowledge.graph.extractor import ExtractedEntity
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
    vector_store.delete_entities = AsyncMock()
    vector_store.delete_wiki_entries = AsyncMock()
    worker = MagicMock()
    worker.submit = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
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
    video: bool = False,
    table: bool = False,
    video_max_mb: int = 2048,
    table_max_mb: int = 50,
) -> None:
    """把 parser 的配置读取器指向 stub——门控两态测试**不读本机 config.yaml**。

    预存缺陷修复（2026-09-09）：off 态用例原先依赖「测试环境默认 off」，但开发机
    的真实 config.yaml 里 `rag.video.enabled: true`，使三条 off 态断言恒红。两条腿
    （video/table）都必须在 stub 里出现：缺一条会让另一条腿的 ``*_ingest_enabled()``
    走 AttributeError 降级路，把真实行为掩盖成「恰好也是 off」。
    """
    monkeypatch.setattr(
        knowledge_parser,
        "get_app_config",
        lambda: SimpleNamespace(
            rag=SimpleNamespace(
                video=SimpleNamespace(enabled=video, max_size_mb=video_max_mb),
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
    assert stranger.post(f"/api/knowledge-bases/{kb['id']}/wiki/generate").status_code == 403
    assert stranger.post(f"/api/knowledge-bases/{kb['id']}/wiki/regenerate", json={"entry_ids": ["e1"]}).status_code == 403
    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries").status_code == 403
    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries/whatever").status_code == 403
    assert stranger.delete(f"/api/knowledge-bases/{kb['id']}/wiki/entries/whatever").status_code == 403
    assert stranger.post(f"/api/knowledge-bases/{kb['id']}/recall-test", json={"query": "x"}).status_code == 403
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

    _stub_rag_gates(monkeypatch)  # 两腿均 off：并集 = 文本冻结集
    client = _client(service)

    response = client.get("/api/knowledge-bases/supported-formats")

    assert response.status_code == 200
    assert response.json() == {"suffixes": sorted(SUPPORTED_UPLOAD_SUFFIXES)}


# ── 视频后缀门控两态（spec 2026-09-08 §2/§7，plan Task 1）───────────────────


async def test_upload_rejects_video_suffix_when_video_disabled(service, monkeypatch):
    """off 态（默认）：视频后缀门口即拒，拒绝文案列出视频后缀，不留文档行。"""
    _stub_rag_gates(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("培训.mp4", b"\x00\x01\x02", "video/mp4")})

    assert response.status_code == 400
    assert ".mp4" in response.json()["detail"]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


async def test_supported_formats_unions_video_suffixes_when_enabled(service, monkeypatch):
    """on 态：端点返回 文本∪视频 并集（排序），文本冻结集恒在其中。"""
    from deerflow.knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES, VIDEO_UPLOAD_SUFFIXES

    _stub_rag_gates(monkeypatch, video=True)
    client = _client(service)

    response = client.get("/api/knowledge-bases/supported-formats")

    assert response.status_code == 200
    suffixes = response.json()["suffixes"]
    assert set(suffixes) == set(SUPPORTED_UPLOAD_SUFFIXES | VIDEO_UPLOAD_SUFFIXES)
    assert suffixes == sorted(suffixes)


async def test_upload_accepts_video_suffix_when_enabled(service, monkeypatch):
    """on 态：.mp4 过门落 uploaded 行并入队（mock worker）——管线腿后续任务接线。"""
    _stub_rag_gates(monkeypatch, video=True)
    client = _client(service)
    kb = _create_kb(client)
    payload = b"\x00\x00\x00\x18ftypmp42"

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("培训.mp4", payload, "video/mp4")})

    assert response.status_code == 202, response.text
    doc = response.json()
    assert doc["status"] == "uploaded"
    assert doc["name"] == "培训.mp4"
    service.worker.submit.assert_awaited_once_with(doc["id"])


async def test_upload_rejects_oversized_video_when_enabled(service, monkeypatch):
    """on 态：超过 rag.video.max_size_mb 的视频门口即拒（spec §7 预算护栏）。"""
    _stub_rag_gates(monkeypatch, video=True, video_max_mb=1)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("大片.mp4", b"x" * (2 * 1024 * 1024), "video/mp4")})

    assert response.status_code == 400
    assert "1" in response.json()["detail"]  # 拒绝文案带上限额
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []


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
    """on 态：端点返回 文本∪表格 并集（排序）；video 腿 off 时视频后缀不得混入
    （两腿独立门控，单一源不漂移）。"""
    from deerflow.knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES, TABLE_UPLOAD_SUFFIXES

    _stub_rag_gates(monkeypatch, table=True)
    client = _client(service)

    response = client.get("/api/knowledge-bases/supported-formats")

    assert response.status_code == 200
    suffixes = response.json()["suffixes"]
    assert set(suffixes) == set(SUPPORTED_UPLOAD_SUFFIXES | TABLE_UPLOAD_SUFFIXES)
    assert suffixes == sorted(suffixes)
    assert ".mp4" not in suffixes


async def test_supported_formats_unions_both_gates_when_both_enabled(service, monkeypatch):
    """两腿同开：并集 = 文本∪视频∪表格（三集互不相交，端点仍是单一源）。"""
    from deerflow.knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES, TABLE_UPLOAD_SUFFIXES, VIDEO_UPLOAD_SUFFIXES

    _stub_rag_gates(monkeypatch, video=True, table=True)
    client = _client(service)

    suffixes = client.get("/api/knowledge-bases/supported-formats").json()["suffixes"]

    assert set(suffixes) == set(SUPPORTED_UPLOAD_SUFFIXES | VIDEO_UPLOAD_SUFFIXES | TABLE_UPLOAD_SUFFIXES)


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


async def test_document_list_injects_library_level_wiki_status(service):
    """spec 2026-08-11 §5：列表响应携带 path_status；wiki 子状态为库级镜像，
    响应组装时注入、全库文档共享；dirty 条目计入已生成（2026-08-12 口径）；
    库存为 null 的老行不注入（前端不展示悬停）。"""
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc_id = upload.json()["id"]
    # 模拟 worker 推进后的 per-path 子状态
    await service.store.update_document_status(doc_id, "indexing", path_status={"vector": "done", "graph": "indexing"})
    # 老行：path_status 为 null
    await service.store.create_document(doc_id="doc-legacy", kb_id=kb["id"], uploader_id=OWNER_ID, name="old.md", size_bytes=1, storage_path="p")

    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents")
    by_id = {doc["id"]: doc for doc in listing.json()}
    # 库无 ready 条目且未在生成 → pending；同一库级值注入到所有文档
    assert by_id[doc_id]["path_status"] == {"vector": "done", "graph": "indexing", "wiki": "pending"}
    assert by_id["doc-legacy"]["path_status"] is None

    # dirty = 已生成待刷新，内容过期但可用，仍属已生成态；但库级镜像只对终
    # 态文档生效（2026-08-13 口径：流水线中的文档尚未被 wiki 消化 → pending）
    await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="旧内容", source_chunk_ids=["c1"], status="dirty")
    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents")
    by_id = {doc["id"]: doc for doc in listing.json()}
    assert by_id[doc_id]["path_status"]["wiki"] == "pending"
    await service.store.update_document_status(doc_id, "ready", path_status={"vector": "done", "graph": "done"})
    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents")
    by_id = {doc["id"]: doc for doc in listing.json()}
    assert by_id[doc_id]["path_status"]["wiki"] == "ready"
    assert by_id["doc-legacy"]["path_status"] is None


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


async def test_document_list_wiki_generating_only_when_in_flight(service, monkeypatch):
    """generating：存在进行中的生成（手动或自动触发）；流水线中的文档除外——
    它尚未被 wiki 消化，wiki 行恒为 pending（2026-08-13 口径）。"""
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc_id = upload.json()["id"]
    await service.store.update_document_status(doc_id, "ready", path_status={"vector": "done", "graph": "done"})

    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: True)
    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents")
    (doc,) = listing.json()
    assert doc["path_status"]["wiki"] == "generating"

    # 同一时刻仍在索引流水线的文档：wiki 尚未消化它 → pending，不镜像库级在途
    await service.store.update_document_status(doc_id, "indexing", path_status={"vector": "done", "graph": "indexing"})
    (doc,) = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()
    assert doc["path_status"]["wiki"] == "pending"


async def test_document_list_wiki_in_flight_overrides_ready_entries(service, monkeypatch):
    """在途优先口径（2026-08-13）：库里已有 ready 条目时，增量生成在途仍显
    示 generating——否则「生成中」只在空库首次生成出现一次，之后新文档触
    发的增量消化永远不可见。dirty 不触发 generating（已生成待更新口径不
    变，轮询也不会空转）。"""
    client = _client(service)
    kb = _create_kb(client)
    upload = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")})
    doc_id = upload.json()["id"]
    await service.store.update_document_status(doc_id, "ready", path_status={"vector": "done", "graph": "done"})
    await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="已有内容", source_chunk_ids=["c1", "c2"])

    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: True)
    (doc,) = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()
    assert doc["path_status"]["wiki"] == "generating"

    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: False)
    (doc,) = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()
    assert doc["path_status"]["wiki"] == "ready"


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
    """条目↔切片血缘（2026-09-05）：GET /chunks?ids= 批量按请求序返回切片并附
    doc_name（wiki 条目抽屉展开 source_chunk_ids 用）；未知 id 静默 dropped
    （切片可能已删，UI 用数量差提示）。"""
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


async def test_delete_document_cascades_vectors_graph_wiki_and_rows(service, session_factory):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]

    assert client.delete(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}").status_code == 204

    service.vector_store.delete_by_doc.assert_awaited_once_with(doc_id)
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents").json() == []
    # deleting again is a 404, not an error
    assert client.delete(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}").status_code == 404


async def test_delete_document_cascades_wiki_lifecycle(service, session_factory):
    """Task 12 条目生命周期级联（spec §3.5）：资格即条目存在理由，失格即删。

    - 失格（remove_chunk_contributions 后剩余 freq < 2）→ 删条目行 +
      ``kb_wiki_entries`` 向量点；实体节点与 ``kb_entities`` 不动（剩余活
      切片仍由向量路直接服务，不违背删除意图）；
    - 仍合格（剩余 freq ≥ 2）→ 标 dirty，等增量重生成；
    - 实体消失（孤儿）→ 条目同样连行带向量删除；
    - 幂等：重复删同一标题返回 0，不报错。
    """
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    doomed = f"{doc_id}#0"
    await store.insert_chunks([{"chunk_id": doomed, "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 0, "text": "切片", "heading_path": ["h"], "page": 1, "token_count": 10}])

    async def _seed_entity(name: str, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            await service.graph_store.upsert_entities(kb["id"], [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=chunk_id)

    # Alpha：删除后 freq 2→1 失格；Beta：3→2 仍合格；Gamma：1→0 孤儿。
    await _seed_entity("Alpha", [doomed, "keeper#0"])
    await _seed_entity("Beta", [doomed, "keeper#0", "keeper#1"])
    await _seed_entity("Gamma", [doomed])
    for name in ("Alpha", "Beta", "Gamma"):
        await service.wiki_store.upsert_entry(kb["id"], title=name, content=f"# {name}", source_chunk_ids=[doomed])

    assert client.delete(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}").status_code == 204

    # 失格 + 孤儿条目连行带向量删除；仍合格的 Beta 仅标 dirty。
    assert {e["title"]: e["status"] for e in await service.wiki_store.list_entries(kb["id"])} == {"Beta": "dirty"}
    service.vector_store.delete_wiki_entries.assert_awaited_once()
    wiki_call = service.vector_store.delete_wiki_entries.await_args
    assert wiki_call.args[0] == kb["id"]
    assert set(wiki_call.args[1]) == {"Alpha", "Gamma"}
    # 实体节点与 kb_entities 不动：只有孤儿实体 Gamma 的向量被删。
    service.vector_store.delete_entities.assert_awaited_once_with(kb["id"], ["Gamma"])
    by_name = {e["name"]: e for e in await service.graph_store.list_entities(kb["id"])}
    assert sorted(by_name) == ["Alpha", "Beta"]
    assert len(by_name["Alpha"]["source_chunk_ids"]) == 1
    assert len(by_name["Beta"]["source_chunk_ids"]) == 2
    # 幂等：重复删同一标题是 no-op。
    assert await service.wiki_store.delete_entries(kb["id"], ["Alpha"]) == 0


async def test_delete_wiki_entry_removes_row_and_vector(service):
    """Task 13 手动删除条目：删业务行 + kb_wiki_entries 向量点（实体不动）。

    重建语义（2026-08-13 拍板）：若实体仍合格，下次 generate_wiki 的
    backfill 会按最新材料重建该条目——手动删除对它相当于「重置」；只有
    失格/无源实体的条目删除才是永久的。
    """
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"])

    assert client.delete(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}").status_code == 204

    assert await service.wiki_store.list_entries(kb["id"]) == []
    service.vector_store.delete_wiki_entries.assert_awaited_once_with(kb["id"], ["DeerFlow"])
    # 重复删除是 404，不是错误
    assert client.delete(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}").status_code == 404


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
    await store.update_document_status(doc_id, "ready", chunk_count=2, path_status={"vector": "done", "graph": "done", "caption": "degraded"})
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


async def test_retry_video_document_requeues_captionless_shots(service, session_factory):
    """视频重试走 resume 路（骨架已在），只补跑 pending 镜头 ⇒ 受理时必须把无图说的
    镜头翻回 pending（RFC §5.2 L162「覆盖原先未成功的图片说明」，2026-10-04 验收补口）：
    failed=尝试过但空；empty=三路俱空但 caption 同样缺失——VLM 故障恢复后本可补出
    （静默视频否则永远停在零切片失败）。done 保持：重刷已有图说是 recaption 的职责。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = uuid.uuid4().hex
    doc_dir = service.data_dir / "knowledge" / kb["id"] / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    await service.store.create_document(doc_id=doc_id, kb_id=kb["id"], uploader_id=OWNER_ID, name="clip.mp4", size_bytes=100, storage_path=str(doc_dir / "clip.mp4"))
    await service.store.update_document_status(doc_id, "ready", chunk_count=2, path_status={"vector": "done", "graph": "done", "caption": "degraded"})
    await service.video_shot_store.bulk_upsert_shots(
        doc_id,
        kb_id=kb["id"],
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 3000, "caption": "旧图说", "asr_text": "甲", "ocr_text": "", "caption_status": "done", "keyframe_path": "frames/0.jpg"},
            {"shot_index": 1, "start_ms": 3000, "end_ms": 6000, "caption": "", "asr_text": "乙", "ocr_text": "", "caption_status": "failed", "keyframe_path": "frames/1.jpg"},
            {"shot_index": 2, "start_ms": 6000, "end_ms": 9000, "caption": "", "asr_text": "", "ocr_text": "", "caption_status": "empty", "keyframe_path": "frames/2.jpg"},
        ],
    )

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 202, response.text
    by_index = {shot["shot_index"]: shot["caption_status"] for shot in await service.video_shot_store.list_shots(doc_id)}
    assert by_index == {0: "done", 1: "pending", 2: "pending"}


async def test_retry_graph_degraded_document_is_allowed(service, session_factory):
    """D1=甲：任一腿 degraded 均可重试——图谱腿降级同属「有未成功产物」。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.update_document_status(doc_id, "ready", path_status={"vector": "done", "graph": "degraded"})

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "uploaded"


async def test_retry_processing_document_conflicts_with_new_copy(service, session_factory):
    """处理中文档不得重试（即便腿上带着历史 degraded 标记）——入口只认
    failed 或 ready+降级；409 文案同步更新（同一文档不重复启动重试）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = client.post(f"/api/knowledge-bases/{kb['id']}/documents", files={"file": ("a.md", b"# a", "text/markdown")}).json()["id"]
    store = KnowledgeStore(session_factory)
    await store.update_document_status(doc_id, "indexing", path_status={"vector": "pending", "graph": "pending", "caption": "degraded"})

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only failed or degraded documents can be retried"


async def test_wiki_generate_enqueues_background_task(service):
    generate = MagicMock(return_value=None)
    service.wiki_generate_fn = generate
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/wiki/generate")

    assert response.status_code == 202
    assert response.json()["status"] == "enqueued"
    # Task 14: default mode is incremental (only_dirty=True).
    generate.assert_called_once_with(kb["id"], True)


async def test_wiki_generate_full_mode_maps_to_full_rebuild(service):
    generate = MagicMock(return_value=None)
    service.wiki_generate_fn = generate
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/wiki/generate?mode=full")

    assert response.status_code == 202
    generate.assert_called_once_with(kb["id"], False)


async def test_wiki_generate_rejects_unknown_mode(service):
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(f"/api/knowledge-bases/{kb['id']}/wiki/generate?mode=everything").status_code == 422


async def test_wiki_generate_already_running_returns_without_requeue(service, monkeypatch):
    """P1 (2026-08-14): a trigger while a run is in flight — manual or worker
    auto, both funnels share the in-flight counter — reports
    ``already_running`` and does NOT queue a duplicate LLM run."""
    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: True)
    generate = MagicMock(return_value=None)
    service.wiki_generate_fn = generate
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/wiki/generate")

    assert response.status_code == 202
    assert response.json()["status"] == "already_running"
    generate.assert_not_called()


async def test_manual_wiki_trigger_passes_embedder(service, monkeypatch):
    """Regression: the manual trigger must pass an embedder to generate_wiki.

    generate_wiki silently skips the vector upsert when embedder is None, so a
    service that forgets it produces entries wiki_search can never find — the
    live smoke caught exactly that (entries existed, kb_wiki_entries stayed
    empty).
    """
    captured: dict = {}

    async def _fake_generate(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock(generated=0, titles=[])

    monkeypatch.setattr("app.gateway.services.knowledge_service.generate_wiki", _fake_generate)

    service.trigger_wiki_generation("kb-1")
    await asyncio.gather(*list(service._wiki_tasks))

    assert captured.get("kb_id") == "kb-1"
    assert captured.get("embedder") is not None, "manual wiki trigger must pass an embedder or entries get no vectors"
    assert captured.get("only_dirty") is True, "Task 14: manual trigger defaults to incremental mode"


async def test_wiki_regenerate_enqueues_background_task(service):
    """局部更新/重建 (2026-09-02): POST /wiki/regenerate 带上手选 entry_ids，
    经 service 触发后台重生成（与全局 generate 共用调度通道）。"""
    regenerate = MagicMock(return_value=None)
    service.wiki_regenerate_fn = regenerate
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/wiki/regenerate", json={"entry_ids": ["e1", "e2"]})

    assert response.status_code == 202
    assert response.json()["status"] == "enqueued"
    regenerate.assert_called_once_with(kb["id"], ["e1", "e2"])


async def test_wiki_regenerate_already_running_returns_without_requeue(service, monkeypatch):
    """与库级生成互斥：任何 generate/regenerate 在途时，局部重生成回
    ``already_running`` 且不重复入队（共享 in-flight 计数器）。"""
    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: True)
    regenerate = MagicMock(return_value=None)
    service.wiki_regenerate_fn = regenerate
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/wiki/regenerate", json={"entry_ids": ["e1"]})

    assert response.status_code == 202
    assert response.json()["status"] == "already_running"
    regenerate.assert_not_called()


async def test_wiki_regenerate_rejects_empty_entry_ids(service):
    """空 entry_ids 无意义 → Pydantic 422（min_length=1），不触发空跑。"""
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(f"/api/knowledge-bases/{kb['id']}/wiki/regenerate", json={"entry_ids": []}).status_code == 422


async def test_manual_wiki_regenerate_passes_embedder(service, monkeypatch):
    """Regression (mirrors the generate path): the per-entry trigger must pass
    an embedder, or the rewritten entry keeps a stale vector wiki_search cites."""
    captured: dict = {}

    async def _fake_regenerate(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock(generated=0, titles=[])

    monkeypatch.setattr("app.gateway.services.knowledge_service.regenerate_wiki_entries", _fake_regenerate)

    service.trigger_wiki_regeneration("kb-1", ["e1", "e2"])
    await asyncio.gather(*list(service._wiki_tasks))

    assert captured.get("kb_id") == "kb-1"
    assert captured.get("entry_ids") == ["e1", "e2"]
    assert captured.get("embedder") is not None, "per-entry regenerate must pass an embedder or the entry keeps a stale vector"


# ── 补充层即生成方向：保存即排队重写 (spec 2026-09-12) ──────────────────────────
#
# 保存补充层 = 用户写下了方向 ⇒ 立刻排队该条目的单条重写，而不是等下一次文档入库。
# 观察点用 `wiki_regenerate_fn`（真正的排队入口）：它被调用即"已排队"，
# 不产生后台任务，用例因此不依赖事件循环时序。


async def test_saving_supplement_queues_single_entry_rewrite(service):
    """补充层变化 ⇒ 单条重写入队，且补充层已落库。"""
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"])
    queued = MagicMock()
    service.wiki_regenerate_fn = queued

    response = client.patch(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}", json={"content": "# DeerFlow", "supplement_content": "语气严谨些"})

    assert response.status_code == 200, response.text
    queued.assert_called_once_with(kb["id"], [entry["id"]])
    stored = await service.wiki_store.get_entry(entry["id"])
    assert stored["supplement_content"] == "语气严谨些"
    assert stored["status"] == "ready"


async def test_saving_supplement_while_generation_running_falls_back_to_dirty(service, monkeypatch):
    """库级生成在跑 ⇒ 单条重写被 _IN_FLIGHT 互斥拒掉 ⇒ 退化为标脏：
    方向进下一次增量，而不是静默丢失。"""
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"])
    queued = MagicMock()
    service.wiki_regenerate_fn = queued
    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda kb_id: True)

    response = client.patch(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}", json={"content": "# DeerFlow", "supplement_content": "语气严谨些"})

    assert response.status_code == 200, response.text
    queued.assert_not_called()
    stored = await service.wiki_store.get_entry(entry["id"])
    assert stored["supplement_content"] == "语气严谨些"
    assert stored["status"] == "dirty"


async def test_editing_main_content_alone_neither_queues_nor_dirties(service):
    """只改正文不触发重写：否则用户刚手改的正文会被同一个请求立刻冲掉。"""
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"], supplement_content="语气严谨些")
    queued = MagicMock()
    service.wiki_regenerate_fn = queued

    response = client.patch(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}", json={"content": "# 我手改的正文", "supplement_content": "语气严谨些"})

    assert response.status_code == 200, response.text
    queued.assert_not_called()
    stored = await service.wiki_store.get_entry(entry["id"])
    assert stored["content"] == "# 我手改的正文"
    assert stored["supplement_content"] == "语气严谨些"
    assert stored["status"] == "ready"


async def test_clearing_supplement_queues_rewrite_too(service):
    """撤下方向同样要重写一次，否则正文会继续带着旧方向的口径。"""
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"], supplement_content="语气严谨些")
    queued = MagicMock()
    service.wiki_regenerate_fn = queued

    response = client.patch(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}", json={"content": "# DeerFlow", "supplement_content": None})

    assert response.status_code == 200, response.text
    queued.assert_called_once_with(kb["id"], [entry["id"]])
    stored = await service.wiki_store.get_entry(entry["id"])
    assert stored["supplement_content"] is None


async def test_whitespace_only_supplement_is_treated_as_unchanged(service):
    """只有空白 == 没有方向：不该因为一次「清空但留了空格」的保存就重写。"""
    client = _client(service)
    kb = _create_kb(client)
    entry = await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content="# DeerFlow", source_chunk_ids=["c1", "c2"], supplement_content="   ")
    queued = MagicMock()
    service.wiki_regenerate_fn = queued

    response = client.patch(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}", json={"content": "# DeerFlow", "supplement_content": None})

    assert response.status_code == 200, response.text
    queued.assert_not_called()
    assert (await service.wiki_store.get_entry(entry["id"]))["status"] == "ready"


async def test_wiki_entries_list_and_detail(service):
    """Wiki tab contract (phase-2 batch-1): list is summary-only (no full
    content), detail carries the full entry; both scoped to the kb."""
    client = _client(service)
    kb = _create_kb(client)
    long_content = " DeerFlow 是一个超级代理系统。" * 20
    await service.wiki_store.upsert_entry(kb["id"], title="DeerFlow", content=long_content, source_chunk_ids=["d#0000"])
    await service.wiki_store.upsert_entry(kb["id"], title="Gateway", content="网关简介", source_chunk_ids=["d#0001"], status="dirty")

    listing = client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries")
    assert listing.status_code == 200
    payload = listing.json()
    # Wiki 更新状态可见 (2026-08-14): the list payload carries the
    # library-level generation flag so the wiki tab can render 更新中 and
    # poll until the run finishes — no cross-correlating the documents query.
    assert payload["generation"] == "idle"
    # P1 失败可见性: terminal status of the most recent run (null = never ran
    # in this process) so a crashed run never masquerades as 已更新.
    assert payload["last_run"] is None
    items = {item["title"]: item for item in payload["entries"]}
    assert set(items) == {"DeerFlow", "Gateway"}
    deerflow = items["DeerFlow"]
    assert set(deerflow) == {"id", "title", "summary", "status", "updated_at"}
    assert deerflow["summary"] == long_content[:120]
    assert len(deerflow["summary"]) == 120
    assert items["Gateway"]["status"] == "dirty"
    assert items["Gateway"]["summary"] == "网关简介"

    detail = client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{deerflow['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "DeerFlow"
    assert body["content"] == long_content
    assert body["source_chunk_ids"] == ["d#0000"]


async def test_wiki_entry_detail_404_on_missing_or_cross_kb(service):
    client = _client(service)
    kb = _create_kb(client)
    other_kb = _create_kb(client, name="另一个库")
    entry = await service.wiki_store.upsert_entry(other_kb["id"], title="Secret", content="x", source_chunk_ids=[])

    assert client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries/missing").status_code == 404
    # an entry that exists but belongs to another kb must not leak
    assert client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries/{entry['id']}").status_code == 404
    assert client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries").json() == {"entries": [], "generation": "idle", "last_run": None}


async def test_wiki_entries_list_reports_last_run_failure(service, monkeypatch):
    """P1 (2026-08-14): after a failed run the entries payload reports
    ``last_run == "failed"`` so the frontend can toast 更新失败 instead of
    the success copy."""
    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_last_run_status", lambda _kb_id: "failed")
    client = _client(service)
    kb = _create_kb(client)

    payload = client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries").json()

    assert payload["last_run"] == "failed"


async def test_wiki_entries_list_reports_generation_in_flight(service, monkeypatch):
    """Wiki 更新状态可见 (2026-08-14): while a generation run is in flight
    (manual button or worker auto trigger), the entries payload reports
    ``generation == "generating"`` so the wiki tab switches dirty badges to
    更新中 and polls until the run drains."""
    monkeypatch.setattr("app.gateway.services.knowledge_service.wiki_generation_in_progress", lambda _kb_id: True)
    client = _client(service)
    kb = _create_kb(client)

    payload = client.get(f"/api/knowledge-bases/{kb['id']}/wiki/entries").json()

    assert payload["generation"] == "generating"
    assert payload["entries"] == []
