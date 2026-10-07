"""Deterministic IR metrics for retrieval evaluation (spec 2026-08-23 §6).

Pure functions, no IO. Chunk-level metrics (hit / recall@k / MRR) are computed
against the union of the retrieval paths' top-k hits — the question is whether
*the system* surfaced the annotated chunk — while the per-path breakdown stays
available for drill-down. Path selection compares each path's top-1 score. The
baseline diff gates on per-category recall drops only (``overall`` is reported
but never gates), per the spec's门禁语义.

The first-phase slice runs the one retrieval tool (vector path), so
``PATH_ORDER`` is the single-element ("vector",); the precedence/tie logic and
the per-path shape stay untouched so the machinery keeps working unchanged the
day a second path returns.

Path correctness uses set membership (spec 2026-08-28 §4): a question carries
``expected_paths`` and the run is correct when the actual winning path is any
member of that set — "any of these paths answering counts", deliberately NOT
"all of them must fire". Single-path questions are the one-element special
case, bit-identical to the legacy equality judgement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from deerflow_knowledge.eval.dataset import GoldenQuestion

#: Fixed precedence when path top-1 scores tie (deterministic reports).
#: First-phase slice: the vector path is the only retrieval path.
PATH_ORDER = ("vector",)

#: Tolerance for the regression-gate comparison: 0.80 - 0.77 exceeds 0.03 in
#: binary floating point, so the gate compares against threshold + epsilon.
_GATE_EPS = 1e-9

#: Default per-category recall regression gate (initial guess, recalibrate
#: after two weeks of observed jitter — spec §4).
DEFAULT_FAIL_THRESHOLD = 0.03


@dataclass(frozen=True)
class PathResult:
    """One retrieval path's outcome for one question (runner supplies these)."""

    hits: tuple[str, ...] = ()
    top_score: float | None = None
    failure: str | None = None


@dataclass(frozen=True)
class PathMetrics:
    hit: float | None
    recall: float | None
    mrr: float | None


@dataclass(frozen=True)
class QuestionMetrics:
    question_id: str
    category: str
    expected_paths: tuple[str, ...]
    actual_path: str | None
    path_correct: bool
    hit: float | None
    recall: float | None
    mrr: float | None
    per_path: Mapping[str, PathMetrics]


@dataclass(frozen=True)
class AggregateMetrics:
    count: int
    hit_rate: float | None
    recall: float | None
    mrr: float | None
    path_accuracy: float


@dataclass(frozen=True)
class MetricDelta:
    scope: str
    metric: str
    before: float | None
    after: float | None
    delta: float | None


@dataclass(frozen=True)
class DiffResult:
    deltas: tuple[MetricDelta, ...]
    regressed_questions: tuple[str, ...]
    failed: bool
    failures: tuple[str, ...]


def recall_at_k(relevant: Iterable[str], hits: Sequence[str]) -> float | None:
    """Share of relevant chunk ids present in the top-k hits."""
    relevant = set(relevant)
    if not relevant:
        return None
    return len(relevant & set(hits)) / len(relevant)


def hit(relevant: Iterable[str], hits: Sequence[str]) -> float | None:
    """1.0 when any relevant chunk id appears in the top-k hits."""
    relevant = set(relevant)
    if not relevant:
        return None
    return 1.0 if relevant & set(hits) else 0.0


