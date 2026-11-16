"""Model-free reproduction of the public history projection and native counters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import call_unwrapped
from fastapi import BackgroundTasks
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.gateway.routers import threads
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.goal import build_goal_state, write_thread_goal
from scripts.benchmark.scheduled_tasks.protocol import goal_history_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_public_history_projection_omits_older_goals_but_native_accessor_reads_real_counters(tmp_path, monkeypatch, mode):
    """Only the history head carries the goal, and only while it is active; the
    benchmark therefore reads earlier counters through the native accessor."""
    from scripts.benchmark.scheduled_tasks.budget_evidence import read_native_goal_evidence

    objective = "Observe a synthetic budget stop"
    (tmp_path / ".scheduled-benchmark-disposable").write_text("synthetic test", encoding="utf-8")
    graph = build_state_mutation_graph("evidence", mode, snapshot_frequency=7)
    config = {"configurable": {"thread_id": "budget-thread", "checkpoint_ns": ""}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "deerflow.db")) as saver:
        await saver.setup()
        accessor = CheckpointStateAccessor.bind(graph, saver, mode=mode)
        goal = build_goal_state(objective)
        goal["continuation_count"] = 2
        await accessor.aupdate(config, {"goal": goal}, as_node="evidence")
        monkeypatch.setattr(threads, "get_checkpointer", lambda _request: saver)
        monkeypatch.setattr(threads, "build_thread_checkpoint_state_accessor", AsyncMock(return_value=(accessor, config)))

        async def public_history():
            projected = await call_unwrapped(threads.get_thread_history, thread_id="budget-thread", body=threads.ThreadHistoryRequest(limit=100), request=SimpleNamespace(), background_tasks=BackgroundTasks())
            return [entry.model_dump(mode="json") for entry in projected]

        active_shape = await public_history()
        assert active_shape[0]["values"]["goal"]["continuation_count"] == 2
        assert all("goal" not in entry["values"] for entry in active_shape[1:])
        # The production control writer removes the channel; the reducer's
        # ordinary None update deliberately preserves an active goal.
        await write_thread_goal(saver, "budget-thread", None)
        api_shape = await public_history()
        assert all("goal" not in entry["values"] for entry in api_shape)
        assert goal_history_evidence(api_shape, objective)["goal_snapshots_observed"] == 0

    evidence = await read_native_goal_evidence(tmp_path, thread_id="budget-thread", objective=objective, mode=mode, snapshot_frequency=7)
    assert evidence["goal_snapshots_observed"] > 0
    assert evidence["maximum_observed_continuation_count"] == 2
    assert evidence["continuation_limits_observed"] == [8]
    assert evidence["within_observed_limits"]
    assert evidence["latest_goal_cleared"]
    assert evidence["read_only"] is True


@pytest.mark.asyncio
async def test_missing_native_goal_evidence_cannot_be_fabricated_as_zero(tmp_path):
    from scripts.benchmark.scheduled_tasks.budget_evidence import read_native_goal_evidence

    (tmp_path / ".scheduled-benchmark-disposable").write_text("synthetic test", encoding="utf-8")
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "deerflow.db")) as saver:
        await saver.setup()
    result = await read_native_goal_evidence(tmp_path, thread_id="absent", objective="Missing")
    assert result["maximum_observed_continuation_count"] is None
    assert not result["within_observed_limits"]
