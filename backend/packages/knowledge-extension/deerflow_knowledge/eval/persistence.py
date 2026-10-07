"""eval_runs persistence for the two evaluation CLIs (spec 2026-08-24 §3.1, plan Task 0b).

One row per CLI run: ``run_rag_eval.py`` writes ``layer1_metrics`` (Layer 2
stays ``{}``), ``run_ragas_eval.py`` writes ``layer2_metrics`` (Layer 1 stays
``{}``); an empty object means "this layer did not run". skipped/error runs
are persisted too — they record *when an evaluation was attempted* — but stay
out of the latest/trend read sets (§4.2).

The report→JSON field mappings (§3.1.2) are pure functions so they are
directly unit-testable; ``save_eval_run`` performs the single-row insert.
Engine lifecycle stays with the caller (the CLIs reuse their existing
``init_engine_from_config`` section).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from deerflow.persistence.engine import get_session_factory
from deerflow_knowledge.eval.dataset import GoldenQuestion
from deerflow_knowledge.eval.metrics import (
    _GATE_EPS,  # same-package: keeps the regressed-category list on the exact gate semantics
    DEFAULT_FAIL_THRESHOLD,
)
from deerflow_knowledge.models import EvalRunRow

logger = logging.getLogger(__name__)

#: eval_runs.status values (§3.1.1).
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

#: eval_runs.environment values (§3.1.1 v3), written since migration 0018.
ENV_LOCAL = "local"
ENV_CI = "ci"
ENV_NIGHTLY = "nightly"
ENVIRONMENTS: tuple[str, ...] = (ENV_LOCAL, ENV_CI, ENV_NIGHTLY)


def generate_run_id() -> str:
    """run_id ``rag-<UTC 秒>-<hex8>``——CLI 与 gateway 按需运行共用同一格式。

    Originally the CLI's private ``_generate_run_id``; lifted into the eval
    package so on-demand runs (spec 2026-08-27 §5) cannot drift from it.
    """

    from uuid import uuid4

    return f"rag-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def status_from_exit_code(exit_code: int) -> str:
    """Map a CLI exit code to eval_runs.status.

    exit 0/1 → ``completed`` — a Layer 1 regression red (exit 1) is still a
    completed run: the gate signal lives in ``baseline_diff`` and the trend
    chart needs the regression run's data point. exit 2 → ``error``,
    exit 3 → ``skipped``.
    """

    if exit_code in (0, 1):
        return STATUS_COMPLETED
    if exit_code == 2:
        return STATUS_ERROR
    return STATUS_SKIPPED


def resolve_environment(explicit: str | None, environ: Mapping[str, str]) -> str:
    """Resolve the run's environment (§3.1.1 v3).

    ``--environment`` wins when given explicitly; otherwise ``CI=true`` in the
    process environment means ``ci``; everything else is ``local``. Nightly
    runs pass ``--environment nightly`` explicitly.
    """

    if explicit:
        return explicit
    if environ.get("CI") == "true":
        return ENV_CI
    return ENV_LOCAL


def _layer1_scope(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """One Layer 1 scope (overall or category): report keys → stored keys."""
    return {
        "hit_rate": metrics.get("hit_rate"),
        "recall_at_k": metrics.get("recall"),
        "mrr": metrics.get("mrr"),
        "path_accuracy": metrics.get("path_accuracy"),
        "question_count": metrics.get("count"),
    }


def layer1_metrics_from_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Layer 1 report (``runner.report_to_dict`` payload) → ``layer1_metrics`` JSON.

    ``overall`` → ``summary`` (with ``recall`` → ``recall_at_k`` and
    ``count`` → ``question_count``); ``by_category`` categories pass through as
    top-level dynamic keys — only the categories present in the batch appear.
    ``questions`` carries a per-question slim array (id/recall/hit/
    path_correct/actual_path) for the question-bank triage column — the
    full per-path hit detail stays out of eval_runs on purpose. ``top_k``
    passes the run's retrieval depth through as a scalar so column headers
    can render ``召回率@5`` instead of a symbolic k; being a scalar (not a
    Mapping) it never enters ``baseline_report_from_metrics``'s category
    reconstruction. Runs saved before these keys existed simply lack them;
    readers treat them as optional.
    """

    result: dict[str, Any] = {"summary": _layer1_scope(report["overall"])}
    for category, metrics in (report.get("by_category") or {}).items():
        result[category] = _layer1_scope(metrics)
    result["questions"] = [
        {
            "id": question.get("id"),
            "recall": question.get("recall"),
            "hit": question.get("hit"),
            "path_correct": question.get("path_correct"),
            "actual_path": question.get("actual_path"),
        }
        for question in (report.get("questions") or [])
        if isinstance(question, Mapping)
    ]
    top_k = (report.get("meta") or {}).get("top_k")
    if top_k is not None:
        result["top_k"] = top_k
    return result


