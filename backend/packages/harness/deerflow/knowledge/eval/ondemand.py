"""On-demand evaluation runner triggered from the gateway (spec 2026-08-27 §5 + 2026-09-01 B 方案).

Mirrors the CLI orchestration in ``scripts/run_rag_eval.py`` (load golden →
searchers → ``run_evaluation`` → report mapping → ``save_eval_run``) but runs
in-process: the gateway already initialized the persistence engine and store
singletons, so there is no engine lifecycle here and no CLI subprocess.

Contracts frozen by the spec:

- **Two tiers** — ``run_layer1_for_kb`` stays Layer 1 only (fast, cheap);
  ``run_full_eval_for_kb`` adds the judge-backed Layer 2 over the same
  question set and persists BOTH layers on one row (history badge "L1+L2").
- **Question selection** — ``question_ids`` filters the bank before either
  pass; an empty post-filter set raises like an empty bank.
- **Idempotent trigger** — a per-KB module-level ``_IN_FLIGHT`` counter (same
  single-process pattern as wiki ``generator._IN_FLIGHT``); the decrement sits
  in ``finally`` so a crashed run never wedges future triggers.
- **Auto baseline diff** — every run diffs against the KB's marked baseline
  row when present (CLI ``--baseline auto`` semantics), so regression badges
  work identically for UI-triggered runs.
- **Best-effort error rows** — any runtime failure logs and persists an
  ``error`` row instead of propagating out of the fire-and-forget task;
  an empty/missing question bank is different: it raises
  :class:`EvalQuestionBankEmpty` *before* scheduling meaningfully starts and
  persists nothing. A full run whose Layer 2 stage crashes keeps the Layer 1
  results (completed row, layer2 empty) — never loses the cheap half.

The default searcher construction resolves the KB owner through the store
(exactly like the CLI); tests inject ``searchers``/``agent_runner`` directly
to exercise the orchestration without real retrieval impls or agent runs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.eval.persistence import (
    ENV_LOCAL,
    baseline_diff_from_report,
    baseline_report_from_metrics,
    generate_run_id,
    get_baseline_run,
    layer1_metrics_from_report,
    layer2_metrics_from_report,
    save_eval_run,
)
from deerflow.knowledge.eval.question_bank import load_questions
from deerflow.knowledge.eval.ragas_eval import report_to_dict as layer2_report_to_dict
from deerflow.knowledge.eval.ragas_eval import run_layer2_evaluation
from deerflow.knowledge.eval.runner import SearchFn, build_default_searchers, report_to_dict, run_evaluation

logger = logging.getLogger(__name__)

#: In-flight runs per KB (single-process asyncio counter) — feeds both the
#: trigger idempotency check and the history endpoint's ``in_flight`` flag.
_IN_FLIGHT: dict[str, int] = {}

#: Live progress per KB (spec 2026-09-06 run-progress) — mirrors the
#: ``_IN_FLIGHT`` single-process pattern: set when a run starts, updated via
#: the Layer 2 progress hook, popped in ``finally`` so a crashed run never
#: leaves a phantom entry. Contract keys (spec §3, extended by §9):
#: ``run_id / phase / done / total / failed / started_at / updated_at`` plus
#: ``phase_started_at / phase_durations / tail`` (the weighted progress bar's
#: duration source and the single-line UI log event).
_PROGRESS: dict[str, dict[str, object]] = {}

#: In-flight run tasks per KB (spec 2026-09-06 §11) — the cancellation handle
#: registry: runners self-register ``asyncio.current_task()`` on their first
#: line (same vocabulary as the ``_IN_FLIGHT`` synchronous increment) and pop
#: in ``finally``; ``cancel_eval_run`` cancels the parked task from anywhere.
_TASKS: dict[str, asyncio.Task] = {}

#: Layer 2 progress hook signature: ``(phase, done, failed, total)``.
ProgressHook = Callable[[str, int, int, int], None]


class EvalQuestionBankEmpty(RuntimeError):
    """The KB's golden bank is missing or has zero questions."""


