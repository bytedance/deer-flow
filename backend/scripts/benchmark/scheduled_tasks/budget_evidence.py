"""Read existing budget evidence without executing models or changing runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import URL, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.database_config import DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.user_context import DEFAULT_USER_ID

from .protocol import assert_arm_installed, goal_history_evidence, load_pilot_config


def _disposable_db(directory: Path) -> Path:
    if not directory.is_absolute() or not (directory / ".scheduled-benchmark-disposable").is_file() or not (directory / "deerflow.db").is_file():
        raise ValueError("Use only the existing marked absolute disposable SQLite directory")
    return directory / "deerflow.db"


async def read_native_goal_evidence(
    directory: Path,
    *,
    thread_id: str,
    objective: str,
    mode: str = "full",
    snapshot_frequency: int = DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY,
) -> dict[str, Any]:
    """Read the complete root history with the production accessor and schema.

    Only this pilot's default lead schema is supported. No graph execution or
    mutation occurs. SQLite protections remain active during saver setup;
    missing schema/setup failure is fatal rather than enabling writes.
    """
    if mode not in {"full", "delta"}:
        raise ValueError("Unsupported checkpoint channel mode")
    db = _disposable_db(directory)
    async with aiosqlite.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        await connection.execute("PRAGMA query_only=ON")
        saver = AsyncSqliteSaver(connection)
        graph = build_state_mutation_graph("budget_evidence_read_only", mode, snapshot_frequency=snapshot_frequency)
        accessor = CheckpointStateAccessor.bind(graph, saver, mode=mode)
        snapshots = await accessor.ahistory({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, limit=None)
        query_only = (await (await connection.execute("PRAGMA query_only")).fetchone())[0] == 1
    entries = []
    for snapshot in snapshots:
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        goal = values.get("goal")
        if isinstance(goal, dict):
            goal = {key: goal[key] for key in ("objective", "created_at", "continuation_count", "max_continuations") if key in goal}
        entries.append({"checkpoint_id": (snapshot.config.get("configurable") or {}).get("checkpoint_id"), "values": {"goal": goal}})
    latest_values = snapshots[0].values if snapshots and isinstance(snapshots[0].values, dict) else {}
    return {
        **goal_history_evidence(entries, objective),
        "history_source": "read_only_native_sqlite_production_checkpoint_state_accessor",
        "schema_scope": "default_lead_base_thread_state",
        "checkpoint_channel_mode": mode,
        "checkpoint_snapshot_frequency": snapshot_frequency,
        "read_only": query_only,
        "history_snapshots_observed": len(entries),
        "history_complete": True,
        "matching_checkpoint_ids": [entry["checkpoint_id"] for entry in entries if isinstance(entry["values"]["goal"], dict) and entry["values"]["goal"].get("objective") == objective],
        # Production write_thread_goal clears by removing this channel.
        "latest_goal_cleared": bool(snapshots) and latest_values.get("goal") is None,
    }


async def recheck_budget(args: Any) -> dict[str, Any]:
    """Recheck one existing run; never create/launch/cancel any work."""
    if args.output.exists():
        raise ValueError("Use a new recheck file; preserve the original failure")
    original_path = args.run_output / "results.json"
    original = json.loads(original_path.read_text(encoding="utf-8"))
    provenance = json.loads((args.run_output / "provenance.json").read_text(encoding="utf-8"))
    plan = load_pilot_config(args.config, args.model)
    if plan["config_sha256"] != provenance["config_sha256"] or plan["sqlite_dir"] != provenance["sqlite_dir"]:
        raise ValueError("Use the exact original budget configuration and database")
    selected = [result for result in original if result.get("arm") == "goal" and result.get("token_cap_observed")]
    if len(selected) != 1 or plan["token_budget"]["max_tokens"] > 2000:
        raise ValueError("Select exactly one recorded tiny-budget goal occurrence")
    previous = selected[0]
    expected = previous["run"]
    db = _disposable_db(Path(plan["sqlite_dir"]))
    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=f"file:{db}", query={"mode": "ro", "uri": "true"}))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            run = await session.get(RunRow, expected["run_id"])
            if run is None or run.user_id != DEFAULT_USER_ID or run.thread_id != expected["thread_id"] or run.assistant_id not in {None, "lead_agent"}:
                raise ValueError("The existing run is not the disposable owner's default lead run")
            metadata = run.metadata_json or {}
            objective = metadata.get("scheduled_goal_objective")
            assert_arm_installed("goal", {"scheduled_goal_metadata_present": "scheduled_goal_objective" in metadata, "scheduled_goal_objective": objective, "goal_verdict": run.goal_verdict})
            if objective != expected["scheduled_goal_objective"] or run.status != expected["status"] or run.llm_call_count != expected["llm_call_count"] or run.total_tokens != expected["total_tokens"]:
                raise ValueError("Existing objective, status, calls or usage changed")
            thread_runs = list((await session.scalars(select(RunRow.run_id).where(RunRow.thread_id == run.thread_id, RunRow.operation_kind == "run"))).all())
            occurrences = list((await session.scalars(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == previous["occurrence"]["task_id"]))).all())
            no_later = thread_runs == [run.run_id] and len(occurrences) == 1 and occurrences[0].run_id == run.run_id
            cap = run.stop_reason == "token_capped" or (run.goal_verdict or {}).get("stand_down_reason") == "token_capped"
            history = await read_native_goal_evidence(Path(plan["sqlite_dir"]), thread_id=run.thread_id, objective=objective, mode=plan["checkpoint_channel_mode"], snapshot_frequency=plan["checkpoint_snapshot_frequency"])
            passed = cap and history["within_observed_limits"] and history["maximum_observed_continuation_count"] == 0 and history["latest_goal_cleared"] and no_later
            result = {
                "passed": bool(passed),
                "verification_level": "existing_real_gateway_run_read_only_persisted_state_recheck",
                "new_provider_calls": 0,
                "run_id": run.run_id,
                "thread_id": run.thread_id,
                "task_id": previous["occurrence"]["task_id"],
                "stop_reason": run.stop_reason,
                "goal_verdict_stand_down_reason": (run.goal_verdict or {}).get("stand_down_reason"),
                "token_cap_observed": cap,
                "goal_history": history,
                "goal_cleared": history["latest_goal_cleared"],
                "no_later_continuation_observed": no_later,
                "llm_call_count": run.llm_call_count,
                "total_tokens": run.total_tokens,
                "original_results_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
                "original_failure_preserved": (args.run_output / "failure.json").is_file(),
                "original_api_goal_history": previous["goal_history"],
                "reader_correction": "Public history projects title/thread_data/messages and omits goal; native accessor reads the persisted goal channel",
            }
    finally:
        await engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not passed:
        raise AssertionError("Existing budget run lacks complete cap/goal/counter evidence")
    return result