def reciprocal_rank(relevant: Iterable[str], hits: Sequence[str]) -> float | None:
    """Reciprocal rank of the first relevant hit; 0.0 when none appears."""
    relevant = set(relevant)
    if not relevant:
        return None
    for rank, chunk_id in enumerate(hits, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def choose_path(paths: Mapping[str, PathResult]) -> str | None:
    """Pick the path with the highest top-1 score; ties follow PATH_ORDER.

    Paths without hits (including degraded/failed paths) never win. Returns
    None when no path produced any hit.
    """
    best: str | None = None
    best_score = float("-inf")
    for path in PATH_ORDER:
        result = paths.get(path)
        if result is None or not result.hits:
            continue
        score = result.top_score if result.top_score is not None else 0.0
        if score > best_score:
            best, best_score = path, score
    return best


def evaluate_question(question: GoldenQuestion, paths: Mapping[str, PathResult]) -> QuestionMetrics:
    """Evaluate one question against the retrieval paths' results.

    Chunk metrics use the union of all paths' hits (MRR takes the best rank
    across lists); per-path metrics are kept for drill-down. Questions without
    annotated chunks skip chunk metrics (None) but still judge path selection.
    """
    relevant = set(question.relevant_chunk_ids)
    union_hits: set[str] = set()
    per_path: dict[str, PathMetrics] = {}
    best_rr = 0.0
    for path in PATH_ORDER:
        result = paths.get(path, PathResult())
        union_hits |= set(result.hits)
        per_path[path] = PathMetrics(
            hit=hit(relevant, result.hits),
            recall=recall_at_k(relevant, result.hits),
            mrr=reciprocal_rank(relevant, result.hits),
        )
        if relevant and result.hits:
            best_rr = max(best_rr, reciprocal_rank(relevant, result.hits) or 0.0)

    actual = choose_path(paths)
    return QuestionMetrics(
        question_id=question.id,
        category=question.category,
        expected_paths=question.expected_paths,
        actual_path=actual,
        # Set membership, not equality: any expected path winning counts
        # (spec 2026-08-28 §4). One-element sets keep legacy behaviour.
        path_correct=actual is not None and actual in question.expected_paths,
        hit=hit(relevant, union_hits) if relevant else None,
        recall=recall_at_k(relevant, union_hits),
        mrr=best_rr if relevant else None,
        per_path=per_path,
    )


def _mean(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def aggregate(results: Iterable[QuestionMetrics]) -> AggregateMetrics:
    """Aggregate question metrics; None values (no annotated chunks) skip means."""
    results = list(results)
    return AggregateMetrics(
        count=len(results),
        hit_rate=_mean(r.hit for r in results),
        recall=_mean(r.recall for r in results),
        mrr=_mean(r.mrr for r in results),
        path_accuracy=sum(1.0 for r in results if r.path_correct) / len(results) if results else 0.0,
    )


def aggregate_by_category(results: Iterable[QuestionMetrics]) -> dict[str, AggregateMetrics]:
    grouped: dict[str, list[QuestionMetrics]] = {}
    for result in results:
        grouped.setdefault(result.category, []).append(result)
    return {category: aggregate(items) for category, items in grouped.items()}


def diff_metrics(
    before: Mapping[str, AggregateMetrics],
    after: Mapping[str, AggregateMetrics],
    *,
    before_questions: Iterable[QuestionMetrics] = (),
    after_questions: Iterable[QuestionMetrics] = (),
    fail_threshold: float = DEFAULT_FAIL_THRESHOLD,
) -> DiffResult:
    """Diff two aggregated reports and apply the per-category recall gate.

    Deltas cover every scope on either side (overall first). Only per-category
    recall drops beyond ``fail_threshold`` fail the gate — ``overall`` and
    other metrics are reported but never gate (spec §4/§6).
    """
    scopes = sorted(set(before) | set(after), key=lambda s: (s != "overall", s))
    deltas: list[MetricDelta] = []
    failures: list[str] = []
    for scope in scopes:
        b = before.get(scope)
        a = after.get(scope)
        for metric in ("hit_rate", "recall", "mrr", "path_accuracy"):
            bv = getattr(b, metric) if b else None
            av = getattr(a, metric) if a else None
            delta = av - bv if bv is not None and av is not None else None
            deltas.append(MetricDelta(scope=scope, metric=metric, before=bv, after=av, delta=delta))
        if scope != "overall" and b is not None and a is not None and b.recall is not None and a.recall is not None and b.recall - a.recall > fail_threshold + _GATE_EPS:
            failures.append(f"category '{scope}' recall dropped {b.recall - a.recall:.1%} (> {fail_threshold:.1%})")

    before_by_id = {q.question_id: q for q in before_questions}
    regressed = []
    for q in after_questions:
        prev = before_by_id.get(q.question_id)
        if prev is None or prev.recall is None or q.recall is None:
            continue
        if q.recall < prev.recall:
            regressed.append(q.question_id)

    return DiffResult(
        deltas=tuple(deltas),
        regressed_questions=tuple(sorted(regressed)),
        failed=bool(failures),
        failures=tuple(failures),
    )