def eval_run_in_progress(kb_id: str) -> bool:
    """True while any on-demand run for the KB is active."""
    return _IN_FLIGHT.get(kb_id, 0) > 0


def cancel_eval_run(kb_id: str) -> bool:
    """Cancel the KB's in-flight on-demand run; ``False`` when none (spec §11).

    ``task.cancel()`` injects ``CancelledError`` at the runner's nearest await
    point — the whole chain is await points (search fanout / agent turns /
    judge HTTP / ragas executor), so in-flight calls abort immediately; the
    runner's ``except asyncio.CancelledError`` persists the cancelled row.
    """
    task = _TASKS.get(kb_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def get_eval_progress(kb_id: str) -> dict[str, object] | None:
    """Snapshot of the KB's live run progress, or ``None`` when idle.

    Returns a copy (nested ``phase_durations`` / ``tail`` included) so API
    callers can never mutate the registry. All writes happen on the event loop
    between awaits, except the ragas job callback which fires from the worker
    thread — either way a plain dict write is atomic under the GIL (same
    consistency model as ``_IN_FLIGHT``).
    """

    entry = _PROGRESS.get(kb_id)
    if entry is None:
        return None
    snapshot = dict(entry)
    snapshot["phase_durations"] = dict(entry.get("phase_durations") or {})
    snapshot["tail"] = dict(entry.get("tail") or {})
    # 旧形状条目兼容：phase_started_at 缺失时回退到 started_at，保证前端恒拿到十键。
    snapshot.setdefault("phase_started_at", entry.get("started_at"))
    return snapshot


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _now_iso_ms() -> str:
    """Millisecond clock for phase timing — second resolution is too coarse for the fast layer1 phase."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _elapsed_seconds(start_iso: str, end_iso: str) -> float:
    """Seconds between two registry timestamps; never negative, 0.0 on malformed input."""
    try:
        delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    except ValueError:
        return 0.0
    return max(delta.total_seconds(), 0.0)


def _progress_start(kb_id: str, run_id: str, *, phase: str, total: int) -> None:
    """Register a fresh run at phase start (done=0, failed=0)."""
    now = _now_iso()
    started_ms = _now_iso_ms()
    _PROGRESS[kb_id] = {
        "run_id": run_id,
        "phase": phase,
        "done": 0,
        "total": total,
        "failed": 0,
        "started_at": now,
        "updated_at": now,
        "phase_started_at": started_ms,
        "phase_durations": {},
        "tail": {"kind": "phase", "phase": phase, "done": 0, "total": total, "failed": 0},
    }


def _progress_update(kb_id: str, *, phase: str, done: int, failed: int, total: int) -> None:
    """Advance the KB's live progress; a no-op when the entry is already gone.

    A phase transition settles the outgoing phase's measured duration (the
    frontend's weight-adaptation source) and stamps a structured ``tail`` event
    — the UI renders the sentence per locale, so the backend never ships copy.
    """
    entry = _PROGRESS.get(kb_id)
    if entry is None:
        return
    now = _now_iso()
    previous = entry.get("phase")
    durations = dict(entry.get("phase_durations") or {})
    switched = previous != phase
    if switched:
        durations[str(previous)] = _elapsed_seconds(str(entry.get("phase_started_at") or now), _now_iso_ms())
        kind = "phase"
    elif failed > int(entry.get("failed") or 0):
        kind = "fail"
    else:
        kind = "item"
    entry.update(
        {
            "phase": phase,
            "done": done,
            "failed": failed,
            "total": total,
            "updated_at": now,
            "phase_started_at": _now_iso_ms() if switched else entry.get("phase_started_at"),
            "phase_durations": durations,
            "tail": {"kind": kind, "phase": phase, "done": done, "total": total, "failed": failed},
        }
    )


def _release_run(kb_id: str) -> None:
    """Decrement ``_IN_FLIGHT`` and drop ``_PROGRESS`` when the KB goes idle.

    Shared by both runners' ``finally`` blocks: the progress entry only ever
    belongs to the in-flight run (the trigger is idempotent per KB), so it is
    popped exactly when the counter hits zero.
    """
    remaining = _IN_FLIGHT.get(kb_id, 0) - 1
    if remaining > 0:
        _IN_FLIGHT[kb_id] = remaining
    else:
        _IN_FLIGHT.pop(kb_id, None)
        _PROGRESS.pop(kb_id, None)


def _filter_questions(questions: Sequence[GoldenQuestion], question_ids: Collection[str] | None) -> list[GoldenQuestion]:
    """选题过滤（``None`` = 全量）；过滤后为空集由调用方按空题库语义处理。"""
    if question_ids is None:
        return list(questions)
    wanted = set(question_ids)
    return [question for question in questions if question.id in wanted]


async def _layer1_report_payload(
    kb_id: str,
    *,
    questions: Sequence[GoldenQuestion],
    top_k: int,
    searchers: Mapping[str, SearchFn] | None,
    generated_at: str,
    progress_hook: ProgressHook | None = None,
) -> dict:
    """Layer 1 执行链（不写库，两条路径共用）：searcher → baseline → run_evaluation → dict。"""
    effective_searchers = searchers if searchers is not None else await _build_default_searchers(kb_id)
    baseline_report = None
    baseline_row = await get_baseline_run(kb_id)
    if baseline_row is not None and baseline_row.layer1_metrics:
        baseline_report = baseline_report_from_metrics(baseline_row.layer1_metrics)
    report = await run_evaluation(questions, effective_searchers, top_k=top_k, baseline=baseline_report, generated_at=generated_at, progress_hook=progress_hook)
    return report_to_dict(report)


async def run_layer1_for_kb(
    kb_id: str,
    *,
    golden_path: str | Path,
    top_k: int = 5,
    searchers: Mapping[str, SearchFn] | None = None,
    question_ids: Collection[str] | None = None,
    generated_at: str | None = None,
) -> str:
    """Run one deterministic evaluation pass for the KB; returns the run_id.

    Never raises after the empty-bank guard: runtime failures are swallowed
    into an ``error`` eval_runs row (the fire-and-forget task must be safe).
    """

    run_id = generate_run_id()
    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    # 同步自增在途计数（runner 第一行、先于任何 await）：create_task 调度后即生效，
    # 关闭"触发后早期 poll 读到 in_flight=false → 覆盖前端乐观值、杀死轮询"的竞态。
    _IN_FLIGHT[kb_id] = _IN_FLIGHT.get(kb_id, 0) + 1
    # 终止句柄自注册（spec §11）：与计数同词汇同位置；直接 await（非 task）调用时
    # current_task 为 None，跳过注册（取消仅对在飞 task 有意义）。
    _current = asyncio.current_task()
    if _current is not None:
        _TASKS[kb_id] = _current
    questions = _filter_questions(await load_questions(golden_path), question_ids)
    if not questions:
        _TASKS.pop(kb_id, None)
        _release_run(kb_id)
        raise EvalQuestionBankEmpty(f"eval question bank is empty: {golden_path}")

    # layer1 段逐题上报（spec §9）：total = 题数，快速档的条才是定长的。
    _progress_start(kb_id, run_id, phase="layer1", total=len(questions))

    def _forward_layer1(phase: str, done: int, failed: int, total: int) -> None:
        _progress_update(kb_id, phase=phase, done=done, failed=failed, total=total)

    try:
        payload = await _layer1_report_payload(kb_id, questions=questions, top_k=top_k, searchers=searchers, generated_at=generated_at, progress_hook=_forward_layer1)
        await save_eval_run(
            run_id=run_id,
            kb_id=kb_id,
            status="completed",
            created_at=datetime.fromisoformat(generated_at),
            completed_at=datetime.now(UTC),
            layer1_metrics=layer1_metrics_from_report(payload),
            baseline_diff=baseline_diff_from_report(payload),
            environment=ENV_LOCAL,
        )
        return run_id
    except asyncio.CancelledError:
        # 终止（spec §11）：落 cancelled 行（layer1 未跑完 → 无指标）后重抛。
        await _save_cancelled_row(run_id=run_id, kb_id=kb_id, created_at=datetime.fromisoformat(generated_at))
        raise
    except Exception:
        logger.exception("on-demand eval run %s failed for kb %s", run_id, kb_id)
        await _save_error_row(run_id=run_id, kb_id=kb_id, created_at=datetime.fromisoformat(generated_at))
        return run_id
    finally:
        _TASKS.pop(kb_id, None)
        _release_run(kb_id)


async def run_full_eval_for_kb(
    kb_id: str,
    *,
    golden_path: str | Path,
    top_k: int = 5,
    searchers: Mapping[str, SearchFn] | None = None,
    question_ids: Collection[str] | None = None,
    agent_runner=None,
    judge_llm=None,
    ragas_evaluator=None,
    generated_at: str | None = None,
) -> str:
    """Layer 1 + Layer 2 完整评测，单行写双层指标（历史徽标 "L1+L2"）。

    Layer 2 依赖（agent runner / judge / ragas）未注入时走生产装配（
    ``_build_layer2_deps``，与 CLI 口径一致）；测试直接注入假件。L2 阶段
    整体异常降级为仅 L1 的 completed 行——廉价层的成果永不丢失。
    """

    run_id = generate_run_id()
    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    # 同步自增在途计数（runner 第一行、先于任何 await）：同 run_layer1_for_kb，
    # 关闭触发后早期 poll 读到 in_flight=false 的竞态窗口。
    _IN_FLIGHT[kb_id] = _IN_FLIGHT.get(kb_id, 0) + 1
    # 终止句柄自注册（spec §11）：同 run_layer1_for_kb。
    _current = asyncio.current_task()
    if _current is not None:
        _TASKS[kb_id] = _current
    questions = _filter_questions(await load_questions(golden_path), question_ids)
    if not questions:
        _TASKS.pop(kb_id, None)
        _release_run(kb_id)
        raise EvalQuestionBankEmpty(f"eval question bank is empty: {golden_path}")

    # layer1 段逐题上报（spec §9）：与快速档同款，total = 题数。
    _progress_start(kb_id, run_id, phase="layer1", total=len(questions))

    def _forward_progress(phase: str, done: int, failed: int, total: int) -> None:
        # Layer 1/2 hook → 注册表：三段均定长计数（layer1 逐题、questions 逐题、
        # ragas 逐 job + 逐题 judge）。
        _progress_update(kb_id, phase=phase, done=done, failed=failed, total=total)

    # layer1 指标在 try 外初始化：CancelledError 分支要带已跑完的廉价层成果。
    layer1_metrics: Mapping[str, object] | None = None
    try:
        payload = await _layer1_report_payload(kb_id, questions=questions, top_k=top_k, searchers=searchers, generated_at=generated_at, progress_hook=_forward_progress)
        layer1_metrics = layer1_metrics_from_report(payload)
        baseline_diff = baseline_diff_from_report(payload)

        layer2_metrics: Mapping[str, object] = {}
        judge_config_error = False
        try:
            effective_runner, effective_judge, effective_ragas = (agent_runner, judge_llm, ragas_evaluator) if agent_runner is not None else await _build_layer2_deps(kb_id, run_id)
            layer2_report = await run_layer2_evaluation(
                questions,
                agent_runner=effective_runner,
                judge_llm=effective_judge,
                ragas_evaluator=effective_ragas,
                kb_id=kb_id,
                run_id=run_id,
                progress_hook=_forward_progress,
            )
            layer2_metrics = layer2_metrics_from_report(layer2_report_to_dict(layer2_report), questions=questions)
        except RagConfigurationError:
            # The judge's *configuration* error is not the optional layer's quality problem
            # (spec 2026-09-23 D10.5): the run is recorded as error, keeping layer 1 and the
            # baseline diff, instead of a `completed` run with a hollow second layer. The
            # wide catch below still degrades every other second-layer failure to a log line.
            logger.exception("on-demand full eval run %s: judge target unusable for kb %s", run_id, kb_id)
            judge_config_error = True
        except Exception:
            logger.exception("on-demand full eval run %s: layer-2 stage failed for kb %s (keeping layer-1 results)", run_id, kb_id)

        await save_eval_run(
            run_id=run_id,
            kb_id=kb_id,
            status="error" if judge_config_error else "completed",
            created_at=datetime.fromisoformat(generated_at),
            completed_at=datetime.now(UTC),
            layer1_metrics=layer1_metrics,
            layer2_metrics=layer2_metrics or None,
            baseline_diff=baseline_diff,
            environment=ENV_LOCAL,
        )
        return run_id
    except asyncio.CancelledError:
        # 终止（spec §11）：layer1 已跑完则带其指标（廉价层成果永不丢）后重抛。
        await _save_cancelled_row(run_id=run_id, kb_id=kb_id, created_at=datetime.fromisoformat(generated_at), layer1_metrics=layer1_metrics)
        raise
    except Exception:
        logger.exception("on-demand full eval run %s failed for kb %s", run_id, kb_id)
        await _save_error_row(run_id=run_id, kb_id=kb_id, created_at=datetime.fromisoformat(generated_at))
        return run_id
    finally:
        _TASKS.pop(kb_id, None)
        _release_run(kb_id)


async def _build_layer2_deps(kb_id: str, run_id: str):
    """生产装配（与 CLI 口径一致）：lead-agent runner + ``rag.judge_model`` judge + ragas 评估器。

    judge 未配置时传 ``None``；工厂按 RAG 自己的顺序（D3）取 ``rag.judge_model`` → RAG 默认 → 首项。
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.knowledge.eval.factory import build_judge_llm, build_ragas_evaluator
    from deerflow.knowledge.eval.ragas_eval import build_lead_agent_runner
    from deerflow.knowledge.store import get_knowledge_store

    store = get_knowledge_store()
    kb = await store.get_kb(kb_id)
    if kb is None:
        raise LookupError(f"knowledge base not found: {kb_id}")
    config = get_app_config()
    # A hand-written ``judge_model: ""`` means "not configured" (the API prunes blanks);
    # passing the empty string through would resolve a model named "" and raise.
    judge = build_judge_llm(config.rag.judge_model or None, config=config)
    runner = build_lead_agent_runner(kb_id=kb_id, user_id=kb["owner_id"], run_id=run_id)
    return runner, judge, build_ragas_evaluator(judge)


async def _save_error_row(*, run_id: str, kb_id: str, created_at: datetime) -> None:
    """Best-effort error-row persistence — never raises (best-effort 同 CLI)."""

    try:
        await save_eval_run(
            run_id=run_id,
            kb_id=kb_id,
            status="error",
            created_at=created_at,
            completed_at=datetime.now(UTC),
            environment=ENV_LOCAL,
        )
    except Exception:
        logger.exception("failed to persist error row %s for kb %s", run_id, kb_id)


async def _save_cancelled_row(*, run_id: str, kb_id: str, created_at: datetime, layer1_metrics: Mapping[str, object] | None = None) -> None:
    """Best-effort cancelled-row persistence (spec §11) — never raises.

    status 为自由字符串列（零迁移）；读集只认 completed → cancelled 行自动
    排除出 latest/trend，历史行是其唯一曝光面。
    """

    try:
        await save_eval_run(
            run_id=run_id,
            kb_id=kb_id,
            status="cancelled",
            created_at=created_at,
            completed_at=datetime.now(UTC),
            layer1_metrics=layer1_metrics,
            environment=ENV_LOCAL,
        )
    except Exception:
        logger.exception("failed to persist cancelled row %s for kb %s", run_id, kb_id)


async def _build_default_searchers(kb_id: str) -> dict[str, SearchFn]:
    """Production searcher wiring: same construction as the CLI's."""

    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import get_knowledge_store
    from deerflow.knowledge.vector_store import get_vector_store
    from deerflow.knowledge.wiki.store import WikiStore

    store = get_knowledge_store()
    kb = await store.get_kb(kb_id)
    if kb is None:
        raise LookupError(f"knowledge base not found: {kb_id}")
    return build_default_searchers(
        kb_id=kb_id,
        user_id=kb["owner_id"],
        store=store,
        vector_store=get_vector_store(),
        graph_store=GraphStore(store._sf),  # same construction the impls use
        wiki_store=WikiStore(store._sf),
    )
