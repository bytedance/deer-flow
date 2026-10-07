"""Tests for eval_runs persistence from the eval CLI (spec 2026-08-24 §3.1, plan Task 0b).

Covers the §3.1.2 report→JSON field mappings (pure functions), the
status/environment resolution rules, ``save_eval_run`` round-trips against a
real (throwaway) SQLite database, and the CLI wiring: every CLI run —
completed, regression-red (exit 1), error (exit 2) or skipped (exit 3) —
persists exactly one eval_runs row with the correct layer split.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from deerflow.knowledge.eval import persistence
from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.models import EvalRunRow

REPO_BACKEND = Path(__file__).resolve().parents[3]
LAYER1_CLI_PATH = REPO_BACKEND / "scripts" / "run_rag_eval.py"

KEYS = {"DASHSCOPE_EMBEDDING_API_KEY": "k1", "DASHSCOPE_RERANK_API_KEY": "k2"}
CHUNK = "a" * 32 + "#0001"


def _load_cli(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layer1_cli = _load_cli(LAYER1_CLI_PATH, "run_rag_eval_persist")


# ── report payloads (mirror runner.report_to_dict / the Layer-2 report shape) ──


def _layer1_report_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "meta": {"top_k": 5, "question_count": 2, "generated_at": "2026-08-24T10:00:00+00:00"},
        "overall": {"count": 2, "hit_rate": 0.9, "recall": 0.8, "mrr": 0.7, "path_accuracy": 0.95},
        "by_category": {
            "fact": {"count": 1, "hit_rate": 1.0, "recall": 1.0, "mrr": 1.0, "path_accuracy": 1.0},
            "relation": {"count": 1, "hit_rate": 0.8, "recall": 0.6, "mrr": 0.4, "path_accuracy": 0.9},
        },
        "questions": [],
        "diff": None,
    }


def _layer2_report_payload() -> dict[str, Any]:
    return {
        "run_id": "ragas-20260824T100000Z-deadbeef",
        "kb_id": "kb-1",
        "generated_at": "2026-08-24T10:00:00+00:00",
        "ragas_available": True,
        "ragas_skip_reason": None,
        "langfuse": {"pushed": False},
        "aggregate": {
            "questions": 2,
            "failures": 0,
            "path_accuracy": 0.5,
            "citation_precision": 0.9,
            "citation_recall": 0.7,
            "graph_entity_hit_rate": 0.6,
            "ragas": {"faithfulness": 0.93, "answer_relevancy": None, "context_precision": 0.8, "context_recall": None},
            "by_category": {},
        },
        "results": [],
    }


def _question(qid: str, category: str = "fact", *, entities: tuple[str, ...] = ()) -> GoldenQuestion:
    return GoldenQuestion(
        id=qid,
        query=f"query-{qid}",
        expected_paths=("vector",),
        relevant_chunk_ids=(CHUNK,),
        relevant_entities=entities,
        category=category,
    )


# ── §3.1.2 field mappings (pure) ──────────────────────────────────────────


class TestLayer1MetricsMapping:
    def test_summary_renamed_keys(self):
        metrics = persistence.layer1_metrics_from_report(_layer1_report_payload())

        summary = metrics["summary"]
        assert summary == {
            "hit_rate": pytest.approx(0.9),
            "recall_at_k": pytest.approx(0.8),  # recall → recall_at_k
            "mrr": pytest.approx(0.7),
            "path_accuracy": pytest.approx(0.95),
            "question_count": 2,  # count → question_count
        }

    def test_by_category_dynamic_keys_passthrough(self):
        metrics = persistence.layer1_metrics_from_report(_layer1_report_payload())

        # Only the batch's categories appear — never a fixed four-key template.
        # ``questions`` is the per-question slim array (bank triage column);
        # ``top_k`` is the scalar retrieval depth for @k column headers.
        assert set(metrics) == {"summary", "fact", "relation", "questions", "top_k"}
        assert metrics["questions"] == []
        assert metrics["top_k"] == 5
        assert metrics["fact"] == {
            "hit_rate": pytest.approx(1.0),
            "recall_at_k": pytest.approx(1.0),
            "mrr": pytest.approx(1.0),
            "path_accuracy": pytest.approx(1.0),
            "question_count": 1,
        }
        assert metrics["relation"]["recall_at_k"] == pytest.approx(0.6)
        assert metrics["relation"]["question_count"] == 1

    def test_empty_categories_yield_summary_only(self):
        payload = _layer1_report_payload()
        payload["by_category"] = {}

        assert set(persistence.layer1_metrics_from_report(payload)) == {"summary", "questions", "top_k"}

    def test_questions_slim_projection_for_bank_triage(self):
        payload = _layer1_report_payload()
        payload["questions"] = [
            {
                "id": "q1",
                "category": "fact",
                "expected_paths": ["vector"],
                "actual_path": "vector",
                "path_correct": True,
                "hit": 1.0,
                "recall": 1.0,
                "mrr": 1.0,
                "paths": {"vector": {"hits": [{"chunk_id": CHUNK, "score": 0.9}], "failure": None}},
            },
            {
                "id": "q2",
                "category": "relation",
                "expected_paths": ["graph"],
                "actual_path": None,
                "path_correct": False,
                "hit": 0.0,
                "recall": 0.0,
                "mrr": None,
                "paths": {},
            },
        ]

        metrics = persistence.layer1_metrics_from_report(payload)

        # Slim five keys only — per-path hit detail never reaches eval_runs.
        assert metrics["questions"] == [
            {"id": "q1", "recall": 1.0, "hit": 1.0, "path_correct": True, "actual_path": "vector"},
            {"id": "q2", "recall": 0.0, "hit": 0.0, "path_correct": False, "actual_path": None},
        ]


class TestLayer2MetricsMapping:
    def test_ragas_and_arch_specific_mapping(self):
        questions = [_question("q1", entities=("实体X",)), _question("q2", category="relation")]
        metrics = persistence.layer2_metrics_from_report(_layer2_report_payload(), questions=questions)

        assert metrics["ragas"] == {"faithfulness": pytest.approx(0.93), "answer_relevancy": None, "context_precision": pytest.approx(0.8), "context_recall": None}
        # graph_entity_hit_rate → arch_specific.seed_hit_rate
        assert metrics["arch_specific"] == {
            "citation_precision": pytest.approx(0.9),
            "citation_recall": pytest.approx(0.7),
            "seed_hit_rate": pytest.approx(0.6),
        }
        assert metrics["ragas_available"] is True
        assert metrics["ragas_skip_reason"] is None
        assert metrics["has_graph_questions"] is True

    def test_has_graph_questions_false_when_no_entities(self):
        questions = [_question("q1"), _question("q2", category="relation")]
        metrics = persistence.layer2_metrics_from_report(_layer2_report_payload(), questions=questions)

        assert metrics["has_graph_questions"] is False

    def test_ragas_unavailable_passthrough(self):
        payload = _layer2_report_payload()
        payload["ragas_available"] = False
        payload["ragas_skip_reason"] = "ragas 未安装"
        metrics = persistence.layer2_metrics_from_report(payload, questions=[_question("q1")])

        assert metrics["ragas_available"] is False
        assert metrics["ragas_skip_reason"] == "ragas 未安装"


class TestBaselineDiffMapping:
    def _diff(self, *, failed: bool) -> dict[str, Any]:
        return {
            "deltas": [
                {"scope": "overall", "metric": "recall", "before": 0.9, "after": 0.88, "delta": -0.02},
                {"scope": "fact", "metric": "recall", "before": 0.9, "after": 0.8, "delta": -0.1},
                {"scope": "relation", "metric": "recall", "before": 0.9, "after": 0.88, "delta": -0.02},
                {"scope": "fact", "metric": "mrr", "before": 0.9, "after": 0.1, "delta": -0.8},
            ],
            "regressed_questions": ["q1"],
            "failed": failed,
            "failures": ["category 'fact' recall dropped 10.0% (> 3.0%)"] if failed else [],
        }

    def test_no_diff_returns_none(self):
        assert persistence.baseline_diff_from_report(_layer1_report_payload()) is None

    def test_diff_mapping_with_regressed_categories(self):
        payload = _layer1_report_payload()
        payload["diff"] = self._diff(failed=True)

        diff = persistence.baseline_diff_from_report(payload)

        assert diff is not None
        # overall recall delta surfaces as recall_at_k_delta
        assert diff["recall_at_k_delta"] == pytest.approx(-0.02)
        assert diff["regression_detected"] is True
        assert diff["threshold_percent"] == pytest.approx(3.0)  # DEFAULT_FAIL_THRESHOLD * 100
        # Only per-category recall drops beyond the threshold are listed —
        # overall never gates, non-recall metrics never gate, sub-threshold drops don't.
        assert diff["regressed_categories"] == ["fact"]

    def test_threshold_percent_follows_fail_threshold(self):
        payload = _layer1_report_payload()
        payload["diff"] = self._diff(failed=False)

        diff = persistence.baseline_diff_from_report(payload, fail_threshold=0.05)

        assert diff is not None
        assert diff["threshold_percent"] == pytest.approx(5.0)
        # 10% category drop still exceeds the custom 5% threshold.
        assert diff["regressed_categories"] == ["fact"]


class TestStatusMapping:
    def test_exit_code_mapping(self):
        # Layer 1 regression red (exit 1) is still a completed run — the gate
        # signal lives in baseline_diff, the trend needs the data point.
        assert persistence.status_from_exit_code(0) == "completed"
        assert persistence.status_from_exit_code(1) == "completed"
        assert persistence.status_from_exit_code(2) == "error"
        assert persistence.status_from_exit_code(3) == "skipped"


class TestResolveEnvironment:
    def test_explicit_flag_wins(self):
        assert persistence.resolve_environment("nightly", {"CI": "true"}) == "nightly"
        assert persistence.resolve_environment("local", {"CI": "true"}) == "local"

    def test_ci_inferred_from_environment(self):
        assert persistence.resolve_environment(None, {"CI": "true"}) == "ci"

    def test_default_is_local(self):
        assert persistence.resolve_environment(None, {}) == "local"
        assert persistence.resolve_environment(None, {"CI": "1"}) == "local"


# ── save_eval_run round-trip (real SQLite via the shared fixture) ─────────


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@pytest.mark.asyncio
class TestSaveEvalRun:
    async def test_round_trip(self, session_factory):
        created = datetime(2026, 8, 24, 10, 0, 0, tzinfo=UTC)
        layer1 = {"summary": {"hit_rate": 0.9, "recall_at_k": 0.8, "mrr": 0.7, "path_accuracy": 0.95, "question_count": 2}}
        diff = {"recall_at_k_delta": -0.02, "regression_detected": False, "threshold_percent": 3.0, "regressed_categories": []}

        run_id = await persistence.save_eval_run(
            run_id="run-1",
            kb_id="kb-1",
            status="completed",
            created_at=created,
            layer1_metrics=layer1,
            baseline_diff=diff,
            completed_at=datetime(2026, 8, 24, 10, 5, 0, tzinfo=UTC),
        )

        assert run_id == "run-1"
        async with session_factory() as session:
            row = (await session.execute(select(EvalRunRow))).scalar_one()
        assert row.id == "run-1"
        assert row.kb_id == "kb-1"
        assert row.status == "completed"
        assert row.layer1_metrics["summary"]["recall_at_k"] == pytest.approx(0.8)
        assert row.layer2_metrics == {}  # 未执行的层存 {}
        assert row.baseline_diff["regressed_categories"] == []
        # created_at comes from the report's generated_at, not the DB default.
        assert _as_utc(row.created_at) == created
        assert row.completed_at is not None

    async def test_uninitialized_engine_returns_none(self, monkeypatch):
        monkeypatch.setattr(persistence, "get_session_factory", lambda: None)

        assert await persistence.save_eval_run(run_id="run-x", kb_id="kb-1", status="skipped", created_at=datetime.now(UTC)) is None


# ── CLI wiring (end-to-end against a throwaway SQLite database) ────────────


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    from deerflow.config.database_config import DatabaseConfig

    return SimpleNamespace(database=DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db")))


class _FakeStore:
    def __init__(self, kb: dict[str, Any] | None) -> None:
        self._sf = None
        self._kb = kb

    async def get_kb(self, kb_id: str) -> dict[str, Any] | None:
        return self._kb


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kb: dict[str, Any] | None) -> None:
    import deerflow.config.app_config as app_config_module
    import deerflow.knowledge.store as store_module

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(store_module, "get_knowledge_store", lambda: _FakeStore(kb))


def _write_golden(path: Path, *questions: dict[str, Any]) -> None:
    path.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8")


def _golden_entry(qid: str, category: str, *, entities: list[str] | None = None) -> dict[str, Any]:
    return {"id": qid, "query": f"query-{qid}", "expected_path": "vector", "relevant_chunk_ids": [CHUNK], "relevant_entities": entities or [], "category": category}


def _read_runs(tmp_path: Path) -> list[EvalRunRow]:
    async def _read() -> list[EvalRunRow]:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

        await init_engine_from_config(_fake_config(tmp_path).database)
        try:
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                result = await session.execute(select(EvalRunRow).order_by(EvalRunRow.created_at))
                return list(result.scalars().all())
        finally:
            await close_engine()

    return asyncio.run(_read())


def _layer1_searchers(*, hit: bool) -> dict[str, Any]:
    from deerflow.knowledge.eval.runner import ScoredHit

    hits = (ScoredHit(CHUNK, 0.9),) if hit else ()

    async def vector_fn(query: str, top_k: int):
        return hits

    async def empty_fn(query: str, top_k: int):
        return ()

    return {"vector": vector_fn, "graph": empty_fn, "wiki": empty_fn}


def _patch_layer1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kb: dict[str, Any] | None, *, hit: bool) -> None:
    _patch_common(monkeypatch, tmp_path, kb)
    import deerflow.knowledge.eval.runner as runner_module
    import deerflow.knowledge.vector_store as vector_store_module

    monkeypatch.setattr(runner_module, "build_default_searchers", lambda **kwargs: _layer1_searchers(hit=hit))
    monkeypatch.setattr(vector_store_module, "get_vector_store", lambda: None)


class TestLayer1CliPersistence:
    def test_completed_run_writes_layer1_only_row(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"), _golden_entry("q2", "relation"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)
        out = tmp_path / "out"

        code = layer1_cli.main(["--golden", str(golden), "--out", str(out), "--kb-id", "kb-1"], environ=dict(KEYS))

        assert code == 0
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.kb_id == "kb-1"
        assert row.status == "completed"
        assert row.layer2_metrics == {}
        assert set(row.layer1_metrics) == {"summary", "fact", "relation", "questions", "top_k"}
        assert row.layer1_metrics["summary"]["question_count"] == 2
        assert row.layer1_metrics["summary"]["recall_at_k"] == pytest.approx(1.0)
        assert row.baseline_diff is None
        assert row.completed_at is not None
        # 时钟单一事实源：created_at == 报告 generated_at
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert _as_utc(row.created_at) == datetime.fromisoformat(report["meta"]["generated_at"])

    def test_regression_run_still_completed_with_baseline_diff(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"), _golden_entry("q2", "relation"))
        baseline = {
            "overall": {"count": 2, "hit_rate": 1.0, "recall": 1.0, "mrr": 1.0, "path_accuracy": 1.0},
            "by_category": {
                "fact": {"count": 1, "hit_rate": 1.0, "recall": 1.0, "mrr": 1.0, "path_accuracy": 1.0},
                "relation": {"count": 1, "hit_rate": 1.0, "recall": 1.0, "mrr": 1.0, "path_accuracy": 1.0},
            },
            "questions": [],
        }
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        # No path surfaces the annotated chunk → recall collapses → gate fails (exit 1).
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=False)

        code = layer1_cli.main(
            ["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--baseline", str(baseline_path)],
            environ=dict(KEYS),
        )

        assert code == 1  # 回退红，但运行本身已完成
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "completed"
        assert row.baseline_diff is not None
        assert row.baseline_diff["regression_detected"] is True
        assert row.baseline_diff["threshold_percent"] == pytest.approx(3.0)
        assert row.baseline_diff["recall_at_k_delta"] == pytest.approx(-1.0)
        assert row.baseline_diff["regressed_categories"] == ["fact", "relation"]

    def test_unknown_kb_writes_error_row(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb=None, hit=True)

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-absent"], environ=dict(KEYS))

        assert code == 2
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].status == "error"
        assert rows[0].kb_id == "kb-absent"
        assert rows[0].layer1_metrics == {}
        assert rows[0].completed_at is None

    def test_missing_keys_writes_skipped_row(self, monkeypatch, tmp_path, capsys):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_common(monkeypatch, tmp_path, kb={"owner_id": "u1"})

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1"], environ={})

        assert code == 3
        assert "skipped" in capsys.readouterr().out
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].status == "skipped"
        assert rows[0].layer1_metrics == {}
        assert rows[0].layer2_metrics == {}


# ── Task 0c: baseline 标记 + environment 列（spec §3.1.3 / §3.1.1 v3）─────────


class TestBaselineReportMapping:
    """Stored ``layer1_metrics`` → runner baseline report payload (``--baseline auto``)."""

    def test_summary_and_categories_reverse_mapped(self):
        metrics = {
            "summary": {"hit_rate": 0.9, "recall_at_k": 0.8, "mrr": 0.7, "path_accuracy": 0.95, "question_count": 2},
            "fact": {"hit_rate": 1.0, "recall_at_k": 1.0, "mrr": 1.0, "path_accuracy": 1.0, "question_count": 1},
            "relation": {"hit_rate": 0.8, "recall_at_k": 0.6, "mrr": 0.4, "path_accuracy": 0.9, "question_count": 1},
        }

        baseline = persistence.baseline_report_from_metrics(metrics)

        # runner._baseline_parts 消费报告键名：overall/by_category 内 count + recall
        # （保存时映射的逆运算：summary→overall、recall_at_k→recall、question_count→count）。
        assert baseline["overall"] == {"count": 2, "hit_rate": 0.9, "recall": 0.8, "mrr": 0.7, "path_accuracy": 0.95}
        assert set(baseline["by_category"]) == {"fact", "relation"}
        assert baseline["by_category"]["relation"]["recall"] == pytest.approx(0.6)
        assert baseline["by_category"]["relation"]["count"] == 1
        # 逐题明细不入库 —— diff 门禁按 category 粒度工作，regressed_questions 为空。
        assert baseline["questions"] == []

    def test_empty_metrics_yield_empty_categories(self):
        baseline = persistence.baseline_report_from_metrics({})

        assert baseline["by_category"] == {}
        assert baseline["questions"] == []


@pytest.mark.asyncio
class TestMarkBaseline:
    async def test_mark_baseline_sets_flag(self, session_factory):
        await persistence.save_eval_run(
            run_id="run-1",
            kb_id="kb-1",
            status="completed",
            created_at=datetime.now(UTC),
            mark_baseline=True,
        )

        row = await persistence.get_baseline_run("kb-1")
        assert row is not None
        assert row.id == "run-1"
        assert row.is_baseline is True

    async def test_new_baseline_clears_previous_marker_same_kb(self, session_factory):
        await persistence.save_eval_run(run_id="run-1", kb_id="kb-1", status="completed", created_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=UTC), mark_baseline=True)
        await persistence.save_eval_run(run_id="run-2", kb_id="kb-1", status="completed", created_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=UTC), mark_baseline=True)
        # 另一 KB 的标记不受影响
        await persistence.save_eval_run(run_id="run-3", kb_id="kb-2", status="completed", created_at=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC), mark_baseline=True)

        baseline_kb1 = await persistence.get_baseline_run("kb-1")
        assert baseline_kb1 is not None and baseline_kb1.id == "run-2"
        baseline_kb2 = await persistence.get_baseline_run("kb-2")
        assert baseline_kb2 is not None and baseline_kb2.id == "run-3"

        async with session_factory() as session:
            rows = {row.id: row for row in (await session.execute(select(EvalRunRow))).scalars().all()}
        assert rows["run-1"].is_baseline is False
        assert rows["run-2"].is_baseline is True
        assert rows["run-3"].is_baseline is True

    async def test_unmarked_run_is_not_baseline_by_default(self, session_factory):
        await persistence.save_eval_run(run_id="run-1", kb_id="kb-1", status="completed", created_at=datetime.now(UTC))

        assert await persistence.get_baseline_run("kb-1") is None
        async with session_factory() as session:
            row = (await session.execute(select(EvalRunRow))).scalar_one()
        assert row.is_baseline is False

    async def test_partial_unique_index_backstops_single_baseline(self, session_factory):
        """绕过清标记逻辑直接插两行 baseline → 部分唯一索引兜底拒绝第二次提交。"""
        async with session_factory() as session:
            session.add(EvalRunRow(id="b-1", kb_id="kb-1", status="completed", layer1_metrics={}, layer2_metrics={}, created_at=datetime.now(UTC), is_baseline=True))
            await session.commit()

        async with session_factory() as session:
            session.add(EvalRunRow(id="b-2", kb_id="kb-1", status="completed", layer1_metrics={}, layer2_metrics={}, created_at=datetime.now(UTC), is_baseline=True))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_get_baseline_run_without_engine_returns_none(self, monkeypatch):
        monkeypatch.setattr(persistence, "get_session_factory", lambda: None)

        assert await persistence.get_baseline_run("kb-1") is None

    @pytest.mark.parametrize("failed_status", ["error", "skipped"])
    async def test_mark_baseline_ignored_for_failed_run(self, session_factory, failed_status):
        """completed 门控（§3.1.3）：失败运行不得成为基线，更不得清掉现有好基线。"""
        await persistence.save_eval_run(run_id="run-good", kb_id="kb-1", status="completed", created_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=UTC), mark_baseline=True)
        await persistence.save_eval_run(run_id="run-bad", kb_id="kb-1", status=failed_status, created_at=datetime.now(UTC), mark_baseline=True)

        baseline = await persistence.get_baseline_run("kb-1")
        assert baseline is not None and baseline.id == "run-good"

        async with session_factory() as session:
            bad_row = await session.get(EvalRunRow, "run-bad")
        assert bad_row is not None
        assert bad_row.is_baseline is False


@pytest.mark.asyncio
class TestEnvironmentPersistence:
    async def test_default_environment_is_local(self, session_factory):
        await persistence.save_eval_run(run_id="run-1", kb_id="kb-1", status="completed", created_at=datetime.now(UTC))

        async with session_factory() as session:
            row = (await session.execute(select(EvalRunRow))).scalar_one()
        assert row.environment == "local"

    async def test_explicit_environment_persisted(self, session_factory):
        await persistence.save_eval_run(run_id="run-1", kb_id="kb-1", status="completed", created_at=datetime.now(UTC), environment="ci")

        async with session_factory() as session:
            row = (await session.execute(select(EvalRunRow))).scalar_one()
        assert row.environment == "ci"


class TestLayer1CliBaselineAndEnvironment:
    def test_environment_flag_wins_over_inference(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        code = layer1_cli.main(
            ["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--environment", "nightly"],
            environ={**KEYS, "CI": "true"},
        )

        assert code == 0
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].environment == "nightly"

    def test_ci_inferred_from_environ(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1"], environ={**KEYS, "CI": "true"})

        assert code == 0
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].environment == "ci"

    def test_default_environment_is_local(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1"], environ=dict(KEYS))

        assert code == 0
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].environment == "local"

    def test_skipped_row_carries_inferred_environment(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_common(monkeypatch, tmp_path, kb={"owner_id": "u1"})

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1"], environ={"CI": "true"})

        assert code == 3
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].environment == "ci"

    def test_mark_baseline_marks_row_and_clears_previous(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        for _ in range(2):
            code = layer1_cli.main(
                ["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--mark-baseline"],
                environ=dict(KEYS),
            )
            assert code == 0

        rows = _read_runs(tmp_path)
        assert len(rows) == 2
        baselines = [row for row in rows if row.is_baseline]
        assert len(baselines) == 1

    def test_mark_baseline_on_skipped_run_keeps_previous_baseline_and_notes_stderr(self, monkeypatch, tmp_path, capsys):
        """缺 key → skipped：--mark-baseline 被忽略，stderr 有提示，既有基线保留。"""
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--mark-baseline"], environ=dict(KEYS))
        assert code == 0

        _patch_common(monkeypatch, tmp_path, kb={"owner_id": "u1"})
        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--mark-baseline"], environ={})

        assert code == 3
        err = capsys.readouterr().err
        assert "--mark-baseline" in err and "ignored" in err
        rows = _read_runs(tmp_path)
        baselines = [row for row in rows if row.is_baseline]
        assert len(baselines) == 1
        assert baselines[0].status == "completed"

    def test_baseline_auto_diffs_against_marked_row(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"), _golden_entry("q2", "relation"))
        out = tmp_path / "out"

        # 第一次：满分运行并标记为 baseline
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)
        code = layer1_cli.main(["--golden", str(golden), "--out", str(out), "--kb-id", "kb-1", "--mark-baseline"], environ=dict(KEYS))
        assert code == 0

        # 第二次：召回归零 + --baseline auto → 从 eval_runs 读标记行做 diff → 门禁红
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=False)
        code = layer1_cli.main(["--golden", str(golden), "--out", str(out), "--kb-id", "kb-1", "--baseline", "auto"], environ=dict(KEYS))

        assert code == 1
        rows = _read_runs(tmp_path)
        assert len(rows) == 2
        regression_row = next(row for row in rows if row.baseline_diff is not None)
        assert regression_row.status == "completed"
        assert regression_row.baseline_diff["regression_detected"] is True
        assert regression_row.baseline_diff["recall_at_k_delta"] == pytest.approx(-1.0)
        assert regression_row.baseline_diff["regressed_categories"] == ["fact", "relation"]
        assert regression_row.baseline_diff["threshold_percent"] == pytest.approx(3.0)

    def test_baseline_auto_without_marked_row_runs_without_diff(self, monkeypatch, tmp_path):
        golden = tmp_path / "golden.jsonl"
        _write_golden(golden, _golden_entry("q1", "fact"))
        _patch_layer1(monkeypatch, tmp_path, kb={"owner_id": "u1"}, hit=True)

        code = layer1_cli.main(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb-1", "--baseline", "auto"], environ=dict(KEYS))

        assert code == 0  # 无 baseline 行 → 按无 diff 运行（exit 0 语义不变）
        rows = _read_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].baseline_diff is None
