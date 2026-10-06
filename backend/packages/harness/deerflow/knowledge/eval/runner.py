"""Batch retrieval evaluation runner (spec 2026-08-23 §6).

Fans every golden question out to the three retrieval paths through the same
seam the recall test uses (the online ``_*_impl`` functions, never HTTP), with
the same degradation contract: one path's exception becomes empty hits plus a
failure note and never sinks the run — every run produces a complete report.
Graph-path config parameters mirror ``knowledge_service.recall_test`` wiring so
the evaluation logic stays byte-identical to the online path.

Wiki entries are normalized to their ``source_chunk_ids`` so chunk-level
metrics credit the wiki path fairly; manual cards have no chunk mapping and
are skipped. Pure orchestration lives here; CLI concerns (arg parsing, store
construction) live in ``backend/scripts/run_rag_eval.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.eval.metrics import (
    DEFAULT_FAIL_THRESHOLD,
    PATH_ORDER,
    AggregateMetrics,
    DiffResult,
    QuestionMetrics,
    aggregate,
    aggregate_by_category,
    diff_metrics,
    evaluate_question,
)
from deerflow.knowledge.eval.metrics import (
    PathResult as MetricsPathResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredHit:
    chunk_id: str
    score: float | None = None


#: A searcher answers (query, top_k) with ranked scored hits, or raises —
#: the runner converts exceptions into the degradation contract.
SearchFn = Callable[[str, int], Awaitable[tuple[ScoredHit, ...]]]


@dataclass(frozen=True)
class PathOutcome:
    hits: tuple[ScoredHit, ...] = ()
    failure: str | None = None


@dataclass(frozen=True)
class QuestionReport:
    question: GoldenQuestion
    metrics: QuestionMetrics
    paths: Mapping[str, PathOutcome]


@dataclass(frozen=True)
class EvalReport:
    meta: Mapping[str, Any]
    overall: AggregateMetrics
    by_category: Mapping[str, AggregateMetrics]
    questions: tuple[QuestionReport, ...]
    diff: DiffResult | None

    @property
    def exit_code(self) -> int:
        """0 = pass / no baseline; 1 = regression beyond the fail threshold."""
        return 1 if (self.diff is not None and self.diff.failed) else 0


async def _fanout(question: GoldenQuestion, searchers: Mapping[str, SearchFn], top_k: int) -> dict[str, PathOutcome]:
    async def _guard(fn: SearchFn) -> PathOutcome:
        try:
            return PathOutcome(hits=tuple(await fn(question.query, top_k)))
        except Exception as exc:  # degradation is the contract — one path must not sink the run
            logger.exception("eval path failed for question %s", question.id)
            return PathOutcome(failure=f"{type(exc).__name__}: {exc}")

    outcomes = await asyncio.gather(*(_guard(searchers[path]) for path in PATH_ORDER))
    return dict(zip(PATH_ORDER, outcomes, strict=True))


def _top_score(outcome: PathOutcome) -> float | None:
    return outcome.hits[0].score if outcome.hits else None


async def run_evaluation(
    questions: list[GoldenQuestion],
    searchers: Mapping[str, SearchFn],
    *,
    top_k: int = 5,
    baseline: Mapping[str, Any] | None = None,
    fail_threshold: float = DEFAULT_FAIL_THRESHOLD,
    generated_at: str | None = None,
    progress_hook: Callable[[str, int, int, int], None] | None = None,
) -> EvalReport:
    """Run every question through the three paths and build the report.

    ``baseline`` is a previous ``report_to_dict`` payload; when provided the
    report carries a diff whose gate result drives ``exit_code``.

    ``progress_hook`` (spec 2026-09-06 §9) fires ``(phase, done, failed, total)``
    once per question (phase ``"layer1"``) so the quick tier's progress bar is
    determinate instead of an all-or-nothing segment; ``None`` keeps the CLI
    behavior untouched.
    """
    question_reports: list[QuestionReport] = []
    for question in questions:
        outcomes = await _fanout(question, searchers, top_k)
        path_results = {path: MetricsPathResult(hits=tuple(hit.chunk_id for hit in outcome.hits), top_score=_top_score(outcome), failure=outcome.failure) for path, outcome in outcomes.items()}
        question_reports.append(QuestionReport(question=question, metrics=evaluate_question(question, path_results), paths=outcomes))
        if progress_hook is not None:
            progress_hook("layer1", len(question_reports), 0, len(questions))

    metrics = [report.metrics for report in question_reports]
    overall = aggregate(metrics)
    by_category = aggregate_by_category(metrics)

    diff = None
    if baseline is not None:
        before_overall, before_categories, before_questions = _baseline_parts(baseline)
        before_scopes = dict(before_categories)
        if before_overall is not None:
            before_scopes = {"overall": before_overall, **before_scopes}
        diff = diff_metrics(
            before_scopes,
            {"overall": overall, **dict(by_category)},
            before_questions=before_questions,
            after_questions=metrics,
            fail_threshold=fail_threshold,
        )

    return EvalReport(
        meta={"top_k": top_k, "question_count": len(question_reports), "generated_at": generated_at},
        overall=overall,
        by_category=by_category,
        questions=tuple(question_reports),
        diff=diff,
    )


# ── report (de)serialization ─────────────────────────────────────────────


def _agg_to_dict(agg: AggregateMetrics) -> dict[str, Any]:
    return {"count": agg.count, "hit_rate": agg.hit_rate, "recall": agg.recall, "mrr": agg.mrr, "path_accuracy": agg.path_accuracy}


def _agg_from_dict(data: Mapping[str, Any]) -> AggregateMetrics:
    return AggregateMetrics(
        count=int(data["count"]),
        hit_rate=data.get("hit_rate"),
        recall=data.get("recall"),
        mrr=data.get("mrr"),
        path_accuracy=float(data.get("path_accuracy") or 0.0),
    )


def _diff_to_dict(diff: DiffResult) -> dict[str, Any]:
    return {
        "deltas": [{"scope": d.scope, "metric": d.metric, "before": d.before, "after": d.after, "delta": d.delta} for d in diff.deltas],
        "regressed_questions": list(diff.regressed_questions),
        "failed": diff.failed,
        "failures": list(diff.failures),
    }


def report_to_dict(report: EvalReport) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "meta": dict(report.meta),
        "overall": _agg_to_dict(report.overall),
        "by_category": {scope: _agg_to_dict(agg) for scope, agg in report.by_category.items()},
        "questions": [
            {
                "id": qr.question.id,
                "category": qr.question.category,
                "expected_paths": list(qr.question.expected_paths),
                "actual_path": qr.metrics.actual_path,
                "path_correct": qr.metrics.path_correct,
                "hit": qr.metrics.hit,
                "recall": qr.metrics.recall,
                "mrr": qr.metrics.mrr,
                "paths": {path: {"hits": [{"chunk_id": hit.chunk_id, "score": hit.score} for hit in outcome.hits], "failure": outcome.failure} for path, outcome in qr.paths.items()},
            }
            for qr in report.questions
        ],
        "diff": _diff_to_dict(report.diff) if report.diff is not None else None,
    }


def report_from_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a persisted report (e.g. a baseline file) before reuse."""
    for key in ("overall", "by_category", "questions"):
        if key not in data:
            raise ValueError(f"report payload missing required key: {key}")
    if not isinstance(data["questions"], list):
        raise ValueError("report payload 'questions' must be a list")
    return dict(data)


