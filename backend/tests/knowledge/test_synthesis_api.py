"""Contract tests for the eval question synthesis endpoints (spec 2026-08-28 §6).

POST   ``/api/knowledge-bases/{kb_id}/eval/questions/synthesize`` — 202 幂等
触发（文档不存在/无切片 → 409；count 1–10 之外 → 422；空 doc_ids → 422）。
2026-09-02 起触发体为 ``doc_ids: list[str]``（多篇联合出题，路线二）。
GET    ``.../synthesize`` — 状态（in_progress + 暂存候选 + 元数据）。
POST   ``.../synthesize/{candidate_id}/accept`` — 201 入库并从暂存移除（404 未知）。
DELETE ``.../synthesize/{candidate_id}`` — 204 忽略候选（404 未知）。

基建对齐 ``test_eval_runs_api.py``：注入 ``synthesis_trigger_fn`` 假调度器，
候选题暂存经真实 ``synthesis.synthesize_for_docs``（stub LLM）播种。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.eval import synthesis
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))
DOC = "a" * 32
DOC_B = "b" * 32


@pytest.fixture(autouse=True)
def _drain_synthesis_registry():
    """模块级 `_SYNTH_IN_FLIGHT` 全局共享——用例间强制清零防串扰。"""
    synthesis._SYNTH_IN_FLIGHT.clear()
    yield
    synthesis._SYNTH_IN_FLIGHT.clear()


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


def _synth_service(session_factory, tmp_path, trigger) -> KnowledgeService:
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
        synthesis_trigger_fn=trigger,
    )


def _client(service: KnowledgeService) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=_owner)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient) -> dict:
    response = client.post("/api/knowledge-bases", json={"name": "合成题库", "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_indexed_doc(service: KnowledgeService, kb_id: str, doc_id: str = DOC, chunk_count: int = 2) -> None:
    """种一篇「已索引」文档：文档行 + 切片行（触发前置守卫要求有切片）。"""
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="Java 并发.md", size_bytes=100, storage_path=f"/tmp/{doc_id}.md")
    if chunk_count:
        await service.store.insert_chunks([{"chunk_id": f"{doc_id}#{index:04d}", "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, "text": f"切片 {index} 的内容。"} for index in range(1, chunk_count + 1)])


class _StubLLM:
    def __init__(self, content: str):
        self.content = content

    async def ainvoke(self, messages):
        return SimpleNamespace(content=self.content)


_GOOD_PAYLOAD = json.dumps(
    {
        "questions": [
            {"query": "切片一讲了什么？", "category": "fact", "expected_paths": ["vector"], "chunk_refs": [1], "reference_answer": "切片 1 的内容。"},
            {"query": "两个切片有什么联系？", "category": "concept", "expected_paths": ["vector", "wiki"], "chunk_refs": [1, 2], "reference_answer": "综合两片：切片 1 的内容与切片 2 的内容。"},
        ]
    },
    ensure_ascii=False,
)


async def _seed_staging(service: KnowledgeService, kb_id: str) -> list[dict]:
    """经真实合成链路播种暂存（stub LLM），返回候选行。"""
    chunks = await service.store.list_chunks(DOC)
    await synthesis.synthesize_for_docs(
        kb_id,
        docs=[(DOC, "Java 并发.md", chunks)],
        count=2,
        staging_path=service._synthesis_staging_path(kb_id),
        llm_factory=lambda: _StubLLM(_GOOD_PAYLOAD),
    )
    return (await synthesis.load_staging(service._synthesis_staging_path(kb_id)))["candidates"]


def _url(kb_id: str, suffix: str = "") -> str:
    return f"/api/knowledge-bases/{kb_id}/eval/questions/synthesize{suffix}"


# ── 触发 ─────────────────────────────────────────────────────────────────


async def test_trigger_returns_202_enqueued_and_schedules_once(session_factory, tmp_path) -> None:
    # 假调度器（eval-runs 同款先例）：begin 在调度前同步计数，假调度不 drain，
    # in-flight 状态确定可断言；手动 drain 模拟后台落完后可重新触发。
    trigger = MagicMock()
    service = _synth_service(session_factory, tmp_path, trigger)
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])

    response = client.post(_url(kb["id"]), json={"doc_ids": [DOC], "count": 5})

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "enqueued"}
    trigger.assert_called_once_with(kb["id"], doc_ids=[DOC], count=5)
    assert synthesis.synthesis_in_progress(kb["id"]) is True

    response = client.post(_url(kb["id"]), json={"doc_ids": [DOC], "count": 5})
    assert response.json() == {"status": "already_running"}
    trigger.assert_called_once()

    # drain 后可重新触发，调度器恰好被打两次。
    synthesis.end_synthesis(kb["id"])
    third = client.post(_url(kb["id"]), json={"doc_ids": [DOC], "count": 5})
    assert third.json() == {"status": "enqueued"}
    assert trigger.call_count == 2
    synthesis.end_synthesis(kb["id"])


async def test_trigger_multi_doc_passes_all_ids_to_scheduler(session_factory, tmp_path) -> None:
    # 多篇联合触发：两篇都已索引 → 调度器收到全部 id（保持入参顺序、去重）。
    trigger = MagicMock()
    service = _synth_service(session_factory, tmp_path, trigger)
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"], doc_id=DOC)
    await _seed_indexed_doc(service, kb["id"], doc_id=DOC_B, chunk_count=1)

    response = client.post(_url(kb["id"]), json={"doc_ids": [DOC, DOC_B, DOC], "count": 8})

    assert response.status_code == 202, response.text
    trigger.assert_called_once_with(kb["id"], doc_ids=[DOC, DOC_B], count=8)
    synthesis.end_synthesis(kb["id"])


async def test_trigger_unknown_or_chunkless_doc_maps_to_409(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(_url(kb["id"]), json={"doc_ids": ["missing-doc"]}).status_code == 409

    await _seed_indexed_doc(service, kb["id"], doc_id=DOC_B, chunk_count=0)
    assert client.post(_url(kb["id"]), json={"doc_ids": [DOC_B]}).status_code == 409, "无切片文档不可合成"

    # 多篇中任一篇未就绪 → 整体 409（宁可明确拒绝，不产出半截合成）。
    await _seed_indexed_doc(service, kb["id"], doc_id=DOC)
    assert client.post(_url(kb["id"]), json={"doc_ids": [DOC, DOC_B]}).status_code == 409


async def test_trigger_unknown_kb_404(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)

    assert client.post(_url("kb-missing"), json={"doc_ids": [DOC]}).status_code == 404


async def test_trigger_empty_doc_ids_422(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(_url(kb["id"]), json={"doc_ids": []}).status_code == 422


@pytest.mark.parametrize("count", [0, 11])
async def test_trigger_count_out_of_bounds_422(session_factory, tmp_path, count: int) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])

    assert client.post(_url(kb["id"]), json={"doc_ids": [DOC], "count": count}).status_code == 422


# ── 状态 ─────────────────────────────────────────────────────────────────


async def test_status_without_staging_is_empty_not_error(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(_url(kb["id"]))

    assert response.status_code == 200, response.text
    assert response.json() == {"in_progress": False, "candidates": [], "generated_at": None, "doc_ids": [], "dropped": 0}


async def test_status_returns_staged_candidates_and_metadata(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])
    staged = await _seed_staging(service, kb["id"])

    body = client.get(_url(kb["id"])).json()

    assert body["in_progress"] is False
    assert body["doc_ids"] == [DOC]
    assert body["dropped"] == 0
    assert body["generated_at"]
    assert [c["candidate_id"] for c in body["candidates"]] == [c["candidate_id"] for c in staged]
    assert body["candidates"][0]["relevant_chunk_ids"] == [f"{DOC}#0001"]


async def test_status_reports_in_progress_flag(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    assert synthesis.begin_synthesis(kb["id"]) is True
    assert client.get(_url(kb["id"])).json()["in_progress"] is True
    synthesis.end_synthesis(kb["id"])
    assert client.get(_url(kb["id"])).json()["in_progress"] is False


# ── 审核：采纳 / 忽略 ────────────────────────────────────────────────────


async def test_accept_moves_candidate_into_bank_and_returns_question(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])
    staged = await _seed_staging(service, kb["id"])
    target = staged[1]

    response = client.post(_url(kb["id"], f"/{target['candidate_id']}/accept"))

    assert response.status_code == 201, response.text
    question = response.json()
    assert question["id"].startswith("q_") and question["id"] != target["candidate_id"]
    assert question["expected_paths"] == ["vector", "wiki"]
    assert question["relevant_chunk_ids"] == [f"{DOC}#0001", f"{DOC}#0002"]
    # 候选从暂存消失、题目进题库（唯一写路径）。
    remaining = client.get(_url(kb["id"])).json()["candidates"]
    assert [c["candidate_id"] for c in remaining] == [staged[0]["candidate_id"]]
    bank = client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()
    assert bank["total"] == 1 and bank["questions"][0]["id"] == question["id"]


async def test_accept_unknown_candidate_404(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(_url(kb["id"], "/c_missing0/accept")).status_code == 404


_MISMATCH_PAYLOAD = json.dumps(
    {
        "questions": [
            {"query": "什么是装箱？", "category": "fact", "expected_paths": ["vector"], "chunk_refs": [2], "reference_answer": "装箱是把基本数据类型转成包装类型。"},
        ]
    },
    ensure_ascii=False,
)


async def test_accept_misanchored_candidate_is_422_and_ack_overrides(session_factory, tmp_path) -> None:
    """accept 口过闸（spec 2026-10-05 D1=甲′）：q008 形状候选 422 回显机器依据、
    候选留暂存不入库；带 anchor_ack 重提放行。"""
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])
    chunks = await service.store.list_chunks(DOC)
    await synthesis.synthesize_for_docs(
        kb_id=kb["id"],
        docs=[(DOC, "Java 并发.md", chunks)],
        count=1,
        staging_path=service._synthesis_staging_path(kb["id"]),
        llm_factory=lambda: _StubLLM(_MISMATCH_PAYLOAD),
    )
    target = (await synthesis.load_staging(service._synthesis_staging_path(kb["id"])))["candidates"][0]

    response = client.post(_url(kb["id"], f"/{target['candidate_id']}/accept"))

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["reason"] in ("mismatch", "zero_hit")
    # 拦截不入库、候选留在暂存（可改正或确认后重提）。
    assert [c["candidate_id"] for c in client.get(_url(kb["id"])).json()["candidates"]] == [target["candidate_id"]]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["total"] == 0

    overridden = client.post(_url(kb["id"], f"/{target['candidate_id']}/accept"), json={"anchor_ack": True})

    assert overridden.status_code == 201, overridden.text
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["total"] == 1


async def test_reject_removes_candidate_without_touching_bank(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_indexed_doc(service, kb["id"])
    staged = await _seed_staging(service, kb["id"])

    response = client.delete(_url(kb["id"], f"/{staged[0]['candidate_id']}"))

    assert response.status_code == 204
    remaining = client.get(_url(kb["id"])).json()["candidates"]
    assert [c["candidate_id"] for c in remaining] == [staged[1]["candidate_id"]]
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval/questions").json()["total"] == 0


async def test_reject_unknown_candidate_404(session_factory, tmp_path) -> None:
    service = _synth_service(session_factory, tmp_path, MagicMock())
    client = _client(service)
    kb = _create_kb(client)

    assert client.delete(_url(kb["id"], "/c_missing0")).status_code == 404


# ── 编排兜底 ─────────────────────────────────────────────────────────────


async def test_runtime_failure_drains_in_flight_and_keeps_existing_staging(session_factory, tmp_path, monkeypatch) -> None:
    # 运行期异常（合成中途炸）→ in-flight drain（可重新触发）、既有暂存不动。
    service = _synth_service(session_factory, tmp_path, MagicMock())
    kb_id = "kb-fail"
    await _seed_indexed_doc(service, kb_id)
    staged = await _seed_staging(service, kb_id)

    async def _boom(*args, **kwargs):
        raise RuntimeError("llm gateway down")

    monkeypatch.setattr(synthesis, "synthesize_for_docs", _boom)
    assert synthesis.begin_synthesis(kb_id) is True

    await service._run_question_synthesis(kb_id, doc_ids=[DOC], count=2)

    assert synthesis.synthesis_in_progress(kb_id) is False, "finally 必须 drain，否则后续触发永远 already_running"
    data = await synthesis.load_staging(service._synthesis_staging_path(kb_id))
    assert [c["candidate_id"] for c in data["candidates"]] == [c["candidate_id"] for c in staged], "失败不动既有暂存"
