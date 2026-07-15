from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.evaluation.checks import run_check
from deerflow.evaluation.loader import normalize_suite_snapshot
from deerflow.evaluation.metrics import build_metrics_summary
from deerflow.evaluation.reports import build_evaluation_report, render_markdown_report
from deerflow.evaluation.results import FailureKind, normalize_attempt_result, normalize_failure_kind
from deerflow.evaluation.schema import EvalSuite
from deerflow.evaluation.workspace_seed import materialize_workspace_seed

LaunchRun = Callable[..., Awaitable[dict[str, Any]]]
RunEventsProvider = Callable[..., Awaitable[list[dict[str, Any]]]]
_INCOMPLETE_ATTEMPT_STATUSES = {"queued", "running"}
_RETRY_AFTER_INCOMPLETE_ATTEMPT_ERROR = "eval platform stale recovery: found incomplete attempt before retry"
_DEFAULT_EVAL_RECURSION_LIMIT = 300


class EvaluationService:
    def __init__(
        self,
        *,
        repository,
        launch_run: LaunchRun | None = None,
        run_events_provider: RunEventsProvider | None = None,
        workspaces_root: str | Path | None = None,
    ) -> None:
        self._repo = repository
        self._launch_run = launch_run
        self._run_events_provider = run_events_provider
        self._workspaces_root = Path(workspaces_root or ".deer-flow/evaluations/workspaces")

    async def create_eval_run(
        self,
        *,
        owner_id: str,
        suite_data: dict[str, Any],
        idempotency_key: str | None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        suite, snapshot, digest = normalize_suite_snapshot(suite_data)
        run_id = f"eval-run-{uuid.uuid4().hex}"
        expanded_items = self._expand_items(run_id, suite)
        created = await self._repo.create_run(
            run_id=run_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            suite_name=suite.name,
            suite_version=str(suite.version) if suite.version is not None else None,
            suite_digest=digest,
            suite_snapshot=snapshot,
            environment_fingerprint={
                "source": "gateway-eval-p0",
                "suite_item_count": len(suite.items),
                "variants": [variant.id for variant in suite.variants],
            },
            config=config or {},
            variants={variant.id: variant.model_dump(mode="json", exclude_none=True) for variant in suite.variants},
            total_items=len(expanded_items),
        )
        if created["id"] != run_id:
            return created
        for item in expanded_items:
            await self._repo.create_item(**item)
        return created

    async def run_eval(self, eval_run_id: str) -> dict[str, Any]:
        run = await self._repo.get_run(eval_run_id)
        if run is None:
            raise ValueError(f"Eval run {eval_run_id!r} not found")
        suite = EvalSuite.model_validate(run["suite_snapshot"])
        items = await self._repo.list_items(eval_run_id)
        for item_row in items:
            if item_row["status"] not in {"queued", "running"}:
                continue
            await self._execute_item(run, suite, item_row)

        all_attempt_rows = []
        for item_row in await self._repo.list_items(eval_run_id):
            all_attempt_rows.extend(await self._repo.list_attempts(item_row["id"]))
        attempt_results = [
            normalize_attempt_result(
                suite_item_id=self._suite_item_id_from_row(row, items),
                variant_id=self._variant_id_from_row(row, items),
                sample_index=self._sample_index_from_row(row, items),
                attempt_index=row["attempt_index"],
                status="passed" if row["status"] == "success" else "failed",
                thread_id=row.get("thread_id"),
                run_id=row.get("run_id"),
                workspace_path=row.get("workspace_path"),
                check_results=row.get("check_results_json") or [],
                run_event_summary=row.get("run_event_summary_json") or {},
                metrics=row.get("metrics_json") or {},
                failure_kind=row.get("failure_kind"),
                error=row.get("error"),
            )
            for row in all_attempt_rows
        ]
        metrics_summary = build_metrics_summary(suite, attempt_results)
        report = build_evaluation_report(
            suite,
            attempt_results,
            eval_run_id=eval_run_id,
            dataset_digest=run.get("suite_digest"),
            metrics_summary=metrics_summary,
        )
        status = "completed" if all(item["status"] == "passed" for item in await self._repo.list_items(eval_run_id)) else "failed"
        await self._repo.update_report(
            eval_run_id,
            summary=report.summary.model_dump(mode="json", exclude_none=True),
            effect_summary=report.effect_summary,
            comparison=(metrics_summary.comparison.model_dump(mode="json", exclude_none=True) if metrics_summary.comparison else {}),
            report_json=report.model_dump(mode="json", exclude_none=True),
            report_markdown=render_markdown_report(report),
            status=status,
            finished_at=datetime.now(UTC),
        )
        return await self._repo.get_run(eval_run_id) or run

    async def cancel_eval(self, eval_run_id: str, *, reason: str = "cancelled") -> bool:
        return await self._repo.update_report(
            eval_run_id,
            status="cancelled",
            error=reason,
            finished_at=datetime.now(UTC),
        )

    async def _execute_item(self, run: dict[str, Any], suite: EvalSuite, item_row: dict[str, Any]) -> dict[str, Any]:
        suite_item = next(item for item in suite.items if item.id == item_row["suite_item_id"])
        await self._close_incomplete_attempts_before_retry(item_row)
        attempt_id = f"eval-attempt-{uuid.uuid4().hex}"
        started_at = datetime.now(UTC)
        attempt_row = await self._repo.create_attempt(
            attempt_id=attempt_id,
            eval_run_id=run["id"],
            eval_run_item_id=item_row["id"],
            status="running",
            metadata={"execution_key": item_row["execution_key"]},
        )
        attempt_index = int(attempt_row["attempt_index"])

        launch_result: dict[str, Any] = {}
        workspace_path: Path | None = None
        try:
            workspace_ref = materialize_workspace_seed(
                suite_item.workspace_seed,
                suite_path=self._suite_path_for_seed(run, suite),
                workspaces_root=self._workspaces_root / run["id"],
                suite_name=suite.name,
                suite_item_id=suite_item.id,
                sample_index=int(item_row["sample_index"]),
                variant_id=item_row.get("variant_id"),
            )
            workspace_path = Path(workspace_ref.workspace_path)
            if self._launch_run is not None:
                launch_result = await self._launch_run(
                    thread_id=str(uuid.uuid4()),
                    assistant_id=None,
                    prompt=self._prompt_for_item(suite_item),
                    owner_user_id=run["owner_id"],
                    eval_workspace_path=str(workspace_path),
                    run_config=self._run_config_for_item(run),
                    metadata={
                        "eval_run_id": run["id"],
                        "eval_item_id": item_row["id"],
                        "eval_attempt_id": attempt_id,
                        "non_interactive": True,
                    },
                )

            run_events = await self._run_events_for_attempt(launch_result)
            check_results = [run_check(check, workspace_path=workspace_path, run_events=run_events) for check in suite_item.checks]
            passed = all(result.passed for result in check_results)
            status = "success" if passed else "failed"
            item_status = "passed" if passed else "failed"
            metrics = {"task_success": passed} if "task_success" in suite_item.metric_tags else {}
            event_summary = _run_event_summary(run_events)
            failure_kind = None if passed else _failure_kind_for_attempt(check_results, run_events=run_events)
            error = None if passed else _error_for_attempt(check_results, run_events=run_events, launch_result=launch_result)
            check_payload = [result.model_dump(mode="json", exclude_none=True) for result in check_results]
        except Exception as exc:
            status = "failed"
            item_status = "failed"
            metrics = {"task_success": False} if "task_success" in suite_item.metric_tags else {}
            event_summary = _run_event_summary([])
            failure_kind = normalize_failure_kind(status="error", error=exc)
            error = str(exc)
            check_payload = []

        workspace_path_text = str(workspace_path) if workspace_path is not None else None
        await self._repo.update_attempt_result(
            attempt_id,
            status=status,
            thread_id=launch_result.get("thread_id"),
            run_id=launch_result.get("run_id"),
            workspace_path=workspace_path_text,
            check_results=check_payload,
            metrics=metrics,
            run_event_summary=event_summary,
            failure_kind=failure_kind,
            error=error,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
        await self._repo.update_item_result(
            item_row["id"],
            status=item_status,
            selected_attempt_id=attempt_id,
            selected_attempt_index=attempt_index,
            thread_id=launch_result.get("thread_id"),
            run_id=launch_result.get("run_id"),
            workspace_path=workspace_path_text,
            check_results=check_payload,
            metrics=metrics,
            run_event_summary=event_summary,
            failure_kind=failure_kind,
            error=error,
            finished_at=datetime.now(UTC),
        )
        return await self._repo.list_attempts(item_row["id"])

    async def _close_incomplete_attempts_before_retry(self, item_row: dict[str, Any]) -> None:
        existing_attempts = await self._repo.list_attempts(item_row["id"])
        if not any(attempt["status"] in _INCOMPLETE_ATTEMPT_STATUSES for attempt in existing_attempts):
            return
        await self._repo.fail_incomplete_attempts_for_item(
            item_row["id"],
            failure_kind=FailureKind.PLATFORM_DEFECT.value,
            error=_RETRY_AFTER_INCOMPLETE_ATTEMPT_ERROR,
            now=datetime.now(UTC),
        )

    def _expand_items(self, run_id: str, suite: EvalSuite) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        for suite_item in suite.items:
            variant_ids = suite_item.variants or [variant.id for variant in suite.variants]
            for variant_id in variant_ids:
                for sample_index in range(suite_item.repeat):
                    execution_key = f"{run_id}:{suite_item.id}:{variant_id}:{sample_index}"
                    expanded.append(
                        {
                            "item_id": f"eval-item-{uuid.uuid4().hex}",
                            "eval_run_id": run_id,
                            "suite_item_id": suite_item.id,
                            "variant_id": variant_id,
                            "sample_index": sample_index,
                            "execution_key": execution_key,
                            "checks": [check.model_dump(mode="json", exclude_none=True) for check in suite_item.checks],
                        }
                    )
        return expanded

    async def _run_events_for_attempt(self, launch_result: dict[str, Any]) -> list[dict[str, Any]]:
        run_events = launch_result.get("run_events")
        if isinstance(run_events, list) and run_events:
            return run_events
        if self._run_events_provider is None:
            return run_events if isinstance(run_events, list) else []
        thread_id = launch_result.get("thread_id")
        run_id = launch_result.get("run_id")
        if not thread_id or not run_id:
            return run_events if isinstance(run_events, list) else []
        return await self._run_events_provider(thread_id=thread_id, run_id=run_id)

    @staticmethod
    def _suite_path_for_seed(run: dict[str, Any], suite: EvalSuite) -> Path:
        config = run.get("config_json") if isinstance(run.get("config_json"), dict) else {}
        for key in ("suite_path", "suite_file", "suite_source_path"):
            value = config.get(key)
            if isinstance(value, str) and value:
                return Path(value)
        return Path.cwd() / f"{suite.name}.yaml"

    @staticmethod
    def _prompt_for_item(suite_item: Any) -> str:
        if suite_item.input is not None:
            return suite_item.input.prompt
        if suite_item.turns:
            return suite_item.turns[0].user
        if suite_item.sessions:
            return suite_item.sessions[0].steps[0].user
        return ""

    @staticmethod
    def _run_config_for_item(run: dict[str, Any]) -> dict[str, Any]:
        config_json = run.get("config_json") if isinstance(run.get("config_json"), dict) else {}
        recursion_limit = config_json.get("recursion_limit", _DEFAULT_EVAL_RECURSION_LIMIT)
        return {"recursion_limit": recursion_limit}

    @staticmethod
    def _suite_item_id_from_row(attempt_row: dict[str, Any], item_rows: list[dict[str, Any]]) -> str:
        item = next(row for row in item_rows if row["id"] == attempt_row["eval_run_item_id"])
        return item["suite_item_id"]

    @staticmethod
    def _variant_id_from_row(attempt_row: dict[str, Any], item_rows: list[dict[str, Any]]) -> str:
        item = next(row for row in item_rows if row["id"] == attempt_row["eval_run_item_id"])
        return item["variant_id"]

    @staticmethod
    def _sample_index_from_row(attempt_row: dict[str, Any], item_rows: list[dict[str, Any]]) -> int:
        item = next(row for row in item_rows if row["id"] == attempt_row["eval_run_item_id"])
        return int(item["sample_index"])


def _run_event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type:
            event_types[event_type] = event_types.get(event_type, 0) + 1
    return {"event_count": len(events), "event_types": event_types}


def _failure_kind_for_attempt(check_results, *, run_events: list[dict[str, Any]]) -> str | None:
    if _run_event_evidence_missing(check_results, run_events=run_events):
        return FailureKind.PLATFORM_EVIDENCE_MISSING.value
    llm_error = _llm_error_text(run_events)
    if llm_error:
        return normalize_failure_kind(status="error", error=llm_error)
    return normalize_failure_kind(status="failed", check_results=check_results)


def _error_for_attempt(check_results, *, run_events: list[dict[str, Any]], launch_result: dict[str, Any]) -> str:
    messages = [result.message for result in check_results if not result.passed]
    if _run_event_evidence_missing(check_results, run_events=run_events):
        run_id = launch_result.get("run_id") or "unknown"
        messages.insert(0, f"run_events evidence missing for run_id={run_id}")
    elif _llm_error_text(run_events):
        messages.insert(0, "llm.error event present before agent response")
    return "; ".join(messages)


def _run_event_evidence_missing(check_results, *, run_events: list[dict[str, Any]]) -> bool:
    if run_events:
        return False
    return any(result.type == "run_event_exists" and not result.passed for result in check_results)


def _llm_error_text(run_events: list[dict[str, Any]]) -> str | None:
    for event in run_events:
        if event.get("event_type") != "llm.error":
            continue
        parts: list[str] = []
        for key in ("error", "content", "payload"):
            value = event.get(key)
            if value:
                parts.append(str(value))
        metadata = event.get("metadata") or {}
        if isinstance(metadata, dict):
            for key in ("error", "message", "error_type", "status"):
                value = metadata.get(key)
                if value:
                    parts.append(str(value))
        return " ".join(parts) or "llm.error"
    return None
