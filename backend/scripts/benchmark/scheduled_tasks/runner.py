"""Explicit live pilot against a disposable real Gateway, not another runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import URL, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.routers.scheduled_tasks import ScheduledTaskCreateRequest, resolve_scheduled_task_assistant_id
from app.gateway.run_models import RunCreateRequest
from app.gateway.scheduled_task_validation import validate_scheduled_task_create
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import TERMINAL_RUN_STATUSES, ScheduledTaskRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.user_context import DEFAULT_USER_ID

from .protocol import (
    ROOT,
    assert_arm_installed,
    comparison_summary,
    fixture,
    grade_artifact,
    host_delivery_evidence,
    independent_completion,
    load_pilot_config,
    require_loopback,
    require_spend_reserve,
    run_cost,
    task_prompt,
)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def provenance(config: Path, model: str) -> dict[str, Any]:
    plan = load_pilot_config(config, model)
    repo = ROOT.parents[3]
    plan["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    plan["git_diff_sha256"] = hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=repo)).hexdigest()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=repo).decode().split("\0")
    safe_sources = [name for name in untracked if name and (name.endswith(".py") and name.startswith("backend/") or name.endswith(".json") and name.startswith(("contracts/", "backend/scripts/benchmark/scheduled_tasks/")))]
    plan["untracked_source_sha256"] = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in safe_sources}
    plan["benchmark_source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(ROOT.glob("*.py"))}
    plan["started_at"] = datetime.now(UTC).isoformat()
    plan["cost_basis"] = "Configured peak-price estimate; provider billing and off-peak discounts are not verified by this runner"
    return plan


def message_evidence(rows: Any) -> dict[str, Any]:
    rows = rows.get("data", []) if isinstance(rows, dict) else rows
    names: set[str] = set()
    turns: set[str] = set()
    fixture_read = False
    reference_read = False
    for row in rows:
        message = row.get("content") or {}
        if not isinstance(message, dict):
            continue
        role = message.get("type") or message.get("role")
        if role in {"ai", "assistant"} and (row.get("metadata") or {}).get("caller", "lead_agent") == "lead_agent":
            turns.add(str(message.get("id") or row.get("seq")))
            names.update(call.get("name") for call in message.get("tool_calls", []) if isinstance(call, dict) and call.get("name"))
        if role == "tool":
            name = message.get("name")
            if name:
                names.add(name)
            try:
                result = json.loads(message.get("content", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict):
                fixture_read |= name == "read_scheduled_fixture" and result.get("synthetic") is True
                reference_read |= name == "read_conversation" and result.get("status") == "ok" and bool(result.get("messages"))
    return {"tool_names": sorted(names), "lead_model_turns": len(turns), "fixture_read_succeeded": fixture_read, "previous_reference_read_succeeded": reference_read}


class Rows:
    """Read production rows; fixture setup uses the production repository only."""

    def __init__(self, sqlite_dir: Path):
        if not sqlite_dir.is_absolute() or not (sqlite_dir / ".scheduled-benchmark-disposable").is_file() or not (sqlite_dir / "deerflow.db").is_file():
            raise ValueError("Mark an existing disposable absolute SQLite directory before live execution")
        db = sqlite_dir / "deerflow.db"
        self.read_engine = create_async_engine(URL.create("sqlite+aiosqlite", database=f"file:{db}", query={"mode": "ro", "uri": "true"}))
        self.write_engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(db)))
        self.read_session = async_sessionmaker(self.read_engine, expire_on_commit=False)
        self.write_session = async_sessionmaker(self.write_engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.read_engine.dispose()
        await self.write_engine.dispose()

    async def metrics(self) -> list[dict[str, Any]]:
        fields = (
            "run_id",
            "thread_id",
            "user_id",
            "status",
            "model_name",
            "total_input_tokens",
            "total_output_tokens",
            "total_tokens",
            "llm_call_count",
            "lead_agent_tokens",
            "middleware_tokens",
            "token_usage_by_model",
            "goal_verdict",
            "stop_reason",
            "created_at",
            "updated_at",
        )
        async with self.read_session() as session:
            rows = (await session.scalars(select(RunRow).where(RunRow.operation_kind == "run").order_by(RunRow.created_at))).all()
            if any(row.user_id != DEFAULT_USER_ID for row in rows):
                raise ValueError("The disposable pilot database contains another user's runs")
            return [
                {
                    **{key: getattr(row, key) for key in fields},
                    "scheduled_goal_metadata_present": "scheduled_goal_objective" in (row.metadata_json or {}),
                    "scheduled_goal_objective": (row.metadata_json or {}).get("scheduled_goal_objective"),
                }
                for row in rows
            ]

    async def occurrences(self, task_id: str) -> list[dict[str, Any]]:
        fields = ("id", "task_id", "thread_id", "run_id", "occurrence_seq", "status", "trigger", "error", "goal_verdict", "stop_requested_run_id", "started_at", "finished_at")
        async with self.read_session() as session:
            query = (
                select(ScheduledTaskRunRow)
                .join(ScheduledTaskRow, ScheduledTaskRunRow.task_id == ScheduledTaskRow.id)
                .where(ScheduledTaskRow.id == task_id, ScheduledTaskRow.user_id == DEFAULT_USER_ID)
                .order_by(ScheduledTaskRunRow.occurrence_seq)
            )
            return [{key: getattr(row, key) for key in fields} for row in (await session.scalars(query)).all()]

    async def seed_once(self, case_id: str, arm: str, plan: dict[str, Any], *, due_at: datetime, origin_thread_id: str) -> dict[str, Any]:
        """Declared benchmark setup; execution still belongs to Gateway's poller."""
        prompt = task_prompt(case_id, "report.json")
        origin = await ThreadMetaRepository(self.read_session).get(origin_thread_id, user_id=DEFAULT_USER_ID)
        if origin is None or origin.get("user_id") != DEFAULT_USER_ID:
            raise ValueError("Benchmark fixture seeding requires a real owned origin thread")
        body = ScheduledTaskCreateRequest(title=f"synthetic-{case_id}-{arm}", prompt=prompt, schedule_type="once", schedule_spec={"run_at": due_at.isoformat()}, timezone="UTC")
        scheduler = SchedulerConfig(enabled=True, min_once_delay_seconds=plan["scheduler_min_delay"])
        definition = await validate_scheduled_task_create(body, user_id=DEFAULT_USER_ID, thread_store=None, scheduler_config=scheduler, assistant_resolver=resolve_scheduled_task_assistant_id)
        return await ScheduledTaskRepository(self.write_session).create(
            task_id=f"bench-{uuid.uuid4().hex}",
            user_id=DEFAULT_USER_ID,
            origin_thread_id=origin_thread_id,
            **definition,
            goal_objective=f"{fixture(case_id)['instruction']} Produce and present report.json from the supplied synthetic source." if arm == "goal" else None,
        )


