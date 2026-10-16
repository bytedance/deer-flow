"""Offline checks for the real-Gateway synthetic pilot; never calls a provider."""

import copy
import json

import pytest

from scripts.benchmark.scheduled_tasks.protocol import assert_arm_installed, fixture, goal_history_evidence, grade_artifact, require_loopback, require_spend_reserve, run_cost, task_prompt


def test_fixture_reader_cannot_open_arbitrary_paths_or_urls():
    assert fixture("inventory")["source"]["document"].startswith("Synthetic")
    for selector in ("../secrets", "file:///tmp/key", "https://example.com", "missing"):
        with pytest.raises(ValueError, match="Unknown synthetic"):
            fixture(selector)


def test_grading_checks_opened_artifact_values_independently_of_success_claim():
    expected = fixture("inventory")["expected"]
    assert grade_artifact(json.dumps(expected), expected)["passed"]
    assert not grade_artifact('{"status":"success","total":11,"items":["Alpha","Beta"]}', expected)["passed"]
    assert not grade_artifact("The goal was satisfied", expected)["passed"]
    assert not grade_artifact('{"total":true,"items":["Alpha","Beta"]}', expected)["passed"]
    assert not grade_artifact("[]", expected)["passed"]


def test_paired_prompt_is_identical_for_both_arms_and_uses_synthetic_source():
    first = task_prompt("corrected-ledger", "report.json")
    second = task_prompt("corrected-ledger", "report.json")
    assert first == second
    assert "read_scheduled_fixture" in first
    assert "subagents" in first


@pytest.mark.parametrize("url", ["https://example.com", "http://127.0.0.1@external.example", "http://127.0.0.1/prefix", "http://127.0.0.1?token=secret"])
def test_live_target_must_be_a_bare_disposable_loopback_origin(url):
    with pytest.raises(ValueError):
        require_loopback(url)


def test_spend_guard_refuses_over_budget_or_unbounded_admission():
    require_spend_reserve(0.8, 0.1, 1)
    for spent, reserve, ceiling in ((0.95, 0.1, 1), (0, 0, 1), (0, 0.1, 2), (float("nan"), 0.1, 1)):
        with pytest.raises(ValueError):
            require_spend_reserve(spent, reserve, ceiling)


def test_cost_reads_production_usage_buckets_and_detects_model_deviation():
    plan = {"model_alias": "pilot", "provider_model": "configured-model", "pricing": {"input_per_million": 2, "output_per_million": 4}}
    row = {"model_name": "pilot", "total_input_tokens": 100, "total_output_tokens": 10, "token_usage_by_model": {"configured-model": {"input_tokens": 100, "output_tokens": 10}}}
    assert run_cost(row, plan) == pytest.approx(0.00024)
    unknown = copy.deepcopy(row)
    unknown["token_usage_by_model"]["unapproved-model"] = {"input_tokens": 1}
    with pytest.raises(ValueError, match="unexpected model"):
        run_cost(unknown, plan)


def test_arm_check_cannot_treat_an_uninstalled_goal_as_a_successful_goal_arm():
    assert_arm_installed("plain", {"goal_verdict": None})
    assert_arm_installed("goal", {"scheduled_goal_metadata_present": True, "scheduled_goal_objective": "Write report", "goal_verdict": {"satisfied": True}})
    for missing in ({"goal_verdict": {"satisfied": True}}, {"scheduled_goal_metadata_present": True, "scheduled_goal_objective": "Write report"}):
        with pytest.raises(AssertionError, match="comparison is invalid"):
            assert_arm_installed("goal", missing)
    with pytest.raises(AssertionError, match="plain arm"):
        assert_arm_installed("plain", {"scheduled_goal_metadata_present": True})


def test_budget_evidence_uses_actual_checkpoint_goal_counters_and_no_missing_evidence_default():
    entries = [{"values": {"goal": {"objective": "Produce report", "continuation_count": 0, "max_continuations": 8}}}, {"values": {"goal": None}}]
    evidence = goal_history_evidence(entries, "Produce report")
    assert evidence["within_observed_limits"]
    assert evidence["maximum_observed_continuation_count"] == 0
    assert not goal_history_evidence([], "Produce report")["within_observed_limits"]
    entries[0]["values"]["goal"]["continuation_count"] = 9
    assert not goal_history_evidence(entries, "Produce report")["within_observed_limits"]


