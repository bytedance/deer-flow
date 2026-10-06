"""Contract tests for the eval question bank CRUD endpoints (spec 2026-08-27 §4.2).

GET    ``/api/knowledge-bases/{kb_id}/eval/questions`` — 读全量题库（空文件 → 空表）。
POST   ``/api/knowledge-bases/{kb_id}/eval/questions`` — 新增一题（id 服务端生成，
带 id 字段 422；字段违例 422 detail 含字段名）。
DELETE ``/api/knowledge-bases/{kb_id}/eval/questions/{question_id}`` — 删一题
（204 / 404）。存量题库文件脏 → 读改写均 500 且 detail 指行号（不静默跳过）。

基建对齐 ``test_eval_runs_api.py``：真实 KnowledgeService + session_factory。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.chunks_collection = "kb_chunks"
    vector_store.entities_collection = "kb_entities"
    vector_store.wiki_entries_collection = "kb_wiki"
    vector_store.manual_cards_collection = "kb_cards"
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
        worker=None,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient, name: str = "评测题库") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


def _golden_file(service: KnowledgeService, kb_id: str) -> Path:
    return Path(service.data_dir) / "knowledge" / kb_id / "golden.jsonl"


def _valid_body(**overrides) -> dict:
    body = {
        "query": "什么是退休年龄",
        "category": "fact",
        "expected_paths": ["vector"],
        "relevant_chunk_ids": [],
        "relevant_entities": [],
        "reference_answer": None,
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None or k == "reference_answer"}


# ── GET ──────────────────────────────────────────────────────────────────


async def test_empty_bank_returns_empty_list(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions")

    assert response.status_code == 200, response.text
    assert response.json() == {"questions": [], "total": 0}


async def test_get_returns_full_question_fields(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    # 锚定核验（2026-10-05）后，锚定片必须真实存在——种出用例声明的那片。
    doc_id = "a" * 32
    await service.store.create_document(doc_id=doc_id, kb_id=kb["id"], uploader_id=OWNER_ID, name="图谱.docx", size_bytes=1, storage_path="p")
    await service.store.insert_chunks([{"chunk_id": f"{doc_id}#0001", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 1, "text": "图谱路径。"}])

    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(
            query="图检索走哪条路",
            category="relation",
            expected_paths=["graph"],
            relevant_chunk_ids=["a" * 32 + "#0001"],
            relevant_entities=["退休"],
            reference_answer="图谱路径。",
        ),
    ).json()

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()
    assert body["total"] == 1
    question = body["questions"][0]
    assert question["id"] == created["id"]
    assert question["query"] == "图检索走哪条路"
    assert question["category"] == "relation"
    assert question["expected_paths"] == ["graph"]  # 请求/响应同批新契约（spec §3 Task 4）
    assert question["relevant_chunk_ids"] == ["a" * 32 + "#0001"]
    assert question["relevant_entities"] == ["退休"]
    assert question["reference_answer"] == "图谱路径。"


async def test_create_derives_entities_from_anchored_chunks_when_body_empty(service) -> None:
    """实体标注派生（2026-09-08）：造题面本无实体输入，body 空 entities +
    有锚定时 service 按锚定切片 entities 保序去重并集派生（与合成路同源）；
    body 显式非空尊重原值不被派生覆盖。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = "d" * 32
    await service.store.create_document(doc_id=doc_id, kb_id=kb["id"], uploader_id=OWNER_ID, name="java基础.docx", size_bytes=1, storage_path="p")
    await service.store.insert_chunks(
        [
            {"chunk_id": f"{doc_id}#0001", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 1, "text": "t1", "entities": ["Integer", "int"]},
            {"chunk_id": f"{doc_id}#0002", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 2, "text": "t2", "entities": ["int"]},
        ]
    )

    derived = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001", f"{doc_id}#0002"], relevant_entities=[]),
    ).json()
    assert derived["relevant_entities"] == ["Integer", "int"]

    explicit = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001"], relevant_entities=["手动"]),
    ).json()
    assert explicit["relevant_entities"] == ["手动"]


