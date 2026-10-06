"""Tests for the batch retrieval evaluation runner (spec 2026-08-23 §6).

The three retrieval impls are stubbed searchers; assertions cover the
degradation contract (one failing path never sinks the run), the report
schema and JSON round-trip, baseline-diff exit-code semantics, and the
markdown/terminal renderings. No Qdrant, no LLM, no database.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.eval.runner import (
    ScoredHit,
    build_default_searchers,
    render_markdown,
    render_summary,
    report_from_dict,
    report_to_dict,
    run_evaluation,
    write_reports,
)


def _question(qid: str, *, category: str = "fact", expected_path: str = "vector", expected_paths: tuple[str, ...] | None = None, chunks=("c1",)) -> GoldenQuestion:
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
    async def test_all_paths_succeed(self):
        searchers = {
            "vector": _ok((("c1", 0.9), ("c2", 0.5))),
            "graph": _ok((("c3", 0.4),)),
            "wiki": _ok(()),
        }

        report = await run_evaluation([_question("q1")], searchers, top_k=5)

        assert report.exit_code == 0
        assert report.diff is None
        assert report.overall.count == 1
        assert report.overall.recall == 1.0
        q = report.questions[0]
        assert q.metrics.actual_path == "vector"
        assert q.metrics.path_correct is True

    async def test_single_path_failure_degrades_without_sinking_run(self):
        searchers = {
            "vector": _ok((("c1", 0.9),)),
            "graph": _boom,
            "wiki": _ok((("c2", 0.3),)),
        }

        report = await run_evaluation([_question("q1", chunks=("c1", "c2"))], searchers, top_k=5)

        assert report.exit_code == 0  # 一次运行总能产出完整报告
        q = report.questions[0]
        assert q.paths["graph"].failure is not None and "exploded" in q.paths["graph"].failure
        assert q.paths["graph"].hits == ()
        assert q.metrics.per_path["graph"].recall == 0.0  # 该路空 hits
        assert q.metrics.recall == 1.0  # 并集仍由 vector/wiki 覆盖
        assert q.metrics.actual_path == "vector"

    async def test_searcher_receives_query_and_top_k(self):
        seen = []

        async def probe(query: str, top_k: int):
            seen.append((query, top_k))
            return ()

        await run_evaluation([_question("q1")], {"vector": probe, "graph": probe, "wiki": probe}, top_k=7)

        assert seen == [("query-q1", 7)] * 3

    async def test_baseline_regression_sets_exit_code_1(self):
        searchers = {"vector": _ok((("c9", 0.9),)), "graph": _ok(()), "wiki": _ok(())}
        baseline = _baseline_dict(recall_by_category={"fact": 1.0})

        report = await run_evaluation([_question("q1")], searchers, top_k=5, baseline=baseline, fail_threshold=0.03)

        assert report.diff is not None and report.diff.failed is True
        assert report.exit_code == 1
        assert report.diff.regressed_questions == ("q1",)

    async def test_baseline_within_threshold_passes(self):
        searchers = {"vector": _ok((("c1", 0.9),)), "graph": _ok(()), "wiki": _ok(())}
        # baseline recall 1.0 but question has two relevant chunks, only one hit → 0.5 drop… use equal instead
        baseline = _baseline_dict(recall_by_category={"fact": 1.0}, question_recalls={"q1": 1.0})

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
        searchers = {
            "vector": _ok((("c1", 0.9),)),
            "graph": _boom,
            "wiki": _ok((("c2", 0.3),)),
        }
        return await run_evaluation(
            [_question("q1", chunks=("c1", "c2")), _question("q2", category="global", expected_path="wiki", chunks=())],
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
        assert set(data["by_category"]) == {"fact", "global"}
        q1 = data["questions"][0]
        assert set(q1) == {"id", "category", "expected_paths", "actual_path", "path_correct", "hit", "recall", "mrr", "paths"}
        assert q1["expected_paths"] == ["vector"]  # 单路题序列化为单元素列表（新格式）
        assert q1["paths"]["graph"]["failure"] is not None
        assert q1["paths"]["vector"]["hits"] == [{"chunk_id": "c1", "score": 0.9}]
        assert data["diff"] is None

    async def test_report_serializes_multi_path_expectations(self):
        report = await run_evaluation([_question("q1", expected_paths=("vector", "graph"))], {"vector": _ok((("c1", 0.9),)), "graph": _ok(()), "wiki": _ok(())}, top_k=5)

        q1 = report_to_dict(report)["questions"][0]

        assert q1["expected_paths"] == ["vector", "graph"]
        assert q1["path_correct"] is True

    async def test_report_round_trip_enables_baseline_diff(self):
        report = await self._report()
        baseline = report_from_dict(report_to_dict(report))

        rerun = await self._report()
        diff_report = await run_evaluation(
            [_question("q1", chunks=("c1", "c2")), _question("q2", category="global", expected_path="wiki", chunks=())],
            {"vector": _ok((("c1", 0.9),)), "graph": _boom, "wiki": _ok((("c2", 0.3),))},
            top_k=5,
            baseline=report_to_dict(rerun),
        )
        assert baseline["by_category"]["fact"]["recall"] == pytest.approx(1.0)
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
        assert "fact" in md and "global" in md

    async def test_markdown_separates_global_section(self):
        report = await self._report()

        md = render_markdown(report)

        assert "## global" in md  # global 类单独分区（设计意图：预期大面积失败）


class TestRenderSummary:
    async def test_summary_lists_categories_and_key_metrics(self):
        searchers = {"vector": _ok((("c1", 0.9),)), "graph": _ok(()), "wiki": _ok(())}
        report = await run_evaluation([_question("q1"), _question("q2", category="relation", expected_path="graph", chunks=("c3",))], searchers, top_k=5)

        summary = render_summary(report)

        assert "overall" in summary and "fact" in summary and "relation" in summary
        assert "recall" in summary and "path_acc" in summary

    async def test_markdown_lists_regressed_question_detail(self):
        searchers = {"vector": _ok((("c9", 0.9),)), "graph": _ok(()), "wiki": _ok(())}
        baseline = _baseline_dict(recall_by_category={"fact": 1.0}, question_recalls={"q1": 1.0})
        report = await run_evaluation([_question("q1")], searchers, top_k=5, baseline=baseline)

        md = render_markdown(report)

        assert "q1" in md
        assert "c1" in md  # 预期命中 chunk
        assert "c9" in md  # 实际命中 chunk

    async def test_markdown_regressed_detail_lists_expected_paths(self):
        # 回退题详情展示多路预期（逗号连接，spec §4 渲染约定）。
        searchers = {"vector": _ok((("c9", 0.9),)), "graph": _ok(()), "wiki": _ok(())}
        baseline = _baseline_dict(recall_by_category={"fact": 1.0}, question_recalls={"q1": 1.0})
        report = await run_evaluation([_question("q1", expected_paths=("vector", "graph"))], searchers, top_k=5, baseline=baseline)

        md = render_markdown(report)

        assert "预期路径: vector, graph" in md


class TestBaselineReportCompat:
    """旧 CLI report.json 用单值 ``expected_path`` 键，新报告用 ``expected_paths``
    列表——``_baseline_parts`` 两个键都认（§9 兼容纪律）。"""

    async def test_legacy_single_key_baseline_still_diffs(self):
        baseline = _baseline_dict(recall_by_category={"fact": 1.0}, question_recalls={"q1": 1.0})
        baseline["questions"] = [{"id": "q1", "recall": 1.0, "expected_path": "vector"}]

        report = await run_evaluation([_question("q1")], {"vector": _ok((("c1", 0.9),)), "graph": _ok(()), "wiki": _ok(())}, top_k=5, baseline=baseline)

        assert report.diff is not None
        assert report.diff.failed is False

    async def test_new_multi_key_baseline_still_diffs(self):
        baseline = _baseline_dict(recall_by_category={"fact": 1.0}, question_recalls={"q1": 1.0})
        baseline["questions"] = [{"id": "q1", "recall": 1.0, "expected_paths": ["vector", "graph"]}]

        report = await run_evaluation([_question("q1", expected_paths=("vector", "graph"))], {"vector": _ok((("c1", 0.9),)), "graph": _ok(()), "wiki": _ok(())}, top_k=5, baseline=baseline)

        assert report.diff is not None
        assert report.diff.failed is False


class TestBuildDefaultSearchers:
    async def test_graph_searcher_mirrors_recall_test_config_wiring(self, monkeypatch):
        """The graph path must receive the same config-driven parameters the
        online wrapper passes (spec §6: 评估逻辑与线上永远同源)."""
        captured = {}

        async def fake_graph_impl(query, runtime, **kwargs):
            captured.update(kwargs)
            return {"entities": [], "relations": [], "evidence": [{"chunk_id": "c1", "score": 0.7}], "message": ""}

        async def fake_vector_impl(query, runtime, **kwargs):
            return {"results": [{"chunk_id": "c1", "score": 0.9}], "message": ""}

        async def fake_wiki_impl(query, runtime, **kwargs):
            return {"entries": [{"entry_id": "e1", "title": "t", "score": 0.3, "source_type": "wiki"}], "message": ""}

        rag = SimpleNamespace(
            graph_rerank=False,
            graph_per_entity_cap=3,
            graph_per_edge_cap=2,
            graph_hop0_guarantee=2,
            graph_evidence_limit=8,
            graph_rerank_threshold=12,
            graph_hop_penalty=0.0,
            graph_neighbor_min_score=0.4,
            graph_max_expanded_nodes=25,
            graph_hub_degree_threshold=50,
        )
        wiki_store = SimpleNamespace()

        async def fake_get_entry(entry_id):
            return {"id": entry_id, "source_chunk_ids": ["c2"]}

        wiki_store.get_entry = fake_get_entry
        searchers = build_default_searchers(
            kb_id="kb1",
            user_id="u1",
            store=object(),
            vector_store=object(),
            graph_store=object(),
            wiki_store=wiki_store,
            rag=rag,
            hybrid_impl=fake_vector_impl,
            graph_impl=fake_graph_impl,
            wiki_impl=fake_wiki_impl,
        )

        graph_hits = await searchers["graph"]("q", 5)
        assert [h.chunk_id for h in graph_hits] == ["c1"]
        # recall_test 同源：evidence_limit 取 top_k，config 参数全量镜像
        assert captured["evidence_limit"] == 5
        assert captured["per_entity_cap"] == 3
        assert captured["neighbor_min_score"] == 0.4
        assert captured["hub_degree_threshold"] == 50
        assert captured["reranker"] is None  # graph_rerank=False → 不构造 reranker

        vector_hits = await searchers["vector"]("q", 5)
        assert [h.chunk_id for h in vector_hits] == ["c1"]

        wiki_hits = await searchers["wiki"]("q", 5)
        assert [h.chunk_id for h in wiki_hits] == ["c2"]  # entry → source_chunk_ids 归一化

    async def test_wiki_manual_cards_have_no_source_chunks(self):
        async def fake_wiki_impl(query, runtime, **kwargs):
            return {"entries": [{"entry_id": "m1", "title": "card", "score": 0.8, "source_type": "manual"}], "message": ""}

        searchers = build_default_searchers(
            kb_id="kb1",
            user_id="u1",
            store=object(),
            vector_store=object(),
            graph_store=object(),
            wiki_store=SimpleNamespace(),
            rag=SimpleNamespace(graph_rerank=False),
            hybrid_impl=_ok(()),
            graph_impl=_ok(()),
            wiki_impl=fake_wiki_impl,
        )

        hits = await searchers["wiki"]("q", 5)
        assert hits == ()  # 人工卡片无 chunk 映射，跳过而非报错
