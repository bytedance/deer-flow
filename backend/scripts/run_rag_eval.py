"""Batch retrieval evaluation CLI (spec 2026-08-23 §6).

Runs the golden dataset through the three online retrieval impls — no gateway
needed, so it works in CI containers — writes ``report.json`` / ``report.md``,
prints the terminal summary, and maps the regression gate to the exit code:

- 0  ok (or no baseline given)
- 1  regression beyond ``--fail-threshold``
- 2  usage / IO error (bad golden file, missing baseline, unknown kb)
- 3  skipped — required API keys absent (explicit, never a fake green)

Usage (from ``backend/``):

    uv run python scripts/run_rag_eval.py \
        --kb-id <KB_ID> --golden tests/fixtures/rag_eval/golden.jsonl --out <dir> \
        [--baseline <prev report.json>|auto] [--top-k 5] [--fail-threshold 0.03] \
        [--environment local|ci|nightly] [--mark-baseline]

``--baseline auto`` diffs against the KB's marked baseline run (the eval_runs
``is_baseline`` row); no marked row means a plain no-diff run.
``--mark-baseline`` marks this run as the KB's baseline, clearing the previous
marker in the same transaction (spec 2026-08-24 §3.1.3). Completed runs only
(exit 0/1): on an error/skipped run the flag is ignored — the previous
baseline stays untouched — with a note on stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from deerflow.knowledge.eval.metrics import DEFAULT_FAIL_THRESHOLD
from deerflow.knowledge.eval.persistence import ENV_LOCAL, ENVIRONMENTS, STATUS_COMPLETED, generate_run_id, resolve_environment

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_ERROR = 2
EXIT_SKIPPED = 3


async def _persist_eval_run(args: argparse.Namespace, *, config=None, status: str, report=None, environment: str = ENV_LOCAL) -> None:
    """Best-effort eval_runs persistence (spec 2026-08-24 §3.1.1).

    Every CLI run writes exactly one row — completed runs carry the mapped
    layer1_metrics (+ baseline_diff when --baseline was given), error/skipped
    runs record the attempt with empty metrics. Persistence never changes the
    exit code: any failure is reported as a note on stderr.

    The engine lifecycle mirrors the call site: when the evaluation path
    already initialized the engine the row reuses it; early-exit paths (bad
    golden file, missing keys) initialize and close it on demand.
    """

    try:
        from deerflow.config.app_config import get_app_config
        from deerflow.knowledge.eval import persistence as eval_persistence
        from deerflow.knowledge.eval.runner import report_to_dict
        from deerflow.persistence import engine as persistence_engine

        layer1_metrics: dict = {}
        baseline_diff = None
        completed_at = None
        created_at = datetime.now(UTC)
        if report is not None:
            payload = report_to_dict(report)
            layer1_metrics = eval_persistence.layer1_metrics_from_report(payload)
            baseline_diff = eval_persistence.baseline_diff_from_report(payload, fail_threshold=args.fail_threshold)
            generated_at = report.meta.get("generated_at")
            if generated_at:
                # Single clock: created_at is the report's generated_at, never the DB default.
                created_at = datetime.fromisoformat(generated_at)
            completed_at = datetime.now(UTC)

        if args.mark_baseline and status != STATUS_COMPLETED:
            # §3.1.3 completed 门控：save_eval_run 会忽略该标记，这里给运维可见的提示。
            print(f"rag-eval note: --mark-baseline ignored for {status} run (only completed runs can become the KB baseline)", file=sys.stderr)

        own_engine = persistence_engine.get_session_factory() is None
        if own_engine:
            await persistence_engine.init_engine_from_config((config or get_app_config()).database)
        try:
            await eval_persistence.save_eval_run(
                run_id=generate_run_id(),
                kb_id=args.kb_id,
                status=status,
                created_at=created_at,
                completed_at=completed_at,
                layer1_metrics=layer1_metrics,
                baseline_diff=baseline_diff,
                environment=environment,
                mark_baseline=args.mark_baseline,
            )
        finally:
            if own_engine:
                await persistence_engine.close_engine()
    except Exception as exc:  # noqa: BLE001 — persistence must never sink a run
        print(f"rag-eval note: eval_runs persistence skipped ({type(exc).__name__}: {exc})", file=sys.stderr)


def _persist_quietly(args: argparse.Namespace, *, status: str, environment: str = ENV_LOCAL) -> None:
    """Sync wrapper for the missing-keys skip path in ``main()`` (no event loop yet)."""

    try:
        asyncio.run(_persist_eval_run(args, status=status, environment=environment))
    except Exception as exc:  # noqa: BLE001 — e.g. already inside an event loop
        print(f"rag-eval note: eval_runs persistence skipped ({type(exc).__name__}: {exc})", file=sys.stderr)


#: The vector path needs embedding + rerank credentials. The graph path's
#: extraction LLM key resolves through config.yaml model profiles — a missing
#: ``$VAR`` there makes ``AppConfig.from_file`` raise ValueError, which
#: ``_async_main`` maps to EXIT_SKIPPED.
REQUIRED_ENV_KEYS = ("DASHSCOPE_EMBEDDING_API_KEY", "DASHSCOPE_RERANK_API_KEY")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch retrieval evaluation against the golden dataset.")
    parser.add_argument("--golden", required=True, help="Path to the golden JSONL dataset.")
    parser.add_argument("--out", required=True, help="Output directory for report.json / report.md.")
    parser.add_argument("--kb-id", required=True, help="Knowledge base the golden questions were annotated against.")
    parser.add_argument(
        "--baseline",
        default=None,
        help="Previous report.json for the regression diff, or 'auto' to diff against the KB's marked baseline run in eval_runs.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Hits per path per question (default 5).")
    parser.add_argument(
        "--fail-threshold",
        type=float,
        default=DEFAULT_FAIL_THRESHOLD,
        help=f"Per-category recall drop that fails the gate (default {DEFAULT_FAIL_THRESHOLD}; initial guess — recalibrate after two weeks).",
    )
    parser.add_argument(
        "--environment",
        choices=ENVIRONMENTS,
        default=None,
        help="Run environment marker for eval_runs (default: infer — CI=true → ci, else local; nightly passes --environment nightly).",
    )
    parser.add_argument(
        "--mark-baseline",
        action="store_true",
        help="Mark this completed run as the KB's baseline in eval_runs (clears the previous marker in the same transaction; ignored for error/skipped runs).",
    )
    return parser.parse_args(argv)


def missing_required_keys(environ: Mapping[str, str]) -> list[str]:
    return [key for key in REQUIRED_ENV_KEYS if not environ.get(key)]


async def _load_auto_baseline(kb_id: str) -> dict | None:
    """Read the KB's marked baseline run (§3.1.3) as a diff-ready report payload.

    No marked row (or a marked row without Layer 1 metrics, e.g. a Layer 2 CLI
    mark) means a plain no-diff run — exit 0 semantics unchanged.
    """

    from deerflow.knowledge.eval import persistence as eval_persistence

    row = await eval_persistence.get_baseline_run(kb_id)
    if row is None or not row.layer1_metrics:
        print("rag-eval: --baseline auto but no baseline run is marked for this KB; running without diff")
        return None
    print(f"rag-eval: diffing against marked baseline run {row.id}")
    return eval_persistence.baseline_report_from_metrics(row.layer1_metrics)


async def _async_main(args: argparse.Namespace, *, environment: str = ENV_LOCAL) -> int:
    try:
        from deerflow.config.app_config import get_app_config

        config = get_app_config()
    except ValueError as exc:  # unresolved $ENV in config.yaml → missing credential
        print(f"rag-eval skipped: {exc}")
        return EXIT_SKIPPED

    # Fail fast on bad inputs BEFORE touching the persistence engine.
    from deerflow.knowledge.eval.dataset import GoldenDatasetError, load_golden

    try:
        questions = load_golden(args.golden)
        baseline = None
        if args.baseline and args.baseline != "auto":
            baseline_path = Path(args.baseline)
            if not baseline_path.exists():
                raise GoldenDatasetError(f"baseline report not found: {baseline_path}")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (GoldenDatasetError, json.JSONDecodeError) as exc:
        print(f"rag-eval error: {exc}", file=sys.stderr)
        await _persist_eval_run(args, config=config, status="error", environment=environment)
        return EXIT_ERROR

    from deerflow.knowledge.eval.runner import build_default_searchers, render_summary, run_evaluation, write_reports
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import get_knowledge_store
    from deerflow.knowledge.vector_store import get_vector_store
    from deerflow.knowledge.wiki.store import WikiStore
    from deerflow.persistence.engine import close_engine, init_engine_from_config

    await init_engine_from_config(config.database)
    try:
        store = get_knowledge_store()
        kb = await store.get_kb(args.kb_id)
        if kb is None:
            print(f"rag-eval error: knowledge base not found: {args.kb_id}", file=sys.stderr)
            await _persist_eval_run(args, config=config, status="error", environment=environment)
            return EXIT_ERROR
        # The DB-backed baseline resolves only after the engine is up (it reads
        # the eval_runs is_baseline row); a missing marker is not an error.
        if args.baseline == "auto":
            baseline = await _load_auto_baseline(args.kb_id)
        # Owner-only access gate (phase 1): the eval runs as the KB owner,
        # resolved from the store — no separate credential to manage.
        searchers = build_default_searchers(
            kb_id=args.kb_id,
            user_id=kb["owner_id"],
            store=store,
            vector_store=get_vector_store(),
            graph_store=GraphStore(store._sf),  # same construction the impls use
            wiki_store=WikiStore(store._sf),
        )
        report = await run_evaluation(
            questions,
            searchers,
            top_k=args.top_k,
            baseline=baseline,
            fail_threshold=args.fail_threshold,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        # exit 0/1 both map to `completed` — the regression gate signal lives
        # in baseline_diff and the trend chart needs the regression run's point.
        await _persist_eval_run(args, config=config, status="completed", report=report, environment=environment)
    finally:
        await close_engine()

    json_path, md_path = write_reports(report, args.out)
    print(render_summary(report))
    print(f"report: {json_path} · {md_path}")
    return report.exit_code


def _run(args: argparse.Namespace, *, environment: str = ENV_LOCAL) -> int:
    return asyncio.run(_async_main(args, environment=environment))


def _load_env_files() -> None:
    """Load .env files with repo-root as fallback and backend/.env taking precedence.

    Operators reasonably put keys in either place: the repo-root .env doubles
    as the docker-compose substitution source, while backend/.env is what the
    gateway reads. ``find_dotenv`` alone stops at the nearest file, so a key
    set only in the root .env would silently not reach the CLI.
    """

    from dotenv import load_dotenv

    repo_root_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(repo_root_env)  # fallback: fills only unset vars
    load_dotenv(override=True)  # backend/.env wins over the root file


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = parse_args(argv)
    if environ is None:
        # Production path: pick up .env files (tests inject ``environ``
        # explicitly and never touch dotenv).
        _load_env_files()
        environ = os.environ
    environment = resolve_environment(args.environment, environ)
    missing = missing_required_keys(environ)
    if missing:
        print(f"rag-eval skipped: missing required API keys: {', '.join(missing)} (exit {EXIT_SKIPPED} — explicit skip, not a pass)")
        _persist_quietly(args, status="skipped", environment=environment)  # 留痕：何时尝试过（best-effort）
        return EXIT_SKIPPED
    return _run(args, environment=environment)


if __name__ == "__main__":
    sys.exit(main())