async def test_get_dirty_file_maps_to_500_with_line_hint(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    path = _golden_file(service, kb["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    good = '{"id": "q_ok00001", "query": "有效问题", "expected_path": "vector", "relevant_chunk_ids": [], "relevant_entities": [], "category": "fact"}'
    path.write_text(good + '\n{"broken": ', encoding="utf-8")

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions")

    assert response.status_code == 500
    assert "golden.jsonl" in response.json()["detail"]


async def test_unknown_kb_404_on_get(service) -> None:
    client = _client(service)

    assert client.get("/api/knowledge-bases/kb-missing/eval/questions").status_code == 404


# ── POST ─────────────────────────────────────────────────────────────────


async def test_post_creates_question_with_server_generated_id(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json=_valid_body())

    assert response.status_code == 201, response.text
    question = response.json()
    assert question["id"].startswith("q_")
    # 文件真实落盘且可被守卫加载器回读（一行一题）。
    lines = _golden_file(service, kb["id"]).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


async def test_post_with_explicit_id_field_is_422(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(id="hacked"),
    )

    assert response.status_code == 422


async def test_post_schema_violation_422_detail_names_the_field(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(category="vibe"),
    )

    assert response.status_code == 422
    assert "category" in response.json()["detail"]


async def test_post_bad_chunk_id_format_422(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=["not-a-chunk-id"]),
    )

    assert response.status_code == 422


# ── expected_paths 多路契约（spec 2026-08-28 §3，破坏式切换）──────────────


async def test_post_multi_path_roundtrips_through_get(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(expected_paths=["vector", "graph"]),
    )

    assert created.status_code == 201, created.text
    assert created.json()["expected_paths"] == ["vector", "graph"]
    assert created.json().get("expected_path") is None  # 响应不留 legacy 键（无此字段）
    listed = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["questions"]
    assert listed[0]["expected_paths"] == ["vector", "graph"]


async def test_post_legacy_single_field_is_422(service) -> None:
    # API 层不做历史兼容（唯一消费者前端同批切换）——旧字段被 extra=forbid 拒绝。
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body() | {"expected_path": "vector"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("paths", [[], ["vector", "graph", "wiki", "vector"]])
async def test_post_expected_paths_length_bounds_422(service, paths) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(expected_paths=paths),
    )

    assert response.status_code == 422


async def test_post_bad_path_enum_422_names_the_field(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(expected_paths=["teleport"]),
    )

    assert response.status_code == 422
    assert "expected_paths" in response.json()["detail"]


async def test_unknown_kb_404_on_post(service) -> None:
    client = _client(service)

    response = client.post("/api/knowledge-bases/kb-missing/eval/questions", json=_valid_body())

    assert response.status_code == 404


# ── 锚定核验（spec 2026-10-05 D1=甲′）────────────────────────────────────


async def test_post_misanchored_question_is_422_with_structured_detail(service) -> None:
    """create 口过闸：q008 形状（答案锚贴到不含答案术语的切片）422 回显机器
    依据；带 anchor_ack 重存放行（人做最后检验）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = "c" * 32
    await service.store.create_document(doc_id=doc_id, kb_id=kb["id"], uploader_id=OWNER_ID, name="java基础.docx", size_bytes=1, storage_path="p")
    await service.store.insert_chunks(
        [
            {"chunk_id": f"{doc_id}#0001", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 1, "text": "什么是自动拆箱/装箱？装箱：将基本数据类型转换为包装类型。拆箱：将包装类型转换为基本数据类型。"},
            {"chunk_id": f"{doc_id}#0002", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 2, "text": "Integer 会缓存 -128 到 127 的对象，==比较的是引用地址。"},
        ]
    )
    body = _valid_body(
        query="什么是自动拆箱和装箱？",
        relevant_chunk_ids=[f"{doc_id}#0002"],
        reference_answer="装箱是把基本数据类型转成包装类型；拆箱是把包装类型转成基本数据类型。",
    )

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json=body)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["reason"] in ("mismatch", "zero_hit")
    assert "装箱" in detail["miss_terms"]
    assert detail["suggested_chunk"] == f"{doc_id}#0001"
    # 拦截即不落盘。
    assert _golden_file(service, kb["id"]).exists() is False or not _golden_file(service, kb["id"]).read_text(encoding="utf-8").strip()

    overridden = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={**body, "anchor_ack": True})

    assert overridden.status_code == 201, overridden.text


# ── DELETE ───────────────────────────────────────────────────────────────


async def test_delete_then_missing_404(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    question = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json=_valid_body()).json()

    first = client.delete(f"/api/knowledge-bases/{kb['id']}/eval/questions/{question['id']}")

    assert first.status_code == 204
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["total"] == 0
    again = client.delete(f"/api/knowledge-bases/{kb['id']}/eval/questions/{question['id']}")
    assert again.status_code == 404


async def test_unknown_kb_404_on_delete(service) -> None:
    client = _client(service)

    assert client.delete("/api/knowledge-bases/kb-missing/eval/questions/q_whatever").status_code == 404


# ── PATCH 改锚 + 悬空派生（spec 2026-10-05 anchor-edit 对，D4=甲′）───────


async def _seed_chunks(service: KnowledgeService, kb_id: str, doc_id: str, chunks: list[dict]) -> str:
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="java基础.docx", size_bytes=1, storage_path="p")
    await service.store.insert_chunks([{"chunk_id": f"{doc_id}#{index:04d}", "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, **rest} for index, rest in enumerate(chunks, start=1)])
    return doc_id


async def test_patch_misanchored_is_422_structured_and_ack_overrides(service) -> None:
    """改锚同闸：贴错锚 422 回显机器依据；anchor_ack 一次性放行（①②）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(
        service,
        kb["id"],
        "c" * 32,
        [
            {"text": "什么是自动拆箱/装箱？装箱：将基本数据类型转换为包装类型。"},
            {"text": "Integer 会缓存 -128 到 127 的对象。"},
        ],
    )
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001"], reference_answer="装箱是把基本数据类型转成包装类型。"),
    ).json()

    response = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0002"]},
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["reason"] in ("mismatch", "zero_hit")
    assert "装箱" in detail["miss_terms"]
    assert detail["suggested_chunk"] == f"{doc_id}#0001"
    # 拦截即不落库。
    stored = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["questions"][0]
    assert stored["relevant_chunk_ids"] == [f"{doc_id}#0001"]

    overridden = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0002"], "anchor_ack": True},
    )

    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["relevant_chunk_ids"] == [f"{doc_id}#0002"]


