"""Orchestration tests for the on-demand Layer 1 eval runner (spec 2026-08-27 §5).

``run_layer1_for_kb`` 复刻 CLI ``run_rag_eval.py`` 的编排链（load golden →
searchers → run_evaluation → 报告映射 → save_eval_run），但复用调用进程已
初始化的引擎与 store：测试直接注入 stub searchers，不经任何真实检索 impl，
也不触发默认 searcher 构建（那需要真实 KB 行与向量库）。

契约：
- completed 落一行 ``environment="local"``、layer2 为 ``{}``、created_at =
  显式传入的 generated_at（单一时钟）；
- 自动 diff 标记 baseline（无标记行则 baseline_diff 为 null）；
- 运行期异常兜底落 error 行且不上抛（fire-and-forget 安全，复刻 CLI
  best-effort 持久化语义）；空题库是「不该开始」而非「运行失败」——直接
  抛 ``EvalQuestionBankEmpty``、不落行；
- in-flight 注册表复刻 wiki ``_IN_FLIGHT``：运行中可观测、finally 必减。
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import pytest

from deerflow.knowledge.eval import ondemand
from deerflow.knowledge.eval.persistence import generate_run_id, save_eval_run
from deerflow.knowledge.eval.question_bank import add_question
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

KB = "kb-under-test"
CHUNK_A = "a" * 32 + "#0001"
GENERATED_AT = "2026-08-27T10:00:00+00:00"


@pytest.fixture
def store(session_factory):
    return KnowledgeStore(session_factory)


@pytest.fixture(autouse=True)
def _clean_in_flight():
    yield
    ondemand._IN_FLIGHT.pop(KB, None)
    ondemand._PROGRESS.pop(KB, None)


def _stub_searchers(hit_chunk: str | None = CHUNK_A) -> dict:
    from deerflow.knowledge.eval.runner import ScoredHit

    async def vector_fn(query: str, top_k: int):
        return () if hit_chunk is None else (ScoredHit(chunk_id=hit_chunk, score=0.93),)

    async def empty_fn(query: str, top_k: int):
        return ()

    return {"vector": vector_fn, "graph": empty_fn, "wiki": empty_fn}


async def _seed_question(path, query: str = "什么是退休年龄") -> None:
    await add_question(path, query=query, category="fact", expected_paths=["vector"], relevant_chunk_ids=[CHUNK_A])


async def _seed_question_returning(path, query: str = "什么是退休年龄"):
    return await add_question(path, query=query, category="fact", expected_paths=["vector"], relevant_chunk_ids=[CHUNK_A])


def _stub_agent_runner(captured: list[str] | None = None):
    """假 agent_runner：返回一次带检索工具序列的 TraceOutcome（hybrid_search → vector 命中）。"""
    from deerflow.knowledge.eval.ragas_eval import TraceOutcome

    async def runner(question):
        if captured is not None:
            captured.append(question.id)
        return TraceOutcome(
            question_id=question.id,
            answer="答案[1]。",
            retrieval_tools=("hybrid_search",),
            citation_map={1: "证据一"},
            seed_entities=(),
        )

    return runner


def test_generate_run_id_format_matches_cli_contract() -> None:
    # rag-<UTC 秒>-<hex8>，提升到 eval 包后 CLI 与按需运行共用。
    assert re.fullmatch(r"rag-\d{8}T\d{6}Z-[0-9a-f]{8}", generate_run_id())


async def test_layer2_deps_judges_with_the_configured_judge_model(monkeypatch) -> None:
    """按需评测的 judge 读 ``rag.judge_model``（与 CLI ``--judge-model`` 同源），未配置为 None → RAG 默认 → 首项。"""
    from types import SimpleNamespace

    from deerflow.config import app_config as app_config_module
    from deerflow.knowledge import store as store_module
    from deerflow.knowledge.eval import factory as factory_module
    from deerflow.knowledge.eval import ragas_eval as ragas_eval_module

    seen: list[str | None] = []

    def fake_build_judge_llm(judge_model, *, config):
        seen.append(judge_model)
        return object()

    async def fake_get_kb(kb_id):
        return {"owner_id": "user-1"}

    monkeypatch.setattr(factory_module, "build_judge_llm", fake_build_judge_llm)
    monkeypatch.setattr(factory_module, "build_ragas_evaluator", lambda judge: None)
    monkeypatch.setattr(ragas_eval_module, "build_lead_agent_runner", lambda **kwargs: object())
    monkeypatch.setattr(store_module, "get_knowledge_store", lambda: SimpleNamespace(get_kb=fake_get_kb))

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: SimpleNamespace(rag=SimpleNamespace(judge_model="judge-entry")))
    await ondemand._build_layer2_deps(KB, "rag-run")

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: SimpleNamespace(rag=SimpleNamespace(judge_model=None)))
    await ondemand._build_layer2_deps(KB, "rag-run")

    # An empty string from a hand-written file is "not configured", not a model named "".
    monkeypatch.setattr(app_config_module, "get_app_config", lambda: SimpleNamespace(rag=SimpleNamespace(judge_model="")))
    await ondemand._build_layer2_deps(KB, "rag-run")

    assert seen == ["judge-entry", None, None]


async def test_completed_run_persists_local_layer1_row(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    run_id = await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    assert run_id.startswith("rag-")
    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == run_id
    assert row.status == "completed"
    assert row.layer2_metrics == {}
    assert row.layer1_metrics["summary"]["question_count"] == 1
    assert row.layer1_metrics["summary"]["recall_at_k"] == 1.0  # 锚定 chunk 命中
    assert row.environment == "local"
    # SQLite 往返返回 naive datetime（本项目 eval_runs 既定口径），按壁钟对齐。
    assert row.created_at == datetime.fromisoformat(GENERATED_AT).replace(tzinfo=None)
    assert row.completed_at >= row.created_at
    assert row.baseline_diff is None
    # drain 后注册表必须归零（finally 保证）。
    assert not ondemand.eval_run_in_progress(KB)


async def test_auto_diff_against_marked_baseline(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    baseline_metrics = {
        "summary": {"recall_at_k": 1.0, "hit_rate": None, "mrr": None, "path_accuracy": None, "question_count": 1},
    }
    await save_eval_run(
        run_id="run-base",
        kb_id=KB,
        status="completed",
        created_at=datetime.now(UTC),
        layer1_metrics=baseline_metrics,
        mark_baseline=True,
    )

    await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    rows = [row for row in await store.list_eval_runs(KB) if row.id != "run-base"]
    assert len(rows) == 1
    diff = rows[0].baseline_diff
    assert diff is not None
    assert diff["regression_detected"] is False


async def test_no_baseline_means_null_diff(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    rows = await store.list_eval_runs(KB)
    assert rows[0].baseline_diff is None


async def test_runtime_exception_falls_back_to_error_row_without_raising(tmp_path, store, monkeypatch) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    def _boom(report):
        raise RuntimeError("mapping blew up")

    # 打在本模块的绑定上：编排期映射崩溃属于「运行期异常」，须兜底为 error 行。
    monkeypatch.setattr(ondemand, "layer1_metrics_from_report", _boom)

    run_id = await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == run_id
    assert row.status == "error"
    assert row.layer1_metrics == {}


async def test_a_judge_target_that_cannot_be_built_records_an_error_row_with_layer1(tmp_path, store, monkeypatch) -> None:
    """spec 2026-09-23 D10.5: the judge's *configuration* error is not the optional layer's
    quality problem.

    Layer 1 finished, so its metrics and the baseline diff are kept; the second layer never
    ran (empty), the row is ``error`` rather than a ``completed`` run with a hollow layer 2,
    and the ``finally`` still releases the in-flight registration.
    """
    from deerflow.knowledge.embedder import RagConfigurationError

    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    async def _refuse(kb_id, run_id):
        raise RagConfigurationError("RAG 目标「judge-entry」不可用：条目缺少非空 api_key。")

    monkeypatch.setattr(ondemand, "_build_layer2_deps", _refuse)

    run_id = await ondemand.run_full_eval_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == run_id
    assert row.status == "error"  # not "completed"
    assert row.layer2_metrics == {}
    assert row.layer1_metrics["summary"]["question_count"] == 1  # layer 1 kept
    assert not ondemand.eval_run_in_progress(KB)  # the finally released it


async def test_missing_bank_raises_and_persists_nothing(tmp_path, store) -> None:
    with pytest.raises(ondemand.EvalQuestionBankEmpty):
        await ondemand.run_layer1_for_kb(KB, golden_path=tmp_path / "absent.jsonl", searchers=_stub_searchers(), generated_at=GENERATED_AT)

    assert await store.list_eval_runs(KB) == []


async def test_blank_line_only_bank_counts_as_empty(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text("\n\n", encoding="utf-8")

    with pytest.raises(ondemand.EvalQuestionBankEmpty):
        await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), generated_at=GENERATED_AT)

    assert await store.list_eval_runs(KB) == []


# ── 选题过滤（spec 2026-09-01 B 方案 Task 2）───────────────────────


async def test_question_ids_filters_layer1_run(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    kept = await _seed_question_returning(golden, query="保留题")
    await _seed_question_returning(golden, query="排除题")

    await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), question_ids=[kept.id], generated_at=GENERATED_AT)

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].layer1_metrics["summary"]["question_count"] == 1


async def test_question_ids_all_unknown_raises_and_persists_nothing(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    with pytest.raises(ondemand.EvalQuestionBankEmpty):
        await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=_stub_searchers(), question_ids=["no-such-id"], generated_at=GENERATED_AT)

    assert await store.list_eval_runs(KB) == []


# ── 完整运行（L1+L2 单行，spec 2026-09-01 B 方案 Task 2）──────────────


async def test_full_run_persists_single_row_with_both_layers(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    run_id = await ondemand.run_full_eval_for_kb(
        KB,
        golden_path=golden,
        searchers=_stub_searchers(),
        agent_runner=_stub_agent_runner(),
        generated_at=GENERATED_AT,
    )

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == run_id
    assert run_id.startswith("rag-")
    assert row.status == "completed"
    assert row.environment == "local"
    # 双层指标同行：L1 静态 + L2 架构专属（judge/ragas 未注入 → ragas 显式跳过）。
    assert row.layer1_metrics["summary"]["question_count"] == 1
    assert row.layer2_metrics["path_accuracy"] == 1.0  # hybrid_search ∈ 期望 {vector}
    assert row.layer2_metrics["ragas_available"] is False
    assert row.layer2_metrics["ragas_skip_reason"]
    assert not ondemand.eval_run_in_progress(KB)


async def test_full_run_question_ids_filters_both_layers(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    kept = await _seed_question_returning(golden, query="保留题")
    await _seed_question_returning(golden, query="排除题")
    called: list[str] = []

    await ondemand.run_full_eval_for_kb(
        KB,
        golden_path=golden,
        searchers=_stub_searchers(),
        agent_runner=_stub_agent_runner(called),
        question_ids=[kept.id],
        generated_at=GENERATED_AT,
    )

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].layer1_metrics["summary"]["question_count"] == 1
    assert called == [kept.id]


async def test_in_flight_incremented_before_load_questions(tmp_path, store, monkeypatch) -> None:
    """竞态修复(2026-09-06)：_IN_FLIGHT 自增前移到 runner 第一行(任何 await 之前)。

    旧实现把自增放在 ``await load_questions`` 之后，create_task 调度到 load 完成
    之间存在窗口：触发后早期 poll 读到 in_flight=false → 覆盖前端乐观值、杀死
    轮询（按钮不亮/不推进）。本例在 load_questions 内部断言在途计数已为真。
    """
    question = await _seed_question_returning(tmp_path / "golden.jsonl", query="在途题")
    seen: dict[str, bool] = {}

    async def slow_load(_path, *_args, **_kwargs):
        seen["during_load"] = ondemand.eval_run_in_progress(KB)
        return [question]

    monkeypatch.setattr(ondemand, "load_questions", slow_load)
    await ondemand.run_layer1_for_kb(
        KB,
        golden_path=tmp_path / "golden.jsonl",
        searchers=_stub_searchers(),
        generated_at=GENERATED_AT,
    )

    assert seen["during_load"] is True
    assert not ondemand.eval_run_in_progress(KB)


async def test_full_run_layer2_exception_degrades_to_layer1_only_row(tmp_path, store, monkeypatch) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    def _boom(*args, **kwargs):
        raise RuntimeError("layer2 stage blew up")

    monkeypatch.setattr(ondemand, "run_layer2_evaluation", _boom)

    run_id = await ondemand.run_full_eval_for_kb(
        KB,
        golden_path=golden,
        searchers=_stub_searchers(),
        agent_runner=_stub_agent_runner(),
        generated_at=GENERATED_AT,
    )

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == run_id
    # L2 阶段崩溃不丢 L1 成果：completed + 仅 L1 指标（layer2 回落空）。
    assert row.status == "completed"
    assert row.layer1_metrics["summary"]["question_count"] == 1
    assert row.layer2_metrics == {}


async def test_full_run_missing_bank_raises_and_persists_nothing(tmp_path, store) -> None:
    with pytest.raises(ondemand.EvalQuestionBankEmpty):
        await ondemand.run_full_eval_for_kb(
            KB,
            golden_path=tmp_path / "absent.jsonl",
            searchers=_stub_searchers(),
            agent_runner=_stub_agent_runner(),
            generated_at=GENERATED_AT,
        )

    assert await store.list_eval_runs(KB) == []


# ── 运行进度注册表（spec 2026-09-06 run-progress Task 1）──────────────


async def test_full_run_progress_observable_then_cleared(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    snapshots: list[dict | None] = []

    async def runner(question):
        # 运行中可观测：契约十键（spec 2026-09-06 §9 扩 phase_started_at/phase_durations/tail）+ run_id 非空。
        snapshot = ondemand.get_eval_progress(KB)
        snapshots.append(snapshot)
        return await _stub_agent_runner()(question)

    run_id = await ondemand.run_full_eval_for_kb(
        KB,
        golden_path=golden,
        searchers=_stub_searchers(),
        agent_runner=runner,
        generated_at=GENERATED_AT,
    )

    assert snapshots and all(s is not None for s in snapshots)
    assert set(snapshots[0]) == {"run_id", "phase", "done", "total", "failed", "started_at", "updated_at", "phase_started_at", "phase_durations", "tail"}
    assert snapshots[0]["run_id"] == run_id
    # finally 必清：落库后注册表归零。
    assert ondemand.get_eval_progress(KB) is None


async def test_layer1_run_progress_observable_then_cleared(tmp_path, store) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    observed: list[dict | None] = []

    searchers = _stub_searchers()
    original_vector = searchers["vector"]

    async def observing_vector(query: str, top_k: int):
        observed.append(ondemand.get_eval_progress(KB))
        return await original_vector(query, top_k)

    searchers["vector"] = observing_vector

    await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=searchers, generated_at=GENERATED_AT)

    assert observed and observed[0] is not None
    assert observed[0]["phase"] == "layer1"
    assert ondemand.get_eval_progress(KB) is None


async def test_full_run_error_path_clears_progress(tmp_path, store, monkeypatch) -> None:
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)

    def _boom(report):
        raise RuntimeError("mapping blew up")

    monkeypatch.setattr(ondemand, "layer1_metrics_from_report", _boom)

    await ondemand.run_full_eval_for_kb(
        KB,
        golden_path=golden,
        searchers=_stub_searchers(),
        agent_runner=_stub_agent_runner(),
        generated_at=GENERATED_AT,
    )

    # error 行兜底路径同样走 finally：进度不得残留。
    assert ondemand.get_eval_progress(KB) is None


async def test_layer1_progress_advances_per_question(tmp_path, store) -> None:
    """spec 2026-09-06 §9 补：layer1 段逐题上报——快速档的条不再是全程空条。"""
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    await _seed_question(golden, query="第二题")
    snapshots: list[dict] = []

    searchers = _stub_searchers()
    original_vector = searchers["vector"]

    async def observing_vector(query: str, top_k: int):
        snapshot = ondemand.get_eval_progress(KB)
        if snapshot is not None:
            snapshots.append(snapshot)
        return await original_vector(query, top_k)

    searchers["vector"] = observing_vector

    await ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=searchers, generated_at=GENERATED_AT)

    # 第二题开跑时第一题已结算：done=1/total=2（旧实现 layer1 恒 0/1，条全程空）。
    assert any(s["phase"] == "layer1" and s["done"] == 1 and s["total"] == 2 for s in snapshots)
    assert ondemand.get_eval_progress(KB) is None


async def test_progress_tail_and_phase_durations() -> None:
    """spec 2026-09-06 §9：进度条目新增 phase_started_at / phase_durations / tail（结构化事件）。"""
    ondemand._progress_start(KB, "run-tail", phase="layer1", total=1)

    started = ondemand.get_eval_progress(KB)
    assert started["phase_started_at"]
    assert started["phase_durations"] == {}
    assert started["tail"] == {"kind": "phase", "phase": "layer1", "done": 0, "total": 1, "failed": 0}

    ondemand._progress_update(KB, phase="layer1", done=1, failed=0, total=1)
    assert ondemand.get_eval_progress(KB)["tail"]["kind"] == "item"

    ondemand._progress_update(KB, phase="questions", done=0, failed=0, total=2)
    switched = ondemand.get_eval_progress(KB)
    assert switched["tail"] == {"kind": "phase", "phase": "questions", "done": 0, "total": 2, "failed": 0}
    # 阶段切换时结算上一段实测耗时（前端加权自适应的数据源）。
    assert list(switched["phase_durations"]) == ["layer1"]
    assert switched["phase_durations"]["layer1"] >= 0.0

    ondemand._progress_update(KB, phase="questions", done=1, failed=1, total=2)
    failed_tail = ondemand.get_eval_progress(KB)
    assert failed_tail["tail"]["kind"] == "fail"
    assert failed_tail["tail"]["failed"] == 1


# ── 运行终止（spec 2026-09-06 §11 Task 19）──────────────────


async def test_cancel_in_flight_layer1_run_writes_cancelled_row_and_releases_lock(tmp_path, store) -> None:
    """cancel 注入 CancelledError → cancelled 行 + 锁/注册表清理 → 可立即再触发。"""
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    parked = asyncio.Event()

    searchers = _stub_searchers()

    async def parking_vector(query: str, top_k: int):
        await parked.wait()  # 永停，等 cancel 把 CancelledError 注进来

    searchers["vector"] = parking_vector

    task = asyncio.create_task(ondemand.run_layer1_for_kb(KB, golden_path=golden, searchers=searchers, generated_at=GENERATED_AT))
    await asyncio.sleep(0.05)  # 让 runner 停进 searcher
    assert ondemand.eval_run_in_progress(KB)
    assert KB in ondemand._TASKS

    assert ondemand.cancel_eval_run(KB) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].status == "cancelled"
    assert rows[0].layer1_metrics == {}
    # 锁与注册表一并清理：cancel 再调 no-op，进度条目已弹。
    assert not ondemand.eval_run_in_progress(KB)
    assert ondemand.get_eval_progress(KB) is None
    assert ondemand.cancel_eval_run(KB) is False


async def test_cancel_during_layer2_keeps_layer1_metrics(tmp_path, store) -> None:
    """layer2 段 cancel：廉价层成果不丢——cancelled 行带 layer1 指标。"""
    golden = tmp_path / "golden.jsonl"
    await _seed_question(golden)
    parked = asyncio.Event()

    async def parking_runner(*_args, **_kwargs):
        await parked.wait()

    task = asyncio.create_task(
        ondemand.run_full_eval_for_kb(
            KB,
            golden_path=golden,
            searchers=_stub_searchers(),
            agent_runner=parking_runner,
            judge_llm=None,
            ragas_evaluator=None,
            generated_at=GENERATED_AT,
        )
    )
    await asyncio.sleep(0.05)
    # layer1 已跑完、停在答题段（轮询等 phase 切换，不用固定 sleep 赌调度）。
    for _ in range(100):
        if (ondemand.get_eval_progress(KB) or {}).get("phase") == "questions":
            break
        await asyncio.sleep(0.01)
    assert ondemand.get_eval_progress(KB)["phase"] == "questions"

    assert ondemand.cancel_eval_run(KB) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].status == "cancelled"
    assert rows[0].layer1_metrics["summary"]["question_count"] == 1


async def test_cancel_without_in_flight_run_is_noop() -> None:
    assert ondemand.cancel_eval_run(KB) is False
