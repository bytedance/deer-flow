"""Tests for the batch retrieval evaluation runner (spec 2026-08-23 §6).

The retrieval impl is a stubbed searcher; assertions cover the degradation
contract (a failing path never sinks the run), the report schema and JSON
round-trip, the meta block (fixed parameters + version extras), baseline-diff
exit-code semantics, and the markdown/terminal renderings. No Qdrant, no LLM,
no database.
"""

from __future__ import annotations

import json

import pytest
from deerflow_knowledge.eval.dataset import GoldenQuestion
from deerflow_knowledge.eval.runner import (
    ScoredHit,
    render_markdown,
    render_summary,
    report_from_dict,
    report_to_dict,
    run_evaluation,
    write_reports,
)


def _question(qid: str, *, category: str = "text", expected_path: str = "vector", expected_paths: tuple[str, ...] | None = None, chunks=("c1",)) -> GoldenQuestion:
    return GoldenQuestion(
        id=qid,
        query=f"query-{qid}",
        expected_paths=expected_paths or (expected_path,),
        relevant_chunk_ids=tuple(chunks),
        relevant_entities=(),
        category=category,
        reference_answer=None,
    )


def _ok(hits: tuple[tuple[str, float], ...]):
    async def searcher(query: str, top_k: int):
        return tuple(ScoredHit(chunk_id=cid, score=score) for cid, score in hits)

    return searcher


async def _boom(query: str, top_k: int):
    raise RuntimeError("path exploded")


class TestRunEvaluation:
    async def test_vector_path_succeeds(self):
        searchers = {"vector": _ok((("c1", 0.9), ("c2", 0.5)))}

        report = await run_evaluation([_question("q1")], searchers, top_k=5)

        assert report.exit_code == 0
        assert report.diff is None
        assert report.overall.count == 1
        assert report.overall.recall == 1.0
        q = report.questions[0]
        assert q.metrics.actual_path == "vector"
        assert q.metrics.path_correct is True

    async def test_path_failure_degrades_without_sinking_run(self):
        searchers = {"vector": _boom}

        report = await run_evaluation([_question("q1")], searchers, top_k=5)

        assert report.exit_code == 0  # 一次运行总能产出完整报告
        q = report.questions[0]
        assert q.paths["vector"].failure is not None and "exploded" in q.paths["vector"].failure
        assert q.paths["vector"].hits == ()
        assert q.metrics.per_path["vector"].recall == 0.0
        assert q.metrics.actual_path is None

    async def test_searcher_receives_query_and_top_k(self):
        seen = []

        async def probe(query: str, top_k: int):
            seen.append((query, top_k))
            return ()

        await run_evaluation([_question("q1")], {"vector": probe}, top_k=7)

        assert seen == [("query-q1", 7)]

    async def test_meta_extra_lands_in_the_report(self):
        # RFC v3 §8.1：固定参数与版本块必须随报告存档（run 与报告不许各说各话）。
        searchers = {"vector": _ok((("c1", 0.9),))}

        report = await run_evaluation(
            [_question("q1")],
            searchers,
            top_k=5,
            generated_at="2026-10-08T00:00:00+00:00",
            meta_extra={"candidate_limit": 20, "embedding_model": "test-embed", "embedding_dimension": 1024},
        )

        assert report.meta["candidate_limit"] == 20
        assert report.meta["embedding_model"] == "test-embed"
        assert report.meta["top_k"] == 5
        data = report_to_dict(report)
        assert data["meta"]["candidate_limit"] == 20
        assert data["meta"]["generated_at"] == "2026-10-08T00:00:00+00:00"

    async def test_baseline_regression_sets_exit_code_1(self):
        searchers = {"vector": _ok((("c9", 0.9),))}
        baseline = _baseline_dict(recall_by_category={"text": 1.0})

        report = await run_evaluation([_question("q1")], searchers, top_k=5, baseline=baseline, fail_threshold=0.03)

        assert report.diff is not None and report.diff.failed is True
        assert report.exit_code == 1
        assert report.diff.regressed_questions == ("q1",)

    async def test_baseline_within_threshold_passes(self):
        searchers = {"vector": _ok((("c1", 0.9),))}
        baseline = _baseline_dict(recall_by_category={"text": 1.0}, question_recalls={"q1": 1.0})

        report = await run_evaluation([_question("q1")], searchers, top_k=5, baseline=baseline)

        assert report.exit_code == 0
        assert report.diff is not None and report.diff.failed is False


def _baseline_dict(*, recall_by_category: dict[str, float], question_recalls: dict[str, float] | None = None) -> dict:
    return {
        "overall": {"count": 1, "hit_rate": 1.0, "recall": 1.0, "mrr": 1.0, "path_accuracy": 1.0},
        "by_category": {cat: {"count": 1, "hit_rate": r, "recall": r, "mrr": r, "path_accuracy": 1.0} for cat, r in recall_by_category.items()},
        "questions": [{"id": qid, "recall": r} for qid, r in (question_recalls or {"q1": 1.0}).items()],
    }