def test_completion_requires_host_delivery_and_successful_run():
    from scripts.benchmark.scheduled_tasks.protocol import host_delivery_evidence, independent_completion

    path = "/mnt/user-data/outputs/report.json"
    events = [{"event_type": "run.delivery", "content": {"satisfied": True, "matched_paths": [path], "by_tool": {"present_files": [path]}}}]
    delivery = host_delivery_evidence(events, path)
    assert delivery["delivered"]
    assert independent_completion(artifact_passed=True, fixture_read=True, delivered=True, run_status="success", stop_reason=None)
    for fields in ({"delivered": False}, {"run_status": "error"}):
        data = {"artifact_passed": True, "fixture_read": True, "delivered": True, "run_status": "success", "stop_reason": None, **fields}
        assert not independent_completion(**data)
    assert not host_delivery_evidence([], path)["delivered"]
    assert not host_delivery_evidence([{"event_type": "llm.ai.response", "content": "I presented the file"}], path)["delivered"]
    events[0]["content"]["by_tool"] = {"write_file": [path]}
    assert not host_delivery_evidence(events, path)["delivered"]


@pytest.mark.parametrize(("delivered", "expected"), [(True, True), (False, False)])
def test_token_cap_does_not_erase_observed_completion_or_substitute_for_delivery(delivered, expected):
    from scripts.benchmark.scheduled_tasks.protocol import independent_completion

    assert independent_completion(artifact_passed=True, fixture_read=True, delivered=delivered, run_status="success", stop_reason="token_capped") is expected


@pytest.mark.asyncio
async def test_interactive_failure_prevents_another_paid_stage():
    from unittest.mock import AsyncMock

    from scripts.benchmark.scheduled_tasks.runner import Pilot

    pilot = object.__new__(Pilot)
    pilot.plan = {"model_alias": "pinned-model"}
    pilot.guard = AsyncMock()
    pilot.request = AsyncMock(return_value={"run_id": "failed-creation"})
    pilot.wait_run = AsyncMock(return_value={"status": "error", "run_id": "failed-creation"})
    with pytest.raises(RuntimeError, match="stop before further paid work"):
        await pilot.user_turn("owned-origin", "Create the exact schedule")
    assert pilot.request.await_count == 1


@pytest.mark.asyncio
async def test_production_fixture_seed_and_scheduler_launch_install_only_goal_arm_metadata(tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.scheduler.service import ScheduledTaskService
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
    from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
    from deerflow.runtime.user_context import DEFAULT_USER_ID
    from scripts.benchmark.scheduled_tasks.runner import Rows

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    (tmp_path / ".scheduled-benchmark-disposable").write_text("synthetic test only", encoding="utf-8")
    rows = Rows(tmp_path)
    try:
        factory = get_session_factory()
        origin = "synthetic-real-origin"
        await ThreadMetaRepository(factory).create(origin, user_id=DEFAULT_USER_ID)
        due = datetime.now(UTC) + timedelta(seconds=2)
        tasks = [await rows.seed_once("inventory", arm, {"scheduler_min_delay": 1}, due_at=due, origin_thread_id=origin) for arm in ("plain", "goal")]
        assert all(task["origin_thread_id"] == origin for task in tasks)
        captured = []

        async def launch(**kwargs):
            captured.append(kwargs)
            return {"run_id": f"fake-model-run-{len(captured)}", "thread_id": kwargs["thread_id"]}

        service = ScheduledTaskService(task_repo=ScheduledTaskRepository(factory), task_run_repo=ScheduledTaskRunRepository(factory), launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=3)
        await service.run_once(now=due + timedelta(seconds=1))
        by_task = {entry["metadata"]["scheduled_task_id"]: entry["metadata"] for entry in captured}
        assert "scheduled_goal_objective" not in by_task[tasks[0]["id"]]
        assert by_task[tasks[1]["id"]]["scheduled_goal_objective"] == tasks[1]["goal_objective"]
        with pytest.raises(AssertionError):
            assert_arm_installed("goal", {"scheduled_goal_metadata_present": True, "scheduled_goal_objective": tasks[1]["goal_objective"], "goal_verdict": None})
    finally:
        await rows.close()
        await close_engine()
