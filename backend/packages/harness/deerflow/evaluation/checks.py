"""Deterministic checks for evaluation attempts."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from deerflow.evaluation.results import CheckResult, FailureKind
from deerflow.evaluation.schema import (
    CheckSpec,
    CommandExitZeroCheck,
    RunEventExistsCheck,
    WorkspaceFileContainsCheck,
    WorkspaceFileExistsCheck,
)


def run_check(
    check: CheckSpec,
    *,
    workspace_path: str | Path,
    run_events: Iterable[dict[str, Any]] | None = None,
) -> CheckResult:
    start = time.monotonic()
    try:
        if isinstance(check, WorkspaceFileExistsCheck):
            result = _check_workspace_file_exists(check, workspace_path=workspace_path)
        elif isinstance(check, WorkspaceFileContainsCheck):
            result = _check_workspace_file_contains(check, workspace_path=workspace_path)
        elif isinstance(check, CommandExitZeroCheck):
            result = _check_command_exit_zero(check, workspace_path=workspace_path)
        elif isinstance(check, RunEventExistsCheck):
            result = _check_run_event_exists(check, run_events=list(run_events or []))
        else:
            result = CheckResult(
                type=getattr(check, "type", "unknown"),
                passed=False,
                failure_kind=FailureKind.CONFIG.value,
                message=f"unsupported check type: {getattr(check, 'type', None)!r}",
            )
    except Exception as exc:
        result = CheckResult(
            type=getattr(check, "type", "unknown"),
            passed=False,
            failure_kind=FailureKind.CHECK_FAILED.value,
            message=str(exc),
        )
    duration_ms = int((time.monotonic() - start) * 1000)
    return result.model_copy(update={"duration_ms": duration_ms})


def run_checks(
    checks: Iterable[CheckSpec],
    *,
    workspace_path: str | Path,
    run_events: Iterable[dict[str, Any]] | None = None,
) -> list[CheckResult]:
    events = list(run_events or [])
    return [run_check(check, workspace_path=workspace_path, run_events=events) for check in checks]


def _check_workspace_file_exists(check: WorkspaceFileExistsCheck, *, workspace_path: str | Path) -> CheckResult:
    path = _workspace_child(workspace_path, check.path)
    passed = path.is_file()
    return CheckResult(
        type=check.type,
        passed=passed,
        failure_kind=None if passed else FailureKind.CHECK_FAILED.value,
        message="file exists" if passed else f"workspace file does not exist: {check.path}",
        metadata={"path": check.path},
    )


def _check_workspace_file_contains(check: WorkspaceFileContainsCheck, *, workspace_path: str | Path) -> CheckResult:
    path = _workspace_child(workspace_path, check.path)
    if not path.is_file():
        return CheckResult(
            type=check.type,
            passed=False,
            failure_kind=FailureKind.CHECK_FAILED.value,
            message=f"workspace file does not exist: {check.path}",
            metadata={"path": check.path},
        )

    text = path.read_text(encoding="utf-8")
    missing = [needle for needle in check.contains if needle not in text]
    forbidden = [needle for needle in check.not_contains if needle in text]
    passed = not missing and not forbidden
    message = "file content matched"
    if not passed:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if forbidden:
            parts.append(f"forbidden present: {', '.join(forbidden)}")
        message = "; ".join(parts)
    return CheckResult(
        type=check.type,
        passed=passed,
        failure_kind=None if passed else FailureKind.CHECK_FAILED.value,
        message=message,
        metadata={"path": check.path, "missing": missing, "forbidden_present": forbidden},
    )


def _check_command_exit_zero(check: CommandExitZeroCheck, *, workspace_path: str | Path) -> CheckResult:
    workspace = Path(workspace_path).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    env = _allowed_env(check.env_allowlist, check.env)
    try:
        completed = subprocess.run(
            check.command,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=check.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            type=check.type,
            passed=False,
            failure_kind=FailureKind.CHECK_TIMEOUT.value,
            message=f"command timed out after {check.timeout_seconds}s",
            stdout=_truncate(exc.stdout or "", check.stdout_limit),
            stderr=_truncate(exc.stderr or "", check.stderr_limit),
            metadata={"command": check.command, "timeout_seconds": check.timeout_seconds},
        )

    passed = completed.returncode == 0
    return CheckResult(
        type=check.type,
        passed=passed,
        failure_kind=None if passed else FailureKind.CHECK_FAILED.value,
        message="command exited zero" if passed else f"command exited with code {completed.returncode}",
        exit_code=completed.returncode,
        stdout=_truncate(completed.stdout, check.stdout_limit),
        stderr=_truncate(completed.stderr, check.stderr_limit),
        metadata={"command": check.command},
    )


def _check_run_event_exists(check: RunEventExistsCheck, *, run_events: list[dict[str, Any]]) -> CheckResult:
    matches = [event for event in run_events if event.get("event_type") == check.event_type and _metadata_matches(event.get("metadata") or {}, check.metadata or {})]
    passed = len(matches) >= check.min_count
    return CheckResult(
        type=check.type,
        passed=passed,
        failure_kind=None if passed else FailureKind.TRACE_GATE.value,
        message="run event matched" if passed else f"event {check.event_type!r} count {len(matches)} < {check.min_count}",
        metadata={"event_type": check.event_type, "count": len(matches), "min_count": check.min_count},
    )


def _workspace_child(workspace_path: str | Path, relative_path: str) -> Path:
    workspace = Path(workspace_path).resolve()
    candidate = (workspace / relative_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {relative_path}") from exc
    return candidate


def _allowed_env(allowlist: Iterable[str], explicit: dict[str, str]) -> dict[str, str]:
    allowed = set(allowlist)
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({key: value for key, value in explicit.items() if key in allowed})
    return env


def _truncate(value: str | bytes, limit: int) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _metadata_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())