async def test_patch_dangling_anchor_blocks_even_with_ack(service) -> None:
    """悬空锚（片不存在）无条件拦，ack 也放不过（③）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(service, kb["id"], "b" * 32, [{"text": "装箱：将基本数据类型转换为包装类型。"}])
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001"], reference_answer="装箱是转换。"),
    ).json()

    blocked = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0009"]},
    )

    assert blocked.status_code == 422
    assert blocked.json()["detail"]["reason"] == "missing_chunk"

    still_blocked = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0009"], "anchor_ack": True},
    )

    assert still_blocked.status_code == 422
    assert still_blocked.json()["detail"]["reason"] == "missing_chunk"


async def test_patch_shrinks_entities_to_new_anchor_vocab(service) -> None:
    """D4=甲′ 跟锚收缩：只删失去支撑的、不新增——精选子集保住（④）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(
        service,
        kb["id"],
        "d" * 32,
        [
            {"text": "StringBuffer 可变且线程安全。", "entities": ["String", "StringBuffer"]},
            {"text": "StringBuffer 可变但非线程安全。", "entities": ["StringBuffer", "StringBuilder"]},
        ],
    )
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(
            relevant_chunk_ids=[f"{doc_id}#0001"],
            relevant_entities=["String", "StringBuffer"],
            reference_answer="StringBuffer 可变。",
        ),
    ).json()

    patched = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0002"]},
    )

    assert patched.status_code == 200, patched.text
    question = patched.json()
    assert question["relevant_chunk_ids"] == [f"{doc_id}#0002"]
    # String 失去支撑被删；StringBuilder 不在旧实体里=不新增。
    assert question["relevant_entities"] == ["StringBuffer"]