class TestReportSchema:
    async def _report(self):
        searchers = {"vector": _ok((("c1", 0.9),))}
        return await run_evaluation(
            [_question("q1"), _question("q2", category="image", chunks=(), expected_path="vector")],
            searchers,
            top_k=5,
        )

    async def test_report_to_dict_is_json_serializable_with_stable_schema(self):
        report = await self._report()

        data = report_to_dict(report)
        encoded = json.dumps(data, ensure_ascii=False)  # must not raise
        assert json.loads(encoded)["meta"]["top_k"] == 5

        assert set(data) == {"schema_version", "meta", "overall", "by_category", "questions", "diff"}
        assert set(data["overall"]) == {"count", "hit_rate", "recall", "mrr", "path_accuracy"}
        assert set(data["by_category"]) == {"text", "image"}
        q1 = data["questions"][0]
        assert set(q1) == {"id", "category", "expected_paths", "actual_path", "path_correct", "hit", "recall", "mrr", "paths"}
        assert q1["expected_paths"] == ["vector"]
        assert set(q1["paths"]) == {"vector"}
        assert q1["paths"]["vector"]["hits"] == [{"chunk_id": "c1", "score": 0.9}]
        assert data["diff"] is None

    async def test_report_round_trip_enables_baseline_diff(self):
        report = await self._report()
        baseline = report_from_dict(report_to_dict(report))

        rerun = await self._report()
        diff_report = await run_evaluation(
            [_question("q1"), _question("q2", category="image", chunks=(), expected_path="vector")],
            {"vector": _ok((("c1", 0.9),))},
            top_k=5,
            baseline=report_to_dict(rerun),
        )
        assert baseline["by_category"]["text"]["recall"] == pytest.approx(1.0)
        assert diff_report.diff is not None
        assert diff_report.diff.failed is False
        assert diff_report.exit_code == 0

    async def test_write_reports_emits_json_and_markdown(self, tmp_path):
        report = await self._report()

        json_path, md_path = write_reports(report, tmp_path)

        assert json_path.name == "report.json" and md_path.name == "report.md"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["overall"]["count"] == 2
        md = md_path.read_text(encoding="utf-8")
        # 分组轴：文字/表格/图片各组一行（RFC v3 §8.1——图片组不被总分掩盖）。
        assert "| text |" in md and "| image |" in md


class TestRenderSummary:
    async def test_summary_lists_categories_and_key_metrics(self):
        searchers = {"vector": _ok((("c1", 0.9),))}
        report = await run_evaluation([_question("q1"), _question("q2", category="table", chunks=("c3",))], searchers, top_k=5)

        summary = render_summary(report)

        assert "overall" in summary and "text" in summary and "table" in summary
        assert "recall" in summary and "path_acc" in summary

    async def test_summary_prints_fixed_parameters(self):
        searchers = {"vector": _ok((("c1", 0.9),))}
        report = await run_evaluation([_question("q1")], searchers, top_k=5, meta_extra={"candidate_limit": 20})

        summary = render_summary(report)

        assert "top_k: 5" in summary and "candidate_limit: 20" in summary

    async def test_markdown_lists_regressed_question_detail(self):
        searchers = {"vector": _ok((("c9", 0.9),))}
        baseline = _baseline_dict(recall_by_category={"text": 1.0}, question_recalls={"q1": 1.0})
        report = await run_evaluation([_question("q1")], searchers, top_k=5, baseline=baseline)

        md = render_markdown(report)

        assert "q1" in md
        assert "c1" in md  # 预期命中 chunk
        assert "c9" in md  # 实际命中 chunk


class TestBaselineReportCompat:
    """旧 CLI report.json 用单值 ``expected_path`` 键，新报告用 ``expected_paths``
    列表——``_baseline_parts`` 两个键都认（§9 兼容纪律）；历史报告里的
    graph/wiki 值只是数据，diff 只消费 recall。"""

    async def test_legacy_single_key_baseline_still_diffs(self):
        baseline = _baseline_dict(recall_by_category={"text": 1.0}, question_recalls={"q1": 1.0})
        baseline["questions"] = [{"id": "q1", "recall": 1.0, "expected_path": "vector"}]

        report = await run_evaluation([_question("q1")], {"vector": _ok((("c1", 0.9),))}, top_k=5, baseline=baseline)

        assert report.diff is not None
        assert report.diff.failed is False

    async def test_new_list_key_baseline_still_diffs(self):
        baseline = _baseline_dict(recall_by_category={"text": 1.0}, question_recalls={"q1": 1.0})
        baseline["questions"] = [{"id": "q1", "recall": 1.0, "expected_paths": ["vector", "graph"]}]

        report = await run_evaluation([_question("q1")], {"vector": _ok((("c1", 0.9),))}, top_k=5, baseline=baseline)

        assert report.diff is not None
        assert report.diff.failed is False
