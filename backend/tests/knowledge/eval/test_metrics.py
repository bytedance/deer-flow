"""Tests for the deterministic IR metrics of retrieval evaluation (spec 2026-08-23 §6).

Pure-function coverage: per-list hit / recall@k / MRR, path selection by
top-1 score, per-question evaluation across the three retrieval paths,
category aggregation, and baseline diff with the regression gate. No IO.
"""

from __future__ import annotations

import pytest

from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.eval.metrics import (
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
        "category": "fact",
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
    def test_picks_highest_top_score(self):
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.4),
            "graph": PathResult(hits=("c2",), top_score=0.9),
            "wiki": PathResult(hits=("c3",), top_score=0.6),
        }
        assert choose_path(paths) == "graph"

    def test_tie_broken_by_fixed_path_order(self):
        paths = {
            "wiki": PathResult(hits=("c3",), top_score=0.5),
            "graph": PathResult(hits=("c2",), top_score=0.5),
            "vector": PathResult(hits=("c1",), top_score=0.5),
        }
        assert choose_path(paths) == "vector"

    def test_path_without_hits_is_excluded_even_with_score(self):
        paths = {
            "vector": PathResult(hits=(), top_score=None),
            "graph": PathResult(hits=("c2",), top_score=0.1),
        }
        assert choose_path(paths) == "graph"

    def test_failed_path_counts_as_empty(self):
        paths = {
            "vector": PathResult(hits=(), top_score=None, failure="boom"),
            "graph": PathResult(hits=(), top_score=None, failure="boom"),
            "wiki": PathResult(hits=(), top_score=None),
        }
        assert choose_path(paths) is None


class TestEvaluateQuestion:
    def test_union_recall_across_paths(self):
        q = _question()
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.9),
            "graph": PathResult(hits=(), top_score=None),
            "wiki": PathResult(hits=("c2",), top_score=0.3),
        }

        m = evaluate_question(q, paths)

        assert m.hit == 1.0
        assert m.recall == 1.0  # c1 via vector + c2 via wiki
        assert m.mrr == 1.0  # c1 ranks first on vector

    def test_mrr_takes_best_rank_across_paths(self):
        q = _question(relevant_chunk_ids=("c1",))
        paths = {
            "vector": PathResult(hits=("c9", "c8", "c1"), top_score=0.9),
            "graph": PathResult(hits=("c1",), top_score=0.2),
            "wiki": PathResult(hits=(), top_score=None),
        }

        m = evaluate_question(q, paths)

        assert m.mrr == 1.0  # graph ranks it first, beating vector's 1/3

    def test_path_selection_correctness(self):
        q = _question(expected_paths=("graph",))
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.9),
            "graph": PathResult(hits=("c2",), top_score=0.4),
        }

        m = evaluate_question(q, paths)

        assert m.actual_path == "vector"
        assert m.path_correct is False

    def test_no_hits_anywhere_counts_as_wrong_path(self):
        q = _question()
        m = evaluate_question(q, {"vector": PathResult(), "graph": PathResult(), "wiki": PathResult()})

        assert m.actual_path is None
        assert m.path_correct is False
        assert m.hit == 0.0
        assert m.recall == 0.0
        assert m.mrr == 0.0

    # ── expected_paths 多路集合判定（spec 2026-08-28 §4）──────────────

    def test_multi_path_any_expected_winner_counts_correct(self):
        # 语义：这些路任何一路承担本题都算对（非必须全调）。
        q = _question(expected_paths=("vector", "graph"))
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.9),
            "graph": PathResult(hits=("c2",), top_score=0.4),
            "wiki": PathResult(hits=(), top_score=None),
        }

        m = evaluate_question(q, paths)

        assert m.expected_paths == ("vector", "graph")
        assert m.actual_path == "vector"
        assert m.path_correct is True

    def test_multi_path_second_expected_winner_also_counts_correct(self):
        # 分数抖动下另一路胜出仍应 ✅——这是多路化的动机场景。
        q = _question(expected_paths=("vector", "graph"))
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.4),
            "graph": PathResult(hits=("c2",), top_score=0.9),
            "wiki": PathResult(hits=(), top_score=None),
        }

        assert evaluate_question(q, paths).path_correct is True

    def test_multi_path_unexpected_winner_counts_wrong(self):
        q = _question(expected_paths=("vector", "graph"))
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.2),
            "graph": PathResult(hits=(), top_score=None),
            "wiki": PathResult(hits=("c2",), top_score=0.9),
        }

        m = evaluate_question(q, paths)

        assert m.actual_path == "wiki"
        assert m.path_correct is False

    def test_multi_path_no_hits_still_counts_wrong(self):
        q = _question(expected_paths=("vector", "graph"))

        m = evaluate_question(q, {"vector": PathResult(), "graph": PathResult(), "wiki": PathResult()})

        assert m.actual_path is None
        assert m.path_correct is False

    def test_aggregate_path_accuracy_counts_multi_path_results(self):
        right = evaluate_question(
            _question(id="q_ok", expected_paths=("vector", "graph")),
            {"vector": PathResult(hits=("c1",), top_score=0.9), "graph": PathResult()},
        )
        wrong = evaluate_question(
            _question(id="q_bad", expected_paths=("vector", "graph")),
            {"vector": PathResult(), "wiki": PathResult(hits=("c2",), top_score=0.8)},
        )

        assert aggregate([right, wrong]).path_accuracy == pytest.approx(0.5)

    def test_empty_relevant_skips_chunk_metrics_but_keeps_path(self):
        q = _question(relevant_chunk_ids=())
        paths = {"vector": PathResult(hits=("c1",), top_score=0.9)}

        m = evaluate_question(q, paths)

        assert m.hit is None and m.recall is None and m.mrr is None
        assert m.actual_path == "vector"
        assert m.path_correct is True

    def test_per_path_breakdown(self):
        q = _question()
        paths = {
            "vector": PathResult(hits=("c1",), top_score=0.9),
            "graph": PathResult(hits=(), top_score=None, failure="boom"),
            "wiki": PathResult(hits=("c2", "c1"), top_score=0.3),
        }

        m = evaluate_question(q, paths)

        assert m.per_path["vector"].recall == 0.5
        assert m.per_path["graph"].recall == 0.0  # degraded path = empty hits
        assert m.per_path["wiki"].recall == 1.0
        assert m.per_path["wiki"].mrr == 1.0  # c2 first


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
            evaluate_question(_question(id="q1", category="fact"), {"vector": PathResult(hits=("c1",), top_score=0.9)}),
            evaluate_question(_question(id="q2", category="global", relevant_chunk_ids=()), {"vector": PathResult()}),
        ]

        grouped = aggregate_by_category(results)

        assert set(grouped) == {"fact", "global"}
        assert grouped["fact"].count == 1
        assert grouped["global"].path_accuracy == 0.0