async def test_patch_keeps_other_fields_untouched(service) -> None:
    """改锚只动锚（+实体收缩）：题面/分类/路径/参考答案原样钉死（⑤）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(service, kb["id"], "e" * 32, [{"text": "装箱：转换。"}, {"text": "拆箱：逆转换。"}])
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(
            query="什么是装箱",
            category="relation",
            expected_paths=["vector", "graph"],
            relevant_chunk_ids=[f"{doc_id}#0001"],
            reference_answer="装箱：转换。",
        ),
    ).json()

    patched = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": [f"{doc_id}#0002"]},
    )

    assert patched.status_code == 200, patched.text
    question = patched.json()
    assert question["query"] == "什么是装箱"
    assert question["category"] == "relation"
    assert question["expected_paths"] == ["vector", "graph"]
    assert question["reference_answer"] == "装箱：转换。"


async def test_patch_unknown_question_404(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/q_nope0000",
        json={"relevant_chunk_ids": []},
    )

    assert response.status_code == 404


async def test_patch_clear_anchors_unanchors_and_shrinks_entities(service) -> None:
    """清空勾选=解除锚定（⑧）；实体跟锚收缩到空词表=清空。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(service, kb["id"], "f" * 32, [{"text": "装箱：转换。", "entities": ["装箱"]}])
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001"], relevant_entities=["装箱"], reference_answer="装箱：转换。"),
    ).json()

    patched = client.patch(
        f"/api/knowledge-bases/{kb['id']}/eval/questions/{created['id']}",
        json={"relevant_chunk_ids": []},
    )

    assert patched.status_code == 200, patched.text
    question = patched.json()
    assert question["relevant_chunk_ids"] == []
    assert question["relevant_entities"] == []


async def test_list_marks_missing_chunk_ids_three_states(service) -> None:
    """读时派生 missing_chunk_ids：悬空/存活/无锚三态（⑦）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(service, kb["id"], "a" * 32, [{"text": "装箱：转换。"}, {"text": "拆箱：逆转换。"}])
    live = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0001"], reference_answer="装箱：转换。"),
    ).json()
    dying = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(relevant_chunk_ids=[f"{doc_id}#0002"], reference_answer="拆箱：逆转换。"),
    ).json()
    client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json=_valid_body(query="无锚题"))

    await service.store.delete_chunk(f"{doc_id}#0002")

    rows = {row["id"]: row for row in client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["questions"]}
    assert rows[live["id"]]["missing_chunk_ids"] == []
    assert rows[dying["id"]]["missing_chunk_ids"] == [f"{doc_id}#0002"]
    unanchored = [row for row in rows.values() if row["query"] == "无锚题"][0]
    assert unanchored["missing_chunk_ids"] == []


# ── 读时词面派生（spec 2026-10-05 §2④，B1=甲「存疑」/B2=乙照标）────────────


async def test_list_derives_anchor_mismatch_when_chunk_content_swapped(service) -> None:
    """落空＝锚在、内容被换（重切同号不同文 / 切片编辑）：读时派生
    anchor_mismatch（判定 / 命中 / suggested_chunk / 疑片 chunk_ids），不落盘。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(
        service,
        kb["id"],
        "a" * 32,
        [
            {"text": "装箱：将基本数据类型转换为包装类型。"},
            {"text": "拆箱：将包装类型转换为基本数据类型。"},
        ],
    )
    created = client.post(
        f"/api/knowledge-bases/{kb['id']}/eval/questions",
        json=_valid_body(
            query="什么是装箱",
            relevant_chunk_ids=[f"{doc_id}#0001"],
            reference_answer="装箱是把基本数据类型转换为包装类型。",
        ),
    ).json()
    # 闸先放行（彼时内容支撑答案），再换内容＝落空发生。
    await service.store.update_chunk_text(f"{doc_id}#0001", "StringBuilder 是可变字符序列。", 6)

    row = {r["id"]: r for r in client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["questions"]}[created["id"]]
    concern = row["anchor_mismatch"]
    assert concern["reason"] in ("mismatch", "zero_hit")
    assert "装箱" in concern["miss_terms"]
    assert concern["suggested_chunk"] == f"{doc_id}#0002"
    assert concern["chunk_ids"] == [f"{doc_id}#0001"]
    assert row["missing_chunk_ids"] == []
    # D1=甲：派生不落盘（golden 文件里没有这个键）。
    assert "anchor_mismatch" not in _golden_file(service, kb["id"]).read_text(encoding="utf-8")


