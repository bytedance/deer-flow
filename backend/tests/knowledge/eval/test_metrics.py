"""Tests for the deterministic IR metrics of retrieval evaluation (spec 2026-08-23 §6).

Pure-function coverage: per-list hit / recall@k / MRR, path selection by
top-1 score, per-question evaluation on the vector path (the first-phase
slice's single retrieval path), category (text/table/image) aggregation, and
baseline diff with the regression gate. No IO.
"""

from __future__ import annotations

import pytest
from deerflow_knowledge.eval.dataset import GoldenQuestion
from deerflow_knowledge.eval.metrics import (
    AggregateMetrics,
    DiffResult,
    PathResult,
    aggregate,
    aggregate_by_category,
    choose_path,
    diff_metrics,
    evaluate_question,
    hit,
    recall_at_k,
    reciprocal_rank,
)


def _question(**overrides) -> GoldenQuestion:
    raw = {
        "id": "q001",
        "query": "q",
        "expected_paths": ("vector",),
        "relevant_chunk_ids": ("c1", "c2"),
        "relevant_entities": (),
        "category": "text",
        "reference_answer": None,
    }
    raw.update(overrides)
    return GoldenQuestion(**raw)


class TestChunkListMetrics:
    def test_recall_partial(self):
        assert recall_at_k({"c1", "c2", "c3"}, ["c9", "c1", "c2"]) == pytest.approx(2 / 3)

    def test_recall_none_hit(self):
        assert recall_at_k({"c1"}, ["c9"]) == 0.0

    def test_recall_empty_relevant_is_excluded(self):
        assert recall_at_k((), ["c1"]) is None

    def test_hit_any(self):
        assert hit({"c1"}, ["c9", "c1"]) == 1.0

    def test_hit_none(self):
        assert hit({"c1"}, ["c9"]) == 0.0

    def test_hit_empty_relevant_is_excluded(self):
        assert hit((), ["c1"]) is None

    def test_rr_first(self):
        assert reciprocal_rank({"c1"}, ["c1", "c2"]) == 1.0

    def test_rr_third(self):
        assert reciprocal_rank({"c1"}, ["c9", "c8", "c1"]) == pytest.approx(1 / 3)

    def test_rr_none(self):
        assert reciprocal_rank({"c1"}, ["c9"]) == 0.0

    def test_rr_empty_relevant_is_excluded(self):
        assert reciprocal_rank((), ["c1"]) is None


class TestChoosePath:
    def test_picks_the_path_with_hits(self):
        assert choose_path({"vector": PathResult(hits=("c1",), top_score=0.4)}) == "vector"

    def test_null_score_counts_as_zero_but_still_wins_alone(self):
        assert choose_path({"vector": PathResult(hits=("c1",), top_score=None)}) == "vector"

    def test_path_without_hits_is_excluded_even_with_score(self):
        assert choose_path({"vector": PathResult(hits=(), top_score=0.9)}) is None

    def test_failed_path_counts_as_empty(self):
        assert choose_path({"vector": PathResult(hits=(), top_score=None, failure="boom")}) is None

    def test_keys_outside_the_path_order_are_ignored(self):
        # 首期切片只跑 vector；机制上 PATH_ORDER 之外的键不参与选择（第二路回归时天然启用）。
        assert choose_path({"graph": PathResult(hits=("c2",), top_score=0.9)}) is None


class TestEvaluateQuestion:
    def test_single_path_metrics(self):
        q = _question()
        paths = {"vector": PathResult(hits=("c1", "c9"), top_score=0.9)}

        m = evaluate_question(q, paths)

        assert m.hit == 1.0
        assert m.recall == 0.5  # c1 of {c1, c2}
        assert m.mrr == 1.0  # c1 ranks first

    def test_path_selection_correctness(self):
        q = _question(expected_paths=("vector",))
        paths = {"vector": PathResult(hits=("c1",), top_score=0.4)}

        m = evaluate_question(q, paths)

        assert m.actual_path == "vector"
        assert m.path_correct is True

    def test_no_hits_anywhere_counts_as_wrong_path(self):
        q = _question()
        m = evaluate_question(q, {"vector": PathResult()})

        assert m.actual_path is None
        assert m.path_correct is False
        assert m.hit == 0.0
        assert m.recall == 0.0
        assert m.mrr == 0.0

    def test_expected_set_membership_semantics_survive(self):
        # 判定是集合成员（spec 2026-08-28 §4）：实际胜出者属于期望集合即对。
        # 单路现实下 actual 只可能是 vector；机制保留，第二路回归时无需改判定。
        q = _question(expected_paths=("vector", "graph"))
        m = evaluate_question(q, {"vector": PathResult(hits=("c1",), top_score=0.9)})

        assert m.expected_paths == ("vector", "graph")
        assert m.actual_path == "vector"
        assert m.path_correct is True

    def test_empty_relevant_skips_chunk_metrics_but_keeps_path(self):
        q = _question(relevant_chunk_ids=())
        paths = {"vector": PathResult(hits=("c1",), top_score=0.9)}

        m = evaluate_question(q, paths)

        assert m.hit is None and m.recall is None and m.mrr is None
        assert m.actual_path == "vector"
        assert m.path_correct is True

    def test_per_path_breakdown(self):
        q = _question()
        paths = {"vector": PathResult(hits=("c1",), top_score=0.9)}

        m = evaluate_question(q, paths)

        assert m.per_path["vector"].recall == 0.5
        assert set(m.per_path) == {"vector"}

    def test_degraded_path_reports_zero_recall(self):
        q = _question()
        paths = {"vector": PathResult(hits=(), top_score=None, failure="boom")}

        m = evaluate_question(q, paths)

        assert m.per_path["vector"].recall == 0.0
        assert m.actual_path is None


