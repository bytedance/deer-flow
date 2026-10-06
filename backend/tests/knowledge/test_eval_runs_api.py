"""Contract tests for the eval-runs read endpoints (spec 2026-08-24 §4.2, plan Task 1).

GET ``/api/knowledge-bases/{kb_id}/eval-runs/latest`` — 两层各自最近一次
completed 且对应层 metrics 非空且非 ci 的运行（可来自不同运行）。
GET ``/api/knowledge-bases/{kb_id}/eval-runs/trend`` — run 级点（contract v4）
+ baseline 块 + 顶层 ``sparks``；固定近 90 天窗口，无服务端聚合粒度。
GET ``/api/knowledge-bases/{kb_id}/eval-runs/{run_id}`` — 单行完整 JSON，
drawer 数据源。

测试数据走真实写入路径 ``save_eval_run``（session_factory fixture 已初始化
全局引擎），基建对齐 ``test_vector_projection_api.py``。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.eval.persistence import save_eval_run
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


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


def _l1(recall_at_k: float = 0.8, hit_rate: float = 0.9, mrr: float = 0.7) -> dict:
    return {
        "summary": {
            "recall_at_k": recall_at_k,
            "hit_rate": hit_rate,
            "mrr": mrr,
            "path_accuracy": 1.0,
            "question_count": 20,
        },
        "fact": {
            "recall_at_k": recall_at_k,
            "hit_rate": hit_rate,
            "mrr": mrr,
            "path_accuracy": 1.0,
            "question_count": 8,
        },
    }


def _l2(faithfulness: float = 0.95) -> dict:
    return {
        "ragas": {
            "faithfulness": faithfulness,
            "answer_relevancy": 0.88,
            "context_precision": 0.91,
            "context_recall": None,
        },
        "arch_specific": {"citation_precision": 0.9, "citation_recall": 0.85, "seed_hit_rate": None},
        "path_accuracy": 0.75,
        "ragas_available": True,
        "ragas_skip_reason": None,
        "has_graph_questions": False,
    }


async def _seed_run(
    kb_id: str,
    run_id: str,
    created_at: datetime,
    *,
    layer1: dict | None = None,
    layer2: dict | None = None,
    status: str = "completed",
    environment: str = "local",
    baseline_diff: dict | None = None,
    langfuse_trace_url: str | None = None,
    mark_baseline: bool = False,
) -> None:
    saved = await save_eval_run(
        run_id=run_id,
        kb_id=kb_id,
        status=status,
        created_at=created_at,
        layer1_metrics=layer1,
        layer2_metrics=layer2,
        baseline_diff=baseline_diff,
        langfuse_trace_url=langfuse_trace_url,
        environment=environment,
        mark_baseline=mark_baseline,
    )
    assert saved == run_id


# ── latest ───────────────────────────────────────────────────────────────


async def test_latest_returns_most_recent_completed_run_per_layer(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-l1-old", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.7))
    await _seed_run(kb["id"], "run-l1-new", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.85))
    await _seed_run(
        kb["id"],
        "run-l2",
        datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
        layer2=_l2(faithfulness=0.97),
        langfuse_trace_url="https://langfuse.example/trace/1",
    )

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kb_id"] == kb["id"]
    # 两层独立取最近：layer1 取 08-20 的新运行，layer2 取 08-19。
    assert body["layer1"]["run_id"] == "run-l1-new"
    assert body["layer1"]["metrics"]["summary"]["recall_at_k"] == 0.85
    assert body["layer1"]["metrics"]["fact"]["question_count"] == 8
    assert body["layer1"]["created_at"].startswith("2026-08-20")
    layer2 = body["layer2"]
    assert layer2["run_id"] == "run-l2"
    assert layer2["ragas"]["faithfulness"] == 0.97
    assert layer2["arch_specific"]["citation_precision"] == 0.9
    # 路由命中率（总览瓦片数据源）：layer2 顶层 path_accuracy 换展示面键名
    assert layer2["routing_hit_rate"] == 0.75
    assert layer2["ragas_available"] is True
    assert layer2["has_graph_questions"] is False
    assert layer2["langfuse_trace_url"] == "https://langfuse.example/trace/1"


async def test_latest_layer_without_any_run_is_null(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-l1", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    assert body["layer1"]["run_id"] == "run-l1"
    assert body["layer2"] is None


async def test_latest_passes_through_per_question_slim_array(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    layer1 = _l1()
    layer1["questions"] = [
        {"id": "q1", "recall": 1.0, "hit": 1.0, "path_correct": True, "actual_path": "vector"},
        {"id": "q2", "recall": 0.0, "hit": 0.0, "path_correct": False, "actual_path": None},
    ]
    await _seed_run(kb["id"], "run-l1", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=layer1)

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    # 题库分诊列数据源：逐题 slim 数组原样透传（bank 按 id join）。
    assert body["layer1"]["metrics"]["questions"] == layer1["questions"]


async def test_latest_legacy_row_without_questions_key_reads_clean(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-legacy", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    # slim 数组落地前的旧运行行 simply 缺键——读集按可选键处理，不报错。
    assert "questions" not in body["layer1"]["metrics"]


async def test_latest_question_results_merge_across_runs(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    old = _l1()
    old["questions"] = [
        {"id": "q1", "recall": 1.0, "hit": 1.0, "path_correct": True, "actual_path": "vector"},
        {"id": "q2", "recall": 0.0, "hit": 0.0, "path_correct": False, "actual_path": None},
    ]
    new = _l1()
    new["questions"] = [{"id": "q2", "recall": 1.0, "hit": 1.0, "path_correct": True, "actual_path": "vector"}]
    ci = _l1()
    ci["questions"] = [{"id": "q3", "recall": 1.0, "hit": 1.0, "path_correct": True, "actual_path": "vector"}]
    await _seed_run(kb["id"], "run-old", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=old)
    await _seed_run(kb["id"], "run-new", datetime(2026, 8, 21, 9, 0, tzinfo=UTC), layer1=new)
    await _seed_run(kb["id"], "run-ci", datetime(2026, 8, 22, 9, 0, tzinfo=UTC), layer1=ci, environment="ci")

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    # 跨 run 合并：q1 保留 run-old 的结果（scoped run-new 不把它覆盖成缺失）；
    # q2 取更近的 run-new；ci 行不进读集。
    merged = {q["id"]: q for q in body["question_results"]}
    assert merged["q1"]["run_id"] == "run-old"
    assert merged["q1"]["recall"] == 1.0
    assert merged["q2"]["run_id"] == "run-new"
    assert merged["q2"]["recall"] == 1.0
    assert "q3" not in merged


async def test_latest_never_evaluated_returns_both_layers_null(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kb_id"] == kb["id"]
    assert body["layer1"] is None
    assert body["layer2"] is None
    assert body["question_results"] == []


async def test_latest_unknown_kb_404(service) -> None:
    client = _client(service)

    response = client.get("/api/knowledge-bases/kb-missing/eval-runs/latest")

    assert response.status_code == 404


async def test_latest_excludes_ci_skipped_and_error_runs(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-local", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.7))
    await _seed_run(kb["id"], "run-ci", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.99), environment="ci")
    await _seed_run(kb["id"], "run-skip", datetime(2026, 8, 21, 9, 0, tzinfo=UTC), layer2=_l2(), status="skipped")
    await _seed_run(kb["id"], "run-err", datetime(2026, 8, 22, 9, 0, tzinfo=UTC), layer2=_l2(), status="error")

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    assert body["layer1"]["run_id"] == "run-local"
    assert body["layer2"] is None


async def test_latest_surfaces_baseline_diff_when_present(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    diff = {
        "recall_at_k_delta": -0.05,
        "regression_detected": True,
        "threshold_percent": 3.0,
        "regressed_categories": ["fact"],
    }
    await _seed_run(kb["id"], "run-diff", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(), baseline_diff=diff)

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()

    assert body["layer1"]["baseline_diff"]["regression_detected"] is True
    assert body["layer1"]["baseline_diff"]["regressed_categories"] == ["fact"]


# ── trend ────────────────────────────────────────────────────────────────


async def test_trend_returns_run_level_points_in_time_order(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    now = datetime.now(UTC).replace(microsecond=0)
    early_ts = now - timedelta(hours=30)
    late_ts = now - timedelta(hours=20)
    l2_ts = now - timedelta(hours=5)
    await _seed_run(kb["id"], "run-early", early_ts, layer1=_l1(recall_at_k=0.7))
    await _seed_run(kb["id"], "run-late", late_ts, layer1=_l1(recall_at_k=0.85))
    await _seed_run(kb["id"], "run-l2", l2_ts, layer2=_l2())

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_data"] is True
    # contract v4：一 run 一点，同日多次运行各自出点（周期末次聚合退役），升序。
    assert [p["run_id"] for p in body["points"]] == ["run-early", "run-late", "run-l2"]
    first, second, third = body["points"]
    # ts = 带 UTC 偏移的完整时间戳（时区标准），非周期起点日期。
    assert first["ts"] == early_ts.isoformat()
    assert second["ts"] == late_ts.isoformat()
    assert first["ts"].endswith("+00:00")
    assert first["recall_at_k"] == 0.7
    assert second["recall_at_k"] == 0.85
    assert second["faithfulness"] is None
    assert third["recall_at_k"] is None
    assert third["faithfulness"] == 0.95
    # layer1_run_id/layer2_run_id 退役 → 单 run_id 键。
    assert "layer1_run_id" not in first and "layer2_run_id" not in third


async def test_trend_include_ci_opts_ci_rows_back_in(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-ci", datetime.now(UTC) - timedelta(days=2), layer1=_l1(), environment="ci")

    default_body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()
    assert default_body["points"] == []
    assert default_body["has_data"] is False

    with_ci = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend?include_ci=true").json()
    assert with_ci["has_data"] is True
    assert with_ci["points"][0]["run_id"] == "run-ci"


async def test_trend_baseline_block_reads_the_marked_row(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    now = datetime.now(UTC)
    await _seed_run(
        kb["id"],
        "run-base",
        now - timedelta(days=10),
        layer1=_l1(recall_at_k=0.88),
        mark_baseline=True,
    )
    await _seed_run(kb["id"], "run-new", now - timedelta(days=2), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()

    assert body["baseline"]["recall_at_k"] == 0.88
    assert body["baseline"]["threshold_percent"] == pytest.approx(3.0)
    baseline_point = next(p for p in body["points"] if p["run_id"] == "run-base")
    assert baseline_point["is_baseline_update"] is True
    other_point = next(p for p in body["points"] if p["run_id"] == "run-new")
    assert other_point["is_baseline_update"] is False


async def test_trend_baseline_block_is_null_without_marked_row(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-l1", datetime.now(UTC) - timedelta(days=2), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()

    assert body["baseline"] is None


async def test_trend_legacy_granularity_params_are_ignored(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-1", datetime.now(UTC) - timedelta(days=2), layer1=_l1())

    # contract v4：granularity/窗口参数退役——传入被忽略（不再 422、不再回显）。
    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend?granularity=week&days_back=7").json()

    assert "granularity" not in body
    assert "days_back" not in body and "weeks_back" not in body and "months_back" not in body
    assert [p["run_id"] for p in body["points"]] == ["run-1"]


async def test_trend_fixed_90d_window_filters_older_rows(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    # 固定近 90 天窗口（滚轮缩小上限）：120 天前的运行出窗，无需任何参数。
    old = datetime.now(UTC) - timedelta(days=120)
    recent = datetime.now(UTC) - timedelta(days=2)
    await _seed_run(kb["id"], "run-old", old, layer1=_l1(recall_at_k=0.7))
    await _seed_run(kb["id"], "run-recent", recent, layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()

    assert [p["run_id"] for p in body["points"]] == ["run-recent"]


async def test_trend_empty_history_reports_has_data_false(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()

    assert body == {
        "points": [],
        "baseline": None,
        "has_data": False,
        "sparks": {
            "faithfulness": [],
            "answer_relevancy": [],
            "context_precision": [],
            "context_recall": [],
            "citation_precision": [],
            "citation_recall": [],
            "seed_hit_rate": [],
            "routing_hit_rate": [],
        },
    }


async def test_trend_sparks_include_runs_outside_points_window(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    old = datetime.now(UTC) - timedelta(days=200)  # 远超固定 90 天窗口
    recent = datetime.now(UTC) - timedelta(days=2)
    await _seed_run(kb["id"], "run-old", old, layer2=_l2(faithfulness=0.60))
    await _seed_run(kb["id"], "run-recent", recent, layer2=_l2(faithfulness=0.90))

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()

    # points 仅含窗口内运行；sparks 取全量近 10 → old + recent 均在（升序）
    assert [p["run_id"] for p in body["points"]] == ["run-recent"]
    assert body["sparks"]["faithfulness"] == [0.60, 0.90]


async def test_trend_unknown_kb_404(service) -> None:
    client = _client(service)

    response = client.get("/api/knowledge-bases/kb-missing/eval-runs/trend")

    assert response.status_code == 404


# ── run detail ───────────────────────────────────────────────────────────


async def test_get_eval_run_returns_full_row_json(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    diff = {
        "recall_at_k_delta": -0.02,
        "regression_detected": True,
        "threshold_percent": 3.0,
        "regressed_categories": ["fact"],
    }
    await _seed_run(
        kb["id"],
        "run-full",
        datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        layer1=_l1(),
        baseline_diff=diff,
        environment="nightly",
        mark_baseline=True,
    )

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/run-full")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == "run-full"
    assert body["kb_id"] == kb["id"]
    assert body["status"] == "completed"
    assert body["environment"] == "nightly"
    assert body["is_baseline"] is True
    assert body["created_at"].startswith("2026-08-20")
    assert body["layer1_metrics"]["summary"]["recall_at_k"] == 0.8
    assert body["layer2_metrics"] == {}
    assert body["baseline_diff"]["regressed_categories"] == ["fact"]


async def test_get_eval_run_cross_kb_access_404(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    other = _create_kb(client, name="另一个库")
    await _seed_run(kb["id"], "run-mine", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    response = client.get(f"/api/knowledge-bases/{other['id']}/eval-runs/run-mine")

    assert response.status_code == 404


async def test_get_eval_run_unknown_run_404(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/run-missing")

    assert response.status_code == 404


async def test_get_eval_run_unknown_kb_404(service) -> None:
    client = _client(service)

    response = client.get("/api/knowledge-bases/kb-missing/eval-runs/run-1")

    assert response.status_code == 404


# ── POST /eval-runs trigger（spec 2026-08-27 §5，wiki 幂等同款）──────────


def _trigger_service(session_factory, tmp_path, trigger) -> KnowledgeService:
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
        eval_trigger_fn=trigger,
    )


async def test_trigger_returns_202_enqueued_and_schedules_once(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    # 空库会被 409 前置守卫拦下（见 test_trigger_empty_bank_maps_to_409_*），
    # enqueued 路径需要至少一题——顺带复用 Task 1 的 CRUD API 播种。
    seeded = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "什么是退休年龄", "category": "fact", "expected_paths": ["vector"]})
    assert seeded.status_code == 201, seeded.text

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs")

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "enqueued"}
    assert trigger.call_count == 1
    assert trigger.call_args[0][0] == kb["id"]


async def test_trigger_in_flight_returns_already_running_without_rescheduling(session_factory, tmp_path) -> None:
    from deerflow.knowledge.eval import ondemand as eval_ondemand

    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    eval_ondemand._IN_FLIGHT[kb["id"]] = 1
    try:
        response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs")

        assert response.status_code == 202
        assert response.json() == {"status": "already_running"}
        assert trigger.call_count == 0
    finally:
        eval_ondemand._IN_FLIGHT.pop(kb["id"], None)


async def test_trigger_empty_bank_maps_to_409_and_never_schedules(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs")

    assert response.status_code == 409, response.text
    assert trigger.call_count == 0


async def test_trigger_unknown_kb_404(session_factory, tmp_path) -> None:
    client = _client(_trigger_service(session_factory, tmp_path, MagicMock()))

    assert client.post("/api/knowledge-bases/kb-missing/eval-runs").status_code == 404


# ── POST /eval-runs 分档与选题（spec 2026-09-01 B 方案 Task 3）─────────


async def test_trigger_default_body_defaults_to_l1(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    seeded = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "什么是退休年龄", "category": "fact", "expected_paths": ["vector"]})
    assert seeded.status_code == 201, seeded.text

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs")

    assert response.status_code == 202, response.text
    assert trigger.call_args.kwargs["layers"] == "l1"
    assert trigger.call_args.kwargs["question_ids"] is None


async def test_trigger_layers_l1_l2_forwards_to_scheduler(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    seeded = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "什么是退休年龄", "category": "fact", "expected_paths": ["vector"]})
    assert seeded.status_code == 201, seeded.text

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs", json={"layers": "l1_l2"})

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "enqueued"}
    assert trigger.call_args.kwargs["layers"] == "l1_l2"


async def test_trigger_invalid_layers_422(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs", json={"layers": "l3"})

    assert response.status_code == 422, response.text
    assert trigger.call_count == 0


async def test_trigger_question_ids_forwarded_to_scheduler(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    kept = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "保留题", "category": "fact", "expected_paths": ["vector"]})
    assert kept.status_code == 201, kept.text
    dropped = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "排除题", "category": "fact", "expected_paths": ["vector"]})
    assert dropped.status_code == 201, dropped.text

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs", json={"question_ids": [kept.json()["id"]]})

    assert response.status_code == 202, response.text
    assert trigger.call_args.kwargs["question_ids"] == [kept.json()["id"]]


async def test_trigger_unknown_question_ids_map_to_409(session_factory, tmp_path) -> None:
    trigger = MagicMock()
    client = _client(_trigger_service(session_factory, tmp_path, trigger))
    kb = _create_kb(client)
    seeded = client.post(f"/api/knowledge-bases/{kb['id']}/eval/questions", json={"query": "什么是退休年龄", "category": "fact", "expected_paths": ["vector"]})
    assert seeded.status_code == 201, seeded.text

    response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs", json={"question_ids": ["no-such-id"]})

    # 过滤后空集 = 空题库语义：确定性 409，不烧注定失败的后台任务。
    assert response.status_code == 409, response.text
    assert trigger.call_count == 0


# ── GET /eval-runs history list（spec 2026-08-27 §6.1）───────────────────


async def test_history_lists_runs_newest_first_with_derived_flags(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    diff = {"recall_at_k_delta": -0.05, "regression_detected": True, "threshold_percent": 3.0, "regressed_categories": ["fact"]}
    await _seed_run(kb["id"], "run-old", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1())
    await _seed_run(
        kb["id"],
        "run-new",
        datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        layer1=_l1(),
        layer2=_l2(),
        baseline_diff=diff,
        langfuse_trace_url="https://langfuse.example/trace/9",
        environment="nightly",
    )

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()

    assert body["in_flight"] is False
    assert body["total"] == 2
    newest, oldest = body["runs"]
    assert newest["run_id"] == "run-new"
    assert oldest["run_id"] == "run-old"
    # has_layer1/has_layer2 由 *_metrics 非空推导；指标本体不下发。
    assert (newest["has_layer1"], newest["has_layer2"]) == (True, True)
    assert (oldest["has_layer1"], oldest["has_layer2"]) == (True, False)
    assert "layer1_metrics" not in newest
    assert newest["status"] == "completed"
    assert newest["environment"] == "nightly"
    assert newest["is_baseline"] is False
    assert newest["regression_detected"] is True
    assert oldest["regression_detected"] is False
    assert newest["langfuse_trace_url"] == "https://langfuse.example/trace/9"
    assert oldest["langfuse_trace_url"] is None


async def test_history_timestamps_carry_utc_offset(service) -> None:
    """SQLite 读回剥 tz：序列化不经 coerce_iso 补偏移的话，前端把 naive ISO
    当本地时间解析（UTC+8 环境历史行与槽相对时间偏 8 小时，用户实测投诉）。"""
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-tz", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()

    assert body["runs"][0]["created_at"].endswith("+00:00")


async def test_history_excludes_ci_by_default_and_opts_back_in(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-local", datetime(2026, 8, 19, 9, 0, tzinfo=UTC), layer1=_l1())
    await _seed_run(kb["id"], "run-ci", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer2=_l2(), environment="ci")

    default_body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()
    assert default_body["total"] == 1
    assert [r["run_id"] for r in default_body["runs"]] == ["run-local"]

    with_ci = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs?include_ci=true").json()
    assert with_ci["total"] == 2
    assert [r["run_id"] for r in with_ci["runs"]] == ["run-ci", "run-local"]


async def test_history_limit_slices_newest_after_filter_and_clamps_upper_bound(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    for day, run_id in ((16, "run-a"), (17, "run-b"), (18, "run-c")):
        await _seed_run(kb["id"], run_id, datetime(2026, 8, day, 9, 0, tzinfo=UTC), layer1=_l1())

    sliced = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs?limit=2").json()
    # 过滤后按新到旧切片，total 反映过滤后全量（不是本页行数）。
    assert [r["run_id"] for r in sliced["runs"]] == ["run-c", "run-b"]
    assert sliced["total"] == 3

    clamped = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs?limit=999")
    assert clamped.status_code == 200
    assert len(clamped.json()["runs"]) == 3
    assert clamped.json()["total"] == 3


async def test_history_rejects_non_positive_or_malformed_limit(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs?limit=abc").status_code == 422
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs?limit=0").status_code == 422


async def test_history_empty_returns_exact_shape(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs")

    assert response.status_code == 200, response.text
    assert response.json() == {"in_flight": False, "progress": None, "runs": [], "total": 0}


async def test_history_reports_in_flight_flag_without_pseudo_rows(service) -> None:
    from deerflow.knowledge.eval import ondemand as eval_ondemand

    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-done", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())
    eval_ondemand._IN_FLIGHT[kb["id"]] = 1
    try:
        body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()
        assert body["in_flight"] is True
        # 运行中状态只由顶层标志表达，不产生伪行。
        assert [r["run_id"] for r in body["runs"]] == ["run-done"]
    finally:
        eval_ondemand._IN_FLIGHT.pop(kb["id"], None)


# ── GET /eval-runs 顶层 progress（spec 2026-09-06 run-progress Task 2）──


async def test_history_exposes_live_progress_from_registry(service) -> None:
    from deerflow.knowledge.eval import ondemand as eval_ondemand

    client = _client(service)
    kb = _create_kb(client)
    progress = {
        "run_id": "run-live",
        "phase": "questions",
        "done": 3,
        "total": 10,
        "failed": 1,
        "started_at": "2026-09-06T10:00:00+00:00",
        "updated_at": "2026-09-06T10:05:00+00:00",
        "phase_started_at": "2026-09-06T10:04:30.000+00:00",
        "phase_durations": {"layer1": 30.5},
        "tail": {"kind": "item", "phase": "questions", "done": 3, "total": 10, "failed": 1},
    }
    eval_ondemand._IN_FLIGHT[kb["id"]] = 1
    eval_ondemand._PROGRESS[kb["id"]] = dict(progress)
    try:
        body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()

        assert body["in_flight"] is True
        # 契约十键原样透出（spec §3 + §9；复用 3s 轮询，不另开端点）。
        assert body["progress"] == progress
    finally:
        eval_ondemand._IN_FLIGHT.pop(kb["id"], None)
        eval_ondemand._PROGRESS.pop(kb["id"], None)


async def test_history_progress_backfills_section9_keys(service) -> None:
    """旧形状条目也恒透出十键（§9 三键补默认值）——前端不必做存在性分支。"""

    from deerflow.knowledge.eval import ondemand as eval_ondemand

    client = _client(service)
    kb = _create_kb(client)
    eval_ondemand._IN_FLIGHT[kb["id"]] = 1
    eval_ondemand._PROGRESS[kb["id"]] = {"run_id": "run-legacy", "phase": "layer1", "done": 0, "total": 1, "failed": 0, "started_at": "2026-09-06T10:00:00+00:00", "updated_at": "2026-09-06T10:00:00+00:00"}
    try:
        body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()

        assert body["progress"]["phase_durations"] == {}
        assert body["progress"]["tail"] == {}
        assert body["progress"]["run_id"] == "run-legacy"
        # phase_started_at 回退到 started_at；总键数恒为十。
        assert body["progress"]["phase_started_at"] == "2026-09-06T10:00:00+00:00"
        assert len(body["progress"]) == 10
    finally:
        eval_ondemand._IN_FLIGHT.pop(kb["id"], None)
        eval_ondemand._PROGRESS.pop(kb["id"], None)


async def test_history_progress_is_null_when_idle(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-done", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1())

    body = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()

    assert body["in_flight"] is False
    assert body["progress"] is None


async def test_history_unknown_kb_404(service) -> None:
    client = _client(service)

    assert client.get("/api/knowledge-bases/kb-missing/eval-runs").status_code == 404


# ── POST /eval-runs/cancel（spec 2026-09-06 §11 Task 19）───────────


class _FakeTask:
    """duck-type asyncio.Task：端点测试避跨事件环取消真任务（portal 环 ≠ 测试环）。"""

    def __init__(self) -> None:
        self.cancel_called = False

    def done(self) -> bool:
        return False

    def cancel(self, msg: object = None) -> bool:
        self.cancel_called = True
        return True


async def test_cancel_endpoint_409_when_idle(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    assert client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs/cancel").status_code == 409


async def test_cancel_endpoint_cancels_registered_task(service) -> None:
    from deerflow.knowledge.eval import ondemand as eval_ondemand

    client = _client(service)
    kb = _create_kb(client)
    fake = _FakeTask()
    eval_ondemand._TASKS[kb["id"]] = fake  # type: ignore[assignment]
    try:
        response = client.post(f"/api/knowledge-bases/{kb['id']}/eval-runs/cancel")

        assert response.status_code == 202
        assert response.json() == {"status": "cancelled"}
        assert fake.cancel_called is True
    finally:
        eval_ondemand._TASKS.pop(kb["id"], None)


# ── DELETE /eval-runs（2026-09-08 历史删除）─────────────────────


async def test_delete_eval_runs_removes_rows_and_converges_read_surfaces(service) -> None:
    """删除后历史列表/ latest / trend 同源收敛于剩余行（三面实时聚合，无伴随写）。"""
    client = _client(service)
    kb = _create_kb(client)
    await _seed_run(kb["id"], "run-a", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.7))
    await _seed_run(kb["id"], "run-b", datetime(2026, 8, 20, 9, 0, tzinfo=UTC), layer1=_l1(recall_at_k=0.85))
    await _seed_run(kb["id"], "run-c", datetime(2026, 8, 21, 9, 0, tzinfo=UTC), layer2=_l2())

    response = client.request(
        "DELETE",
        f"/api/knowledge-bases/{kb['id']}/eval-runs",
        json={"run_ids": ["run-a", "run-c"]},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 2}

    listed = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs").json()
    assert [run["run_id"] for run in listed["runs"]] == ["run-b"]
    # latest 收敛到剩余行（run-a 删除前是 layer1 latest 候选之一）
    latest = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/latest").json()
    assert latest["layer1"]["run_id"] == "run-b"
    assert latest["layer2"] is None
    # trend 点同步减少
    trend = client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/trend").json()
    assert [point["run_id"] for point in trend["points"]] == ["run-b"]
    # 单 run 详情 404
    assert client.get(f"/api/knowledge-bases/{kb['id']}/eval-runs/run-a").status_code == 404


async def test_delete_eval_runs_cross_kb_ids_ignored(service) -> None:
    """kb_id 条件是跨库删除的硬隔离线：他库 id 不计入 deleted 且行存活。"""
    client = _client(service)
    kb = _create_kb(client)
    other = _create_kb(client, name="其他库")
    await _seed_run(kb["id"], "run-mine", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1())
    await _seed_run(other["id"], "run-theirs", datetime(2026, 8, 18, 9, 0, tzinfo=UTC), layer1=_l1())

    response = client.request(
        "DELETE",
        f"/api/knowledge-bases/{kb['id']}/eval-runs",
        json={"run_ids": ["run-theirs", "run-ghost"]},
    )
    assert response.status_code == 200
    assert response.json() == {"deleted": 0}

    other_listed = client.get(f"/api/knowledge-bases/{other['id']}/eval-runs").json()
    assert [run["run_id"] for run in other_listed["runs"]] == ["run-theirs"]


async def test_delete_eval_runs_empty_list_rejected(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    response = client.request("DELETE", f"/api/knowledge-bases/{kb['id']}/eval-runs", json={"run_ids": []})
    assert response.status_code == 422
