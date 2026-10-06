"""Contract tests for GET /api/knowledge-bases/{kb_id}/graph (spec §4 P1).

图数据端点：全量实体/关系 + Louvain 社区标注。无缓存（百级图毫秒级现算），
种子经真实 GraphStore 落 SQLite——端点行为与生产路径零漂移。
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=None,  # 图端点不触向量存储
        graph_store=GraphStore(session_factory),
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


def _create_kb(client: TestClient, name: str = "JVM 笔记") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_graph(service: KnowledgeService, kb_id: str) -> None:
    """一个连通簇 {JVM, 堆内存, 字节码} + 孤立实体；JVM 被两个切片提及。"""
    graph = service.graph_store
    assert graph is not None
    await graph.upsert_entities(
        kb_id,
        [
            ExtractedEntity(name="JVM", type="组件", description="Java 虚拟机"),
            ExtractedEntity(name="堆内存", type="概念", description="对象实例存放区"),
        ],
        chunk_id="d#0000",
    )
    await graph.upsert_entities(
        kb_id,
        [
            ExtractedEntity(name="JVM", type="组件", description=""),  # 二次提及
            ExtractedEntity(name="字节码", type="概念", description="中间码"),
        ],
        chunk_id="d#0001",
    )
    await graph.upsert_entities(
        kb_id,
        [ExtractedEntity(name="孤立概念", type="概念", description="无关系")],
        chunk_id="d#0002",
    )
    await graph.upsert_relations(
        kb_id,
        [
            ExtractedRelation(source="JVM", target="堆内存", relation="包含", description=""),
            ExtractedRelation(source="JVM", target="字节码", relation="解释", description=""),
        ],
        chunk_id="d#0000",
    )


async def test_graph_returns_full_contract_with_communities(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_graph(service, kb["id"])

    response = client.get(f"/api/knowledge-bases/{kb['id']}/graph")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kb_id"] == kb["id"]
    assert body["stats"] == {"node_count": 4, "edge_count": 2, "community_count": 2}

    nodes = {n["id"]: n for n in body["nodes"]}
    assert set(nodes) == {"JVM", "堆内存", "字节码", "孤立概念"}
    jvm = nodes["JVM"]
    assert jvm["type"] == "组件"
    assert "Java 虚拟机" in jvm["description"]
    # mention_count = len(source_chunk_ids)：JVM 被 d#0000/d#0001 两个切片提及。
    assert jvm["mention_count"] == 2
    assert nodes["堆内存"]["mention_count"] == 1
    # Task 3 扩展：source_chunk_ids 透传——前端实体钻取链路（点击 → 关联切片
    # → 文档抽屉）的唯一数据来源；chunk_id 内嵌 doc_id（`{doc_id}#%04d`），
    # 前端无需二次查询即可跳文档。
    assert jvm["source_chunk_ids"] == ["d#0000", "d#0001"]
    assert nodes["孤立概念"]["source_chunk_ids"] == ["d#0002"]
    # 社区：连通簇同社区，孤立实体独立社区；大簇拿社区 0（规模降序）。
    assert isinstance(jvm["community"], int)
    assert jvm["community"] == nodes["堆内存"]["community"] == nodes["字节码"]["community"] == 0
    assert nodes["孤立概念"]["community"] == 1

    assert body["edges"] == [
        {"source": "JVM", "target": "堆内存", "relation": "包含", "description": ""},
        {"source": "JVM", "target": "字节码", "relation": "解释", "description": ""},
    ]


async def test_graph_communities_are_deterministic_across_requests(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_graph(service, kb["id"])

    first = client.get(f"/api/knowledge-bases/{kb['id']}/graph").json()
    second = client.get(f"/api/knowledge-bases/{kb['id']}/graph").json()
    first_map = {n["id"]: n["community"] for n in first["nodes"]}
    second_map = {n["id"]: n["community"] for n in second["nodes"]}
    assert first_map == second_map


async def test_graph_empty_kb_returns_empty_graph(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/graph")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["stats"] == {"node_count": 0, "edge_count": 0, "community_count": 0}


async def test_graph_unknown_kb_returns_404(service) -> None:
    client = _client(service)
    response = client.get("/api/knowledge-bases/kb-missing/graph")
    assert response.status_code == 404


# ── Task 7b（LOD 分层渲染）：社区汇总字段 ─────────────────────────────────
# cluster/hub 层与 SuperNode 着色（主导类型）需要社区级聚合数据；前端全量 nodes
# 也能算，但后端预计算为「分层加载（先 super 后 detail）」留出契约空间，且保证
# 排序规则（mention 降序、同数按名字典序）的单一事实源。


async def test_graph_includes_community_summaries(service) -> None:
    """响应含 communities 汇总：memberCount / totalMentions / topMembers(Top3) / dominantType。"""
    client = _client(service)
    kb = _create_kb(client)
    await _seed_graph(service, kb["id"])

    body = client.get(f"/api/knowledge-bases/{kb['id']}/graph").json()
    communities = {c["id"]: c for c in body["communities"]}
    assert set(communities) == {0, 1}

    main = communities[0]  # {JVM(mention 2), 堆内存(1), 字节码(1)}
    assert main["memberCount"] == 3
    assert main["totalMentions"] == 4
    # mention 降序，同数按名字典序：JVM(2) > 堆内存(1) / 字节码(1)（「堆」U+5806 < 「字」U+5B57）。
    assert main["topMembers"] == [
        {"id": "JVM", "mention_count": 2},
        {"id": "堆内存", "mention_count": 1},
        {"id": "字节码", "mention_count": 1},
    ]
    # 主导类型：组件(JVM=2) vs 概念(堆+字节码=2) 同数 → type 名字典序「概念」(U+6982 < U+7EC4)。
    assert main["dominantType"] == "概念"


async def test_graph_community_summary_single_member(service) -> None:
    """单成员社区 topMembers 长度 1（无填充无截断错误）。"""
    client = _client(service)
    kb = _create_kb(client)
    await _seed_graph(service, kb["id"])

    body = client.get(f"/api/knowledge-bases/{kb['id']}/graph").json()
    communities = {c["id"]: c for c in body["communities"]}
    isolated = communities[1]  # {孤立概念(mention 1)}
    assert isolated["memberCount"] == 1
    assert isolated["totalMentions"] == 1
    assert isolated["topMembers"] == [{"id": "孤立概念", "mention_count": 1}]
    assert isolated["dominantType"] == "概念"


async def test_graph_empty_kb_communities_empty(service) -> None:
    """空 KB → communities 空数组（空社区跳过，不产零成员条目）。"""
    client = _client(service)
    kb = _create_kb(client)

    body = client.get(f"/api/knowledge-bases/{kb['id']}/graph").json()
    assert body["communities"] == []