class TestAggregate:
    def test_means_over_questions(self):
        results = [
            evaluate_question(_question(id="q1", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
            evaluate_question(_question(id="q2", relevant_chunk_ids=("c1", "c2")), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
        ]

        agg = aggregate(results)

        assert agg.count == 2
        assert agg.hit_rate == 1.0
        assert agg.recall == pytest.approx((1.0 + 0.5) / 2)
        assert agg.mrr == 1.0
        assert agg.path_accuracy == 1.0

    def test_none_metrics_are_excluded_from_means(self):
        with_chunks = evaluate_question(_question(id="q1", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)})
        without_chunks = evaluate_question(_question(id="q2", relevant_chunk_ids=()), {"vector": PathResult()})

        agg = aggregate([with_chunks, without_chunks])

        assert agg.count == 2
        assert agg.recall == 1.0  # only q1 participates
        assert agg.path_accuracy == 0.5  # q2 has no actual path -> incorrect

    def test_empty_results(self):
        agg = aggregate([])

        assert agg.count == 0
        assert agg.hit_rate is None and agg.recall is None and agg.mrr is None
        assert agg.path_accuracy == 0.0

    def test_group_by_category(self):
        results = [
            evaluate_question(_question(id="q1", category="text"), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
            evaluate_question(_question(id="q2", category="image", relevant_chunk_ids=()), {"vector": PathResult()}),
        ]

        grouped = aggregate_by_category(results)

        assert set(grouped) == {"text", "image"}
        assert grouped["text"].count == 1
        assert grouped["image"].path_accuracy == 0.0


def _agg(recall: float | None, *, hit_rate=0.0, mrr=0.0, path_accuracy=0.0, count=5) -> AggregateMetrics:
    return AggregateMetrics(count=count, hit_rate=hit_rate, recall=recall, mrr=mrr, path_accuracy=path_accuracy)


class TestDiffMetrics:
    def test_deltas_per_scope_and_metric(self):
        before = {"text": _agg(0.8, hit_rate=0.9)}
        after = {"text": _agg(0.7, hit_rate=1.0)}

        diff = diff_metrics(before, after)

        by_key = {(d.scope, d.metric): d for d in diff.deltas}
        assert by_key[("text", "recall")].delta == pytest.approx(-0.1)
        assert by_key[("text", "hit_rate")].delta == pytest.approx(0.1)
        assert diff.failed is True
        assert any("text" in f and "recall" in f for f in diff.failures)

    def test_gate_threshold_boundary(self):
        before = {"text": _agg(0.80)}
        at_threshold = {"text": _agg(0.77)}
        beyond = {"text": _agg(0.769)}

        assert diff_metrics(before, at_threshold, fail_threshold=0.03).failed is False
        assert diff_metrics(before, beyond, fail_threshold=0.03).failed is True

    def test_improvement_never_fails(self):
        diff = diff_metrics({"text": _agg(0.5)}, {"text": _agg(0.9)})

        assert diff.failed is False
        assert diff.failures == ()

    def test_overall_scope_is_reported_but_not_gated(self):
        before = {"overall": _agg(0.9), "text": _agg(0.9)}
        after = {"overall": _agg(0.5), "text": _agg(0.9)}  # overall tanks, categories stable

        diff = diff_metrics(before, after)

        assert diff.failed is False  # spec gates on per-category recall only
        assert any(d.scope == "overall" and d.metric == "recall" for d in diff.deltas)

    def test_image_group_gates_on_its_own_recall(self):
        # RFC v3 §8.1：图片链失效不能被总分掩盖——image 组自己的 recall 回退即门禁失败。
        before = {"overall": _agg(0.9), "text": _agg(0.9), "image": _agg(1.0)}
        after = {"overall": _agg(0.9), "text": _agg(0.9), "image": _agg(0.0)}

        diff = diff_metrics(before, after)

        assert diff.failed is True
        assert any("image" in f for f in diff.failures)

    def test_scope_only_on_one_side_gets_none_delta(self):
        diff = diff_metrics({"text": _agg(0.8)}, {"text": _agg(0.8), "image": _agg(None)})

        image_recall = next(d for d in diff.deltas if d.scope == "image" and d.metric == "recall")
        assert image_recall.delta is None
        assert diff.failed is False

    def test_regressed_questions_listed_sorted(self):
        q_before = [
            evaluate_question(_question(id="q2", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
            evaluate_question(_question(id="q1", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
        ]
        q_after = [
            evaluate_question(_question(id="q2", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c9",), top_score=0.9)}),
            evaluate_question(_question(id="q1", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
        ]

        diff = diff_metrics({}, {}, before_questions=q_before, after_questions=q_after)

        assert isinstance(diff, DiffResult)
        assert diff.regressed_questions == ("q2",)

    def test_regressed_questions_ignore_new_and_missing(self):
        q_before = [evaluate_question(_question(id="q1", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=("c1",), top_score=0.9)})]
        q_after = [evaluate_question(_question(id="q9", relevant_chunk_ids=("c1",)), {"vector": PathResult(hits=(), top_score=None)})]

        diff = diff_metrics({}, {}, before_questions=q_before, after_questions=q_after)

        assert diff.regressed_questions == ()