def layer2_metrics_from_report(report: Mapping[str, Any], *, questions: Sequence[GoldenQuestion]) -> dict[str, Any]:
    """Layer 2 report (``ragas_eval.report_to_dict`` payload) → ``layer2_metrics`` JSON.

    ``aggregate.ragas`` passes through (NaN already normalized to None);
    the architecture-specific metrics nest under ``arch_specific`` with
    ``graph_entity_hit_rate`` → ``seed_hit_rate``. ``has_graph_questions`` is
    computed at save time from the evaluated batch (``any(q.relevant_entities)``)
    and decides whether the seed_hit_rate card renders.
    """

    aggregate = report["aggregate"]
    return {
        "ragas": dict(aggregate.get("ragas") or {}),
        "arch_specific": {
            "citation_precision": aggregate.get("citation_precision"),
            "citation_recall": aggregate.get("citation_recall"),
            "seed_hit_rate": aggregate.get("graph_entity_hit_rate"),
        },
        # Real-conversation-chain path accuracy (口径 differs from Layer 1's
        # same-named metric) — surfaced in the run detail drawer.
        "path_accuracy": aggregate.get("path_accuracy"),
        "ragas_available": bool(report.get("ragas_available")),
        "ragas_skip_reason": report.get("ragas_skip_reason"),
        "has_graph_questions": any(q.relevant_entities for q in questions),
    }


def baseline_diff_from_report(report: Mapping[str, Any], *, fail_threshold: float = DEFAULT_FAIL_THRESHOLD) -> dict[str, Any] | None:
    """Layer 1 report ``diff`` → ``baseline_diff`` column payload.

    ``None`` when the run carried no baseline. ``regressed_categories`` mirrors
    the CI gate exactly: per-category recall drops beyond ``fail_threshold``
    (overall never gates, other metrics never gate).
    """

    diff = report.get("diff")
    if diff is None:
        return None
    recall_at_k_delta: float | None = None
    regressed_categories: list[str] = []
    for delta in diff.get("deltas") or []:
        if delta.get("metric") != "recall":
            continue
        scope = delta.get("scope")
        if scope == "overall":
            recall_at_k_delta = delta.get("delta")
            continue
        before, after = delta.get("before"), delta.get("after")
        if before is not None and after is not None and before - after > fail_threshold + _GATE_EPS:
            regressed_categories.append(scope)
    return {
        "recall_at_k_delta": recall_at_k_delta,
        "regression_detected": bool(diff.get("failed")),
        "threshold_percent": fail_threshold * 100,
        "regressed_categories": regressed_categories,
    }