def _baseline_parts(data: Mapping[str, Any]) -> tuple[AggregateMetrics | None, dict[str, AggregateMetrics], list[QuestionMetrics]]:
    data = report_from_dict(data)
    overall = _agg_from_dict(data["overall"]) if data.get("overall") else None
    categories = {scope: _agg_from_dict(agg) for scope, agg in (data.get("by_category") or {}).items()}
    questions = [
        QuestionMetrics(
            question_id=str(q["id"]),
            category=str(q.get("category") or ""),
            # 双键兼容（§9）：旧 CLI report.json 存单值 ``expected_path``，
            # 新报告存 ``expected_paths`` 列表；diff 只消费 recall，路径键仅透传。
            expected_paths=tuple(q.get("expected_paths") or ([q["expected_path"]] if q.get("expected_path") else [])),
            actual_path=None,
            path_correct=bool(q.get("path_correct")),
            hit=None,
            recall=q.get("recall"),
            mrr=None,
            per_path={},
        )
        for q in data["questions"]
    ]
    return overall, categories, questions


def write_reports(report: EvalReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    json_path.write_text(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


# ── rendering ────────────────────────────────────────────────────────────

_SCOPES_EXCLUDING_GLOBAL = "global"  # global 类单独分区（spec §10 设计意图）


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _summary_rows(report: EvalReport) -> list[tuple[str, AggregateMetrics]]:
    rows = [("overall", report.overall)]
    rows.extend((scope, agg) for scope, agg in report.by_category.items() if scope != _SCOPES_EXCLUDING_GLOBAL)
    return rows


def render_summary(report: EvalReport) -> str:
    """Compact terminal table: one row per scope (global rendered separately)."""
    lines = [f"{'scope':<12} {'count':>5} {'hit_rate':>8} {'recall':>8} {'mrr':>8} {'path_acc':>8}"]
    for scope, agg in _summary_rows(report):
        lines.append(f"{scope:<12} {agg.count:>5} {_fmt(agg.hit_rate):>8} {_fmt(agg.recall):>8} {_fmt(agg.mrr):>8} {_fmt(agg.path_accuracy):>8}")
    if _SCOPES_EXCLUDING_GLOBAL in report.by_category:
        agg = report.by_category[_SCOPES_EXCLUDING_GLOBAL]
        lines.append(f"{_SCOPES_EXCLUDING_GLOBAL:<12} {agg.count:>5} {_fmt(agg.hit_rate):>8} {_fmt(agg.recall):>8} {_fmt(agg.mrr):>8} {_fmt(agg.path_accuracy):>8}  (单独分区，不解读为回退)")
    if report.diff is not None:
        lines.append(f"diff: {'FAILED' if report.diff.failed else 'ok'}; regressed: {', '.join(report.diff.regressed_questions) or '-'}")
    return "\n".join(lines) + "\n"


def render_markdown(report: EvalReport) -> str:
    lines = [
        "# RAG 检索评估报告",
        "",
        f"- top_k: {report.meta.get('top_k')} · 题目数: {report.meta.get('question_count')} · generated_at: {report.meta.get('generated_at') or '-'}",
        "- 阈值均为初始拍值（回退 3%），跑两周后按实际抖动校准（spec §4）",
        "",
        "## 汇总",
        "",
        "| scope | count | hit_rate | recall | mrr | path_acc |",
        "|---|---|---|---|---|---|",
    ]
    for scope, agg in _summary_rows(report):
        lines.append(f"| {scope} | {agg.count} | {_fmt(agg.hit_rate)} | {_fmt(agg.recall)} | {_fmt(agg.mrr)} | {_fmt(agg.path_accuracy)} |")

    if _SCOPES_EXCLUDING_GLOBAL in report.by_category:
        agg = report.by_category[_SCOPES_EXCLUDING_GLOBAL]
        lines += [
            "",
            "## global（主题级问题）",
            "",
            "global 类题目预期大面积失败——这是设计意图：量化「主题级综述检索路」的能力缺口，不解读为回退（spec §10）。",
            "",
            "| scope | count | hit_rate | recall | mrr | path_acc |",
            "|---|---|---|---|---|---|",
            f"| global | {agg.count} | {_fmt(agg.hit_rate)} | {_fmt(agg.recall)} | {_fmt(agg.mrr)} | {_fmt(agg.path_accuracy)} |",
        ]

    if report.diff is not None:
        lines += ["", "## Baseline diff", ""]
        if report.diff.failures:
            lines += ["**门禁失败**：", ""]
            lines += [f"- {failure}" for failure in report.diff.failures]
            lines.append("")
        lines += [
            "| scope | metric | before | after | Δ |",
            "|---|---|---|---|---|",
        ]
        for delta in report.diff.deltas:
            lines.append(f"| {delta.scope} | {delta.metric} | {_fmt(delta.before)} | {_fmt(delta.after)} | {_fmt(delta.delta)} |")
        if report.diff.regressed_questions:
            lines += ["", "### 回退题目详情", ""]
            by_id = {qr.question.id: qr for qr in report.questions}
            for qid in report.diff.regressed_questions:
                qr = by_id.get(qid)
                if qr is None:
                    continue
                expected = ", ".join(qr.question.relevant_chunk_ids) or "(无标注)"
                expected_paths = ", ".join(qr.question.expected_paths)
                lines.append(f"- **{qid}**（{qr.question.category}，预期路径: {expected_paths}）预期命中: {expected}")
                for path in PATH_ORDER:
                    outcome = qr.paths[path]
                    hits = ", ".join(f"{hit.chunk_id}({_fmt(hit.score)})" for hit in outcome.hits) or "(空)"
                    note = f" [失败: {outcome.failure}]" if outcome.failure else ""
                    lines.append(f"  - {path}: {hits}{note}")
    return "\n".join(lines) + "\n"


# ── default searchers (recall_test 同源接线) ─────────────────────────────


def build_default_searchers(
    *,
    kb_id: str,
    user_id: str,
    store: Any,
    vector_store: Any,
    graph_store: Any,
    wiki_store: Any,
    rag: Any = None,
    hybrid_impl: Any = None,
    graph_impl: Any = None,
    wiki_impl: Any = None,
) -> dict[str, SearchFn]:
    """Wire the three online ``_*_impl`` functions as searchers.

    Mirrors ``knowledge_service.recall_test``: the graph path receives the same
    config-driven parameters, and the eval ``top_k`` maps to ``evidence_limit``
    exactly like the recall test. Impl parameters are injectable for tests.
    """
    if rag is None:
        from deerflow.config.app_config import get_app_config

        rag = get_app_config().rag
    if hybrid_impl is None:
        from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl as hybrid_impl
    if graph_impl is None:
        from deerflow.tools.builtins.graph_search_tool import _graph_search_impl as graph_impl
    if wiki_impl is None:
        from deerflow.tools.builtins.wiki_search_tool import _wiki_search_impl as wiki_impl

    runtime = SimpleNamespace(context={"kb_id": kb_id, "user_id": user_id})

    async def vector_fn(query: str, top_k: int) -> tuple[ScoredHit, ...]:
        raw = await hybrid_impl(query, runtime, store=store, vector_store=vector_store, top_k=top_k)
        return tuple(ScoredHit(item["chunk_id"], item.get("score")) for item in raw.get("results", []))

    async def graph_fn(query: str, top_k: int) -> tuple[ScoredHit, ...]:
        reranker = None
        if rag.graph_rerank:
            from deerflow.knowledge.reranker_factory import build_reranker

            reranker = build_reranker()
        raw = await graph_impl(
            query,
            runtime,
            store=store,
            graph_store=graph_store,
            vector_store=vector_store,
            reranker=reranker,
            per_entity_cap=rag.graph_per_entity_cap,
            per_edge_cap=rag.graph_per_edge_cap,
            hop0_guarantee=rag.graph_hop0_guarantee,
            evidence_limit=top_k,  # recall_test 同源：top_k 映射为 evidence_limit
            graph_rerank=rag.graph_rerank,
            rerank_threshold=rag.graph_rerank_threshold,
            hop_penalty=rag.graph_hop_penalty,
            neighbor_min_score=rag.graph_neighbor_min_score,
            max_expanded_nodes=rag.graph_max_expanded_nodes,
            hub_degree_threshold=rag.graph_hub_degree_threshold,
        )
        return tuple(ScoredHit(item["chunk_id"], item.get("score")) for item in raw.get("evidence", []))

    async def wiki_fn(query: str, top_k: int) -> tuple[ScoredHit, ...]:
        raw = await wiki_impl(query, runtime, store=store, wiki_store=wiki_store, vector_store=vector_store, top_k=top_k)
        hits: list[ScoredHit] = []
        seen: set[str] = set()
        for entry in raw.get("entries", []):
            if entry.get("source_type") != "wiki":
                continue  # 人工卡片无 chunk 映射，跳过
            stored = await wiki_store.get_entry(entry["entry_id"])
            for chunk_id in (stored or {}).get("source_chunk_ids") or []:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    hits.append(ScoredHit(chunk_id, entry.get("score")))
        return tuple(hits)

    return {"vector": vector_fn, "graph": graph_fn, "wiki": wiki_fn}