async def test_list_anchor_mismatch_exemptions_and_precedence(service) -> None:
    """豁免照抄门禁 + 悬空优先：好题零标 / 无参考答案不标 / 无锚不标 /
    多片全命中不标、单片零命中才标（疑片＝零命中片）/ 短答案（|K|<2）不豁免
    （B2=乙照标）/ 有缺片只显悬空（同一判定短路，一题至多显一类警示）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _seed_chunks(
        service,
        kb["id"],
        "a" * 32,
        [
            {"text": "装箱：将基本数据类型转换为包装类型。"},
            {"text": "拆箱：将包装类型转换为基本数据类型。"},
            {"text": "StringBuilder 是可变字符序列。"},
            {"text": "装箱与拆箱是包装类型和基本数据类型的互转。"},
            {"text": "装箱：基本数据类型转包装类型。"},
            {"text": "装箱就是包装。"},
        ],
    )

    def create(query: str, **overrides) -> dict:
        response = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json=_valid_body(query=query, **overrides))
        assert response.status_code == 201, response.text
        return response.json()

    long_answer = "装箱是把基本数据类型转换为包装类型；拆箱是把包装类型转换为基本数据类型。"
    good = create("好题", relevant_chunk_ids=[f"{doc_id}#0001"], reference_answer="装箱是把基本数据类型转换为包装类型。")
    no_answer = create("无答案题", relevant_chunk_ids=[f"{doc_id}#0003"], reference_answer=None)
    unanchored = create("无锚题")
    multi_ok = create("多片全中", relevant_chunk_ids=[f"{doc_id}#0001", f"{doc_id}#0004"], reference_answer=long_answer)
    multi_swapped = create("多片一零", relevant_chunk_ids=[f"{doc_id}#0001", f"{doc_id}#0002"], reference_answer=long_answer)
    mixed = create("悬空混落空", relevant_chunk_ids=[f"{doc_id}#0002", f"{doc_id}#0005"], reference_answer=long_answer)
    short = create("短答案题", relevant_chunk_ids=[f"{doc_id}#0006"], reference_answer="装箱")

    # 落空与悬空各自发生：#0002/#0006 内容被换（零命中）、#0005 被删（缺片）。
    await service.store.update_chunk_text(f"{doc_id}#0002", "StringBuilder 是可变字符序列。", 6)
    await service.store.update_chunk_text(f"{doc_id}#0006", "可变字符序列。", 4)
    await service.store.delete_chunk(f"{doc_id}#0005")

    rows = {row["id"]: row for row in client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["questions"]}

    assert rows[good["id"]]["anchor_mismatch"] is None
    assert rows[no_answer["id"]]["anchor_mismatch"] is None
    assert rows[unanchored["id"]]["anchor_mismatch"] is None
    assert rows[multi_ok["id"]]["anchor_mismatch"] is None

    swapped = rows[multi_swapped["id"]]["anchor_mismatch"]
    assert swapped["reason"] in ("mismatch", "zero_hit")
    assert swapped["chunk_ids"] == [f"{doc_id}#0002"]
    assert rows[multi_swapped["id"]]["missing_chunk_ids"] == []

    short_concern = rows[short["id"]]["anchor_mismatch"]
    assert short_concern is not None
    assert short_concern["chunk_ids"] == [f"{doc_id}#0006"]

    # 悬空优先：缺片短路同一判定，活片上的落空暂不显（修完悬空自会浮出）。
    assert rows[mixed["id"]]["anchor_mismatch"] is None
    assert rows[mixed["id"]]["missing_chunk_ids"] == [f"{doc_id}#0005"]
