"""Run history rows carry run numbers, token totals and the agent's summary."""

import pytest
import pytest_asyncio
from _scheduled_rows import create_task, durable_run, occurrence

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest_asyncio.fixture
async def repos(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    try:
        yield sf, ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_run_numbers_match_the_safety_cap_count_and_skip_unlaunched_rows(repos):
    sf, tasks, runs = repos
    await create_task(tasks, max_runs=10)
    async with sf() as session:
        session.add_all(
            [
                occurrence("first", seq=1, run_id="run-first"),
                occurrence("trial", seq=2, trigger="manual", run_id="run-trial"),
                occurrence("skipped", seq=3, status="skipped", accounted=False),
                occurrence("second", seq=4, status="unmet", run_id="run-second"),
                occurrence("cancelled", seq=5, status="interrupted", accounted=False, error="scheduled task was paused while queued"),
                occurrence("third", seq=6, status="failed", run_id="run-third"),
                occurrence("legacy", seq=None, accounted=None, run_id="run-legacy"),
            ]
        )
        await session.commit()
    rows = {row["id"]: row for row in await runs.list_by_task("task-1", limit=50)}
    assert {key: rows[key]["run_number"] for key in rows} == {"first": 1, "trial": None, "skipped": None, "second": 2, "cancelled": None, "third": 3, "legacy": None}
    used = (await tasks.automatic_runs_used_for(["task-1"]))["task-1"]
    assert max(row["run_number"] or 0 for row in rows.values()) == used == 3
    assert await runs.run_number("third") == 3
    assert await runs.run_number("trial") is None
    assert await runs.run_number("skipped") is None


@pytest.mark.asyncio
async def test_a_launching_row_gets_the_number_it_will_have_once_accounted(repos):
    sf, tasks, runs = repos
    await create_task(tasks)
    async with sf() as session:
        session.add_all([occurrence("first", seq=1, run_id="run-first"), occurrence("trial", seq=2, trigger="manual", run_id="run-trial"), occurrence("now", seq=3, status="launching", accounted=False)])
        await session.commit()
    assert await runs.run_number("now") == 2
    assert {row["id"]: row["run_number"] for row in await runs.list_by_task("task-1")}["now"] == 2


@pytest.mark.asyncio
async def test_rows_carry_token_totals_and_the_agents_reply_not_the_evaluator_reason(repos):
    sf, tasks, runs = repos
    await create_task(tasks, goal_objective="all items checked")
    verdict = {"satisfied": False, "reason": "The evaluator wrote this in English.", "stand_down_reason": "blocked:goal_not_met_yet"}
    async with sf() as session:
        session.add_all(
            [
                occurrence("done", seq=1, run_id="run-done", thread_id="thread-done"),
                occurrence("missed", seq=2, status="unmet", run_id="run-missed", thread_id="thread-missed", goal_verdict=verdict, error="blocked:goal_not_met_yet"),
                occurrence("waiting", seq=3, status="queued", accounted=False),
                durable_run("run-done", thread_id="thread-done", total_tokens=1234, last_ai_message="\n## 清单检查结果\n\n- 还有 2 项未勾选"),
                durable_run("run-missed", thread_id="thread-missed", total_tokens=88, last_ai_message="**Two items** are still open: [owner list](https://example.test)."),
            ]
        )
        await session.commit()
    rows = {row["id"]: row for row in await runs.list_by_task("task-1")}
    assert (rows["done"]["total_tokens"], rows["done"]["summary"]) == (1234, "清单检查结果")
    assert (rows["missed"]["total_tokens"], rows["missed"]["summary"]) == (88, "Two items are still open: owner list.")
    assert rows["missed"]["goal_verdict"]["reason"] == "The evaluator wrote this in English."
    assert (rows["waiting"]["total_tokens"], rows["waiting"]["summary"], rows["waiting"]["run_number"]) == (None, None, None)
    assert "occurrence_seq" not in rows["done"] and "launch_accounted" not in rows["done"]


def test_summary_is_bounded():
    from deerflow.persistence.scheduled_task_runs.sql import run_summary

    summary = run_summary("x" * 400)
    assert len(summary) == 160 and summary.endswith("…")
    assert run_summary("---\n\n   ") is None
    assert run_summary(None) is None