def _agg(recall: float | None, *, hit_rate=0.0, mrr=0.0, path_accuracy=0.0, count=5) -> AggregateMetrics:
    return AggregateMetrics(count=count, hit_rate=hit_rate, recall=recall, mrr=mrr, path_accuracy=path_accuracy)


class TestDiffMetrics:
    def test_deltas_per_scope_and_metric(self):
        before = {"fact": _agg(0.8, hit_rate=0.9)}
        after = {"fact": _agg(0.7, hit_rate=1.0)}

        diff = diff_metrics(before, after)

        by_key = {(d.scope, d.metric): d for d in diff.deltas}
        assert by_key[("fact", "recall")].delta == pytest.approx(-0.1)
        assert by_key[("fact", "hit_rate")].delta == pytest.approx(0.1)
        assert diff.failed is True
        assert any("fact" in f and "recall" in f for f in diff.failures)

    def test_gate_threshold_boundary(self):
        before = {"fact": _agg(0.80)}
        at_threshold = {"fact": _agg(0.77)}
        beyond = {"fact": _agg(0.769)}

        assert diff_metrics(before, at_threshold, fail_threshold=0.03).failed is False
        assert diff_metrics(before, beyond, fail_threshold=0.03).failed is True

    def test_improvement_never_fails(self):
        diff = diff_metrics({"fact": _agg(0.5)}, {"fact": _agg(0.9)})

        assert diff.failed is False
        assert diff.failures == ()

    def test_overall_scope_is_reported_but_not_gated(self):
        before = {"overall": _agg(0.9), "fact": _agg(0.9)}
        after = {"overall": _agg(0.5), "fact": _agg(0.9)}  # overall tanks, categories stable

        diff = diff_metrics(before, after)

        assert diff.failed is False  # spec gates on per-category recall only
        assert any(d.scope == "overall" and d.metric == "recall" for d in diff.deltas)

    def test_scope_only_on_one_side_gets_none_delta(self):
        diff = diff_metrics({"fact": _agg(0.8)}, {"fact": _agg(0.8), "global": _agg(None)})

        global_recall = next(d for d in diff.deltas if d.scope == "global" and d.metric == "recall")
        assert global_recall.delta is None
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