class Pilot:
    def __init__(self, *, base_url: str, plan: dict[str, Any], output: Path, max_cost: float, reserve: float, timeout: float, interval: int):
        self.plan = plan
        self.output = output
        self.max_cost = max_cost
        self.reserve = reserve
        self.timeout = timeout
        self.interval = interval
        self.session_id = uuid.uuid4().hex[:12]
        self.task_ids: set[str] = set()
        self.origin_ids: set[str] = set()
        self.results: list[dict[str, Any]] = []
        self.rows = Rows(Path(plan["sqlite_dir"]))
        self.client = httpx.AsyncClient(base_url=require_loopback(base_url), timeout=30, trust_env=False)

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"Gateway HTTP {response.status_code}: {method} {path}")
        return response.json() if response.content else None

    async def guard(self, *, admit: bool = False) -> float:
        metrics = await self.rows.metrics()
        spent = 0.0
        for row in metrics:
            cost = run_cost(row, self.plan)
            if cost is None and row["status"] not in {"pending", "running"} and row["llm_call_count"]:
                raise RuntimeError("A terminal paid run has unavailable cost accounting; stop the pilot")
            if row["status"] in {"pending", "running"}:
                live = await self.request("GET", f"/api/threads/{row['thread_id']}/runs/{row['run_id']}")
                cost = max(cost or 0, run_cost(live, self.plan) or 0)
            spent += cost or 0
        if admit:
            require_spend_reserve(spent, self.reserve, self.max_cost)
        elif spent >= self.max_cost:
            raise RuntimeError("Measured pilot estimate reached the spend guard; cancel active work")
        return spent

    async def preflight(self) -> None:
        await self.request("GET", "/health/ready")
        models = await self.request("GET", "/api/models")
        first = models["models"][0]
        if first["name"] != self.plan["model_alias"] or first["model"] != self.plan["provider_model"]:
            raise ValueError("Gateway model differs from the named pinned pilot configuration")
        await self.guard(admit=True)

    async def wait_run(self, thread_id: str, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            await self.guard()
            row = await self.request("GET", f"/api/threads/{thread_id}/runs/{run_id}")
            if row["status"] not in {"pending", "running"}:
                return row
            await asyncio.sleep(0.5)
        raise TimeoutError("The real Gateway run exceeded the pilot timeout")

    async def user_turn(self, thread_id: str, text: str) -> dict[str, Any]:
        await self.guard(admit=True)
        body = RunCreateRequest(input={"messages": [{"role": "user", "content": text}]}, context={"model_name": self.plan["model_alias"], "thinking_enabled": False, "subagent_enabled": False}, on_disconnect="continue")
        created = await self.request("POST", f"/api/threads/{thread_id}/runs", json=body.model_dump(exclude_none=True))
        result = await self.wait_run(thread_id, created["run_id"])
        if result["status"] != "success":
            raise RuntimeError(f"Interactive pilot run ended {result['status']}; stop before further paid work")
        return result

    async def wait_occurrence(self, task_id: str, count: int) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            await self.guard()
            occurrences = await self.rows.occurrences(task_id)
            if len(occurrences) >= count and occurrences[count - 1]["status"] in TERMINAL_RUN_STATUSES:
                return occurrences[count - 1]
            await asyncio.sleep(0.5)
        raise TimeoutError("Automatic scheduled occurrence exceeded the pilot timeout")

    async def observed_result(self, case_id: str, arm: str, occurrence: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        result = {"case_id": case_id, "arm": arm, "occurrence": occurrence, "prompt_sha256": hashlib.sha256(task_prompt(case_id, "report.json").encode()).hexdigest()}
        if not occurrence.get("run_id"):
            return {**result, "grade": {"passed": False, "reason": "no_gateway_run"}}
        matching = [row for row in await self.rows.metrics() if row["run_id"] == occurrence["run_id"]]
        if matching:
            result["run"] = matching[0]
            result["estimated_cost_usd"] = run_cost(matching[0], self.plan)
        messages = await self.request("GET", f"/api/threads/{occurrence['thread_id']}/runs/{occurrence['run_id']}/messages?limit=200")
        result["evidence"] = message_evidence(messages)
        delivery_events = await self.request("GET", f"/api/threads/{occurrence['thread_id']}/runs/{occurrence['run_id']}/events?event_types=run.delivery")
        result["delivery"] = host_delivery_evidence(delivery_events, "/mnt/user-data/outputs/report.json")
        artifact = await self.client.get(f"/api/threads/{occurrence['thread_id']}/artifacts/mnt/user-data/outputs/report.json")
        if artifact.is_success:
            result["grade"] = grade_artifact(artifact.text, expected)
            (self.output / f"{case_id}-{arm}-artifact.json").write_text(artifact.text, encoding="utf-8")
        else:
            result["grade"] = {"passed": False, "reason": "artifact_unavailable", "http_status": artifact.status_code}
        run = result.get("run") or {}
        result["budget_stopped"] = run.get("stop_reason") == "token_capped"
        result["run_succeeded"] = run.get("status") == "success"
        result["independent_pass"] = independent_completion(
            artifact_passed=result["grade"]["passed"], fixture_read=result["evidence"]["fixture_read_succeeded"], delivered=result["delivery"]["delivered"], run_status=run.get("status"), stop_reason=run.get("stop_reason")
        )
        return result

    async def paired(self, *, budget_only: bool = False) -> None:
        origin = f"bench-{self.session_id}-paired-origin"
        await self.request("POST", "/api/threads", json={"thread_id": origin})
        self.origin_ids.add(origin)
        self.plan["paired_setup"] = {"method": "production_repository_fixture_seed", "user_conversation_creation_bypassed_for_matched_study": True, "shared_owned_origin_thread_id": origin}
        write_json(self.output / "provenance.json", self.plan)
        cases = ["inventory"] if budget_only else ["inventory", "corrected-ledger", "missing-reviewer"]
        if budget_only and self.plan["token_budget"]["max_tokens"] > 2000:
            raise ValueError("Budget phase requires an explicit tiny per-run budget no larger than 2000")
        for index, case_id in enumerate(cases):
            arms = ["goal"] if budget_only else (["plain", "goal"] if index % 2 == 0 else ["goal", "plain"])
            for arm in arms:
                await self.guard(admit=True)
                due = datetime.now(UTC) + timedelta(seconds=self.plan["scheduler_min_delay"] + 3)
                task = await self.rows.seed_once(case_id, arm, self.plan, due_at=due, origin_thread_id=origin)
                self.task_ids.add(task["id"])
                started = time.monotonic()
                occurrence = await self.wait_occurrence(task["id"], 1)
                result = await self.observed_result(case_id, arm, occurrence, fixture(case_id)["expected"])
                result["elapsed_seconds"] = round(time.monotonic() - started, 3)
                if budget_only:
                    run = result.get("run") or {}
                    verdict = run.get("goal_verdict") or {}
                    result["token_cap_observed"] = run.get("stop_reason") == "token_capped" or verdict.get("stand_down_reason") == "token_capped"
                    from .budget_evidence import read_native_goal_evidence

                    result["goal_history"] = await read_native_goal_evidence(
                        Path(self.plan["sqlite_dir"]),
                        thread_id=occurrence["thread_id"],
                        objective=run.get("scheduled_goal_objective"),
                        mode=self.plan["checkpoint_channel_mode"],
                        snapshot_frequency=self.plan["checkpoint_snapshot_frequency"],
                    )
                    await asyncio.sleep(2)
                    later_messages = await self.request("GET", f"/api/threads/{occurrence['thread_id']}/runs/{occurrence['run_id']}/messages?limit=200")
                    current_goal = await self.request("GET", f"/api/threads/{occurrence['thread_id']}/goal")
                    result["goal_cleared"] = current_goal.get("goal") is None
                    result["no_later_continuation_observed"] = message_evidence(later_messages)["lead_model_turns"] == result["evidence"]["lead_model_turns"] and len(await self.rows.occurrences(task["id"])) == 1
                self.results.append(result)
                write_json(self.output / "results.json", self.results)
                assert_arm_installed(arm, result.get("run") or {})
                if budget_only and not result["token_cap_observed"]:
                    raise AssertionError("The scheduled goal occurrence did not record the tiny token-budget stop")
                if budget_only and (not result["goal_history"]["within_observed_limits"] or result["goal_history"]["maximum_observed_continuation_count"] != 0 or not result["goal_cleared"] or not result["no_later_continuation_observed"]):
                    raise AssertionError("The tiny-budget goal continued, remained installed or had unavailable continuation evidence")

    async def lifecycle(self) -> None:
        if not self.plan["conversation_reader_enabled"]:
            raise ValueError("Lifecycle phase requires the opt-in conversation reader")
        if self.interval < self.plan["scheduler_min_delay"]:
            raise ValueError("Lifecycle interval is below the configured scheduler floor")
        origin = f"bench-{self.session_id}-origin"
        await self.request("POST", "/api/threads", json={"thread_id": origin})
        self.origin_ids.add(origin)
        title = f"synthetic-continuity-{self.session_id}"
        prompt = (
            task_prompt("continuity", "report.json")
            + " If a previous conversation reference is present, read_conversation before reporting. Once a standing note selects develop and that report is written and presented, call stop_scheduled_task."
        )
        definition = {"title": title, "prompt": prompt, "schedule_type": "interval", "schedule_spec": {"every_seconds": self.interval}, "timezone": "UTC", "max_runs": 5, "context_mode": "fresh_thread_per_run"}
        create = await self.user_turn(
            origin,
            "Create exactly ONE scheduled task through schedule_task using this exact definition: "
            + json.dumps(definition)
            + ". No goal, no trial now and no extra tasks. Echo the task ID, next firing, end condition and stop instructions.",
        )
        tasks = await self.request("GET", f"/api/threads/{origin}/scheduled-tasks")
        found = [task for task in tasks if task.get("title") == title]
        self.task_ids.update(task["id"] for task in found)
        if len(found) != 1:
            raise AssertionError("The real conversation did not create exactly one scoped task")
        task = found[0]
        if task.get("origin_thread_id") != origin or task.get("context_mode") != "fresh_thread_per_run" or task.get("goal_objective") is not None:
            raise AssertionError("Conversation-created task binding or fresh context was not preserved")
        first = await self.wait_occurrence(task["id"], 1)
        first_result = await self.observed_result("continuity", "first", first, fixture("continuity")["expected"]["first"])
        self.results.append(first_result)
        if first["status"] != "success" or not first_result.get("independent_pass"):
            raise AssertionError("First occurrence failed artifact/source acceptance; stop before the paid note and second occurrence")
        await self.request("POST", f"/api/scheduled-tasks/{task['id']}/pause")
        note_run = await self.user_turn(origin, f"For task {task['id']}, add this exact standing note through schedule_task note: Use develop branch. Do not run a trial or resume it.")
        changed = await self.request("GET", f"/api/scheduled-tasks/{task['id']}")
        if "Use develop branch." not in (changed.get("standing_notes") or []):
            raise AssertionError("The explicit current-user note was not persisted verbatim")
        await self.guard(admit=True)
        await self.request("POST", f"/api/scheduled-tasks/{task['id']}/resume")
        second = await self.wait_occurrence(task["id"], 2)
        second_result = await self.observed_result("continuity", "second", second, fixture("continuity")["expected"]["second"])
        self.results.append(second_result)
        ended = await self.request("GET", f"/api/scheduled-tasks/{task['id']}")
        stop_recorded = second.get("stop_requested_run_id") == second.get("run_id")
        if ended.get("status") != "paused" or not stop_recorded:
            raise AssertionError("The scheduled agent did not durably stop its own schedule")
        deadline = time.monotonic() + self.interval + 3
        while time.monotonic() < deadline:
            await self.guard()
            if len(await self.rows.occurrences(task["id"])) != 2:
                raise AssertionError("An occurrence was dispatched after self-stop")
            await asyncio.sleep(0.5)
        passed = first_result.get("independent_pass") and second_result.get("independent_pass") and second_result["evidence"]["previous_reference_read_succeeded"] and stop_recorded and second["thread_id"] != first["thread_id"]
        write_json(
            self.output / "lifecycle.json",
            {
                "passed": bool(passed),
                "origin_thread_id": origin,
                "task_id": task["id"],
                "creation_run_id": create["run_id"],
                "note_run_id": note_run["run_id"],
                "self_stop_recorded": stop_recorded,
                "no_next_dispatch_observed": True,
                "restart_recovery": "not_exercised_by_this_phase",
            },
        )
        if not passed:
            raise AssertionError("Lifecycle artifact/source/reference acceptance failed")

    async def cleanup(self) -> None:
        """Preserve evidence while preventing disposable pilot work from recurring."""
        # A creation tool may commit before its interactive run fails. Discover
        # its task even when user_turn failed before returning the task ID.
        for origin in self.origin_ids:
            try:
                tasks = await self.request("GET", f"/api/threads/{origin}/scheduled-tasks")
                self.task_ids.update(task["id"] for task in tasks)
            except Exception as exc:
                self.results.append({"cleanup_origin_thread_id": origin, "cleanup_error_type": type(exc).__name__})
        for task_id in self.task_ids:
            try:
                task = await self.request("GET", f"/api/scheduled-tasks/{task_id}")
                if task.get("status") in {"completed", "failed", "cancelled", "paused"}:
                    continue
                for occurrence in await self.rows.occurrences(task_id):
                    if occurrence["status"] not in TERMINAL_RUN_STATUSES and occurrence.get("run_id"):
                        await self.request("POST", f"/api/threads/{occurrence['thread_id']}/runs/{occurrence['run_id']}/cancel?wait=true")
                response = await self.client.post(f"/api/scheduled-tasks/{task_id}/pause")
                if response.status_code not in {200, 404}:
                    self.results.append({"cleanup_task_id": task_id, "cleanup_status": response.status_code})
            except Exception as exc:
                self.results.append({"cleanup_task_id": task_id, "cleanup_error_type": type(exc).__name__})

    async def close(self) -> None:
        try:
            await self.cleanup()
            metrics = await self.rows.metrics()
            for row in metrics:
                try:
                    row["estimated_cost_usd"] = run_cost(row, self.plan)
                except ValueError as exc:
                    row["estimated_cost_usd"] = None
                    row["cost_accounting_error"] = str(exc)
            write_json(self.output / "run-rows.json", metrics)
            write_json(self.output / "results.json", self.results)
            write_json(
                self.output / "summary.json",
                {
                    "scheduled_results": len([result for result in self.results if "case_id" in result]),
                    "independent_passes": sum(bool(result.get("independent_pass")) for result in self.results),
                    "estimated_total_cost_usd": None if any(row["llm_call_count"] and row["estimated_cost_usd"] is None for row in metrics) else sum(row["estimated_cost_usd"] or 0 for row in metrics),
                    "small_synthetic_pilot": True,
                    "notifications_received": "not_tested",
                    "provider_billing": "not_verified",
                    **comparison_summary(self.results),
                },
            )
        finally:
            await self.client.aclose()
            await self.rows.close()


async def run_live(args: Any) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    plan = provenance(args.config, args.model)
    plan.update({"phase": args.phase, "max_cost_usd": args.max_cost, "reserve_usd_per_run": args.reserve_per_run, "run_timeout_seconds": args.timeout, "lifecycle_interval_seconds": args.interval})
    require_spend_reserve(0, args.reserve_per_run, args.max_cost)
    write_json(args.output / "provenance.json", plan)
    pilot = Pilot(base_url=args.base_url, plan=plan, output=args.output, max_cost=args.max_cost, reserve=args.reserve_per_run, timeout=args.timeout, interval=args.interval)
    try:
        await pilot.preflight()
        if args.phase == "lifecycle":
            await pilot.lifecycle()
        else:
            await pilot.paired(budget_only=args.phase == "budget")
    except Exception as exc:
        write_json(args.output / "failure.json", {"type": type(exc).__name__, "phase": args.phase, "message": str(exc)[:300], "time": datetime.now(UTC).isoformat()})
        raise
    finally:
        await pilot.close()
