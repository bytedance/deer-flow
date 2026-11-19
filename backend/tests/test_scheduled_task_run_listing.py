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


# The final reply of run 1 of the live acceptance task (ux-audit/impl/live/S5-runs.json,
# task-run-f83bbe9076644db0b7cf4907e9911d08, thread c18ee7af-…), recorded on DeepSeek Flash.
# Demo data; the names are fictional.
LIVE_RUN_1_REPLY = (
    "清单中还有 2 项未完成：\n\n"
    "- **Publish the Docker image** — 负责人：Sam Okafor\n"
    "- **Post the release notes** — 负责人：Nora Lind\n\n"
    "其余 3 项（冻结发布分支、更新变更日志、运行完整测试套件）均已完成。由于仍有未勾选条目，停止条件未满足，本次不暂停计划。"
)
LIVE_RUN_2_REPLY = "已按停止规则暂停该定时任务：清单中所有条目均已完成，没有未勾选项，无需继续轮询。如需恢复，可在界面中重新启用该计划。"


def test_a_lead_in_line_carries_the_list_that_follows_it():
    from deerflow.persistence.scheduled_task_runs.sql import run_summary

    # Recorded live: the first line alone ("清单中还有 2 项未完成：") said nothing.
    assert run_summary(LIVE_RUN_1_REPLY) == "清单中还有 2 项未完成：Publish the Docker image — 负责人：Sam Okafor；Post the release notes — 负责人：Nora Lind"
    # A first line that is a full sentence (colon inside, not at the end) stays as it is.
    assert run_summary(LIVE_RUN_2_REPLY) == LIVE_RUN_2_REPLY


def test_lead_in_list_variants():
    from deerflow.persistence.scheduled_task_runs.sql import run_summary

    # No list after the colon: the line is returned unchanged.
    assert run_summary("Two items are still open:\n\nSee the checklist for details.") == "Two items are still open:"
    assert run_summary("还有 2 项未完成：") == "还有 2 项未完成："
    # Numbered list, English: "; " between items, a space after the colon.
    assert run_summary("Still open:\n1. Publish the image — Sam\n2) Post the notes — Nora\n\nNothing else changed.") == "Still open: Publish the image — Sam; Post the notes — Nora"
    # Markdown bold, links, code and task checkboxes are stripped from the items; the list ends at the first prose line.
    assert run_summary("**Open items:**\n\n- [ ] **Publish** the [image](https://example.test) — `Sam`\n* [x] Post the notes — Nora\nThat is all.\n- not part of it") == "Open items: Publish the image — Sam; Post the notes — Nora"
    # The script of the summary text picks the separator, also with an ASCII colon,
    # which keeps a space after it (a full-width "：" does not need one).
    assert run_summary("未完成的条目:\n- 发布镜像\n- 发布说明") == "未完成的条目: 发布镜像；发布说明"


def test_a_long_lead_in_list_is_capped_with_an_ellipsis():
    from deerflow.persistence.scheduled_task_runs.sql import run_summary

    reply = "还有这些未完成：\n" + "\n".join(f"- 第 {n} 项任务，负责人是一位很忙的同事" for n in range(1, 20))
    summary = run_summary(reply)
    assert len(summary) == 160 and summary.endswith("…")
    assert summary.startswith("还有这些未完成：第 1 项任务，负责人是一位很忙的同事；第 2 项任务")