def baseline_report_from_metrics(layer1_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Stored ``layer1_metrics`` (§3.1.2 shape) → runner baseline report payload.

    Reverses the save-time mapping (``summary`` → ``overall``,
    ``recall_at_k`` → ``recall``, ``question_count`` → ``count``) so
    ``--baseline auto`` diffs against the persisted baseline row through the
    exact same code path as a file baseline. Per-question detail is not
    persisted in eval_runs, so ``questions`` is empty: the diff's
    ``regressed_questions`` list comes out empty while the per-category /
    overall gates work on full data.
    """

    def _scope(metrics: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "count": metrics.get("question_count"),
            "hit_rate": metrics.get("hit_rate"),
            "recall": metrics.get("recall_at_k"),
            "mrr": metrics.get("mrr"),
            "path_accuracy": metrics.get("path_accuracy"),
        }

    return {
        "schema_version": 1,
        "meta": {},
        "overall": _scope(layer1_metrics.get("summary") or {}),
        "by_category": {key: _scope(value) for key, value in layer1_metrics.items() if key != "summary" and isinstance(value, Mapping)},
        "questions": [],
        "diff": None,
    }


async def save_eval_run(
    *,
    run_id: str,
    kb_id: str,
    status: str,
    created_at: datetime,
    layer1_metrics: Mapping[str, Any] | None = None,
    layer2_metrics: Mapping[str, Any] | None = None,
    completed_at: datetime | None = None,
    langfuse_trace_url: str | None = None,
    baseline_diff: Mapping[str, Any] | None = None,
    environment: str = ENV_LOCAL,
    mark_baseline: bool = False,
) -> str | None:
    """Insert one eval_runs row; returns ``run_id``.

    Returns ``None`` when the persistence engine is not initialized (memory
    backend) — the eval CLI output contract never depends on persistence.
    ``created_at`` is always supplied explicitly (the report's
    ``generated_at``; §3.1.1 single-clock rule), never the DB default.

    ``mark_baseline`` clears the KB's previous baseline marker and sets the
    new one in the same transaction (§3.1.3: code-level guarantee, with the
    ``uq_eval_runs_kb_baseline`` partial unique index as the DB backstop).
    Completed-only gating: it takes effect for ``status=completed`` runs only
    (exit 0/1 — a regression-red run is still completed and may be marked,
    its gate signal lives in ``baseline_diff``); error/skipped runs ignore it
    with a warning and leave the previous marker untouched.
    """

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("eval run %s not persisted: persistence engine not initialized", run_id)
        return None
    if mark_baseline and status != STATUS_COMPLETED:
        # §3.1.3 completed 门控：失败运行不得成为基线，更不能在同一事务里
        # 清掉现有的好基线——否则一次失败的评估会静默抹掉 baseline。
        logger.warning("eval run %s: --mark-baseline ignored (status=%s; only completed runs can become the KB baseline)", run_id, status)
        mark_baseline = False
    row = EvalRunRow(
        id=run_id,
        kb_id=kb_id,
        status=status,
        layer1_metrics=dict(layer1_metrics or {}),
        layer2_metrics=dict(layer2_metrics or {}),
        created_at=created_at,
        completed_at=completed_at,
        langfuse_trace_url=langfuse_trace_url,
        baseline_diff=dict(baseline_diff) if baseline_diff is not None else None,
        environment=environment,
        is_baseline=mark_baseline,
    )
    async with session_factory() as session:
        if mark_baseline:
            # Same transaction: clear the KB's previous marker BEFORE the
            # insert so the partial unique index never sees two true rows.
            await session.execute(update(EvalRunRow).where(EvalRunRow.kb_id == kb_id, EvalRunRow.is_baseline.is_(True)).values(is_baseline=False))
        session.add(row)
        await session.commit()
    return run_id


async def get_baseline_run(kb_id: str) -> EvalRunRow | None:
    """Return the KB's marked baseline row (``is_baseline = true``), if any.

    Returns ``None`` when the persistence engine is not initialized (memory
    backend) — ``--baseline auto`` then falls back to a no-diff run.
    """

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("baseline lookup for kb %s skipped: persistence engine not initialized", kb_id)
        return None
    async with session_factory() as session:
        result = await session.execute(select(EvalRunRow).where(EvalRunRow.kb_id == kb_id, EvalRunRow.is_baseline.is_(True)))
        return result.scalar_one_or_none()
