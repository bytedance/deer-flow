"""Opt-in live smoke checks for model/tool compatibility.

This script intentionally calls real model APIs. It is not part of the normal
pytest suite and should be run manually when validating provider compatibility.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = BACKEND_ROOT / "packages" / "harness"
for import_root in (BACKEND_ROOT, HARNESS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

RESULTS_DIR = BACKEND_ROOT / ".deer-flow" / "model-compat-runs"
EXPECTED_WRITE_CONTENT = "hello deerflow model compatibility"
EXPECTED_READBACK_CONTENT = "readback-ok"
EXPECTED_RECOVERY_CONTENT = "recovered"


class CaseTimeoutError(TimeoutError):
    """Raised when a live smoke case exceeds its wall-clock budget."""


@dataclass(frozen=True)
class SmokeCase:
    name: str
    prompt: str


@dataclass
class CaseResult:
    model: str
    case: str
    status: str
    reason: str = ""
    duration_ms: int = 0
    first_content_ms: int | None = None
    thread_id: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    final_text: str = ""
    usage: dict[str, Any] | None = None
    exception: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "case": self.case,
            "status": self.status,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "first_content_ms": self.first_content_ms,
            "thread_id": self.thread_id,
            "tool_calls": self.tool_calls or [],
            "tool_results": self.tool_results or [],
            "final_text": self.final_text,
            "usage": self.usage or {},
            "exception": self.exception,
        }


SMOKE_CASES: dict[str, SmokeCase] = {
    "basic_chat": SmokeCase(
        name="basic_chat",
        prompt="Reply with exactly: MODEL_COMPAT_OK",
    ),
    "streaming_health": SmokeCase(
        name="streaming_health",
        prompt="Count from 1 to 5, one number per line.",
    ),
    "write_file_required_args": SmokeCase(
        name="write_file_required_args",
        prompt=(f"Use the write_file tool to create /mnt/user-data/outputs/model_compat_write.txt with exactly this content: {EXPECTED_WRITE_CONTENT}"),
    ),
    "write_then_read": SmokeCase(
        name="write_then_read",
        prompt=("Step 1: Use write_file to write 'readback-ok' to /mnt/user-data/outputs/model_compat_readback.txt. Step 2: Use read_file to read that file back. Step 3: Reply with the content you read."),
    ),
    "tool_error_recovery": SmokeCase(
        name="tool_error_recovery",
        prompt=(
            "First use read_file to read /mnt/user-data/outputs/definitely_missing_model_compat.txt. "
            "If that fails, use write_file to create /mnt/user-data/outputs/model_compat_recovered.txt "
            "with exactly this content: recovered. Then reply DONE."
        ),
    ),
}


@contextmanager
def case_timeout(seconds: int) -> Iterator[None]:
    """Apply a coarse wall-clock timeout around one live case on POSIX."""
    if seconds <= 0 or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise CaseTimeoutError(f"case timed out after {seconds}s")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def event_tool_calls(events: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        if event.type != "messages-tuple":
            continue
        data = event.data
        if data.get("type") != "ai":
            continue
        for tool_call in data.get("tool_calls") or []:
            if tool_call.get("name"):
                calls.append(dict(tool_call))
    return calls


def event_tool_results(events: list[Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in events:
        if event.type != "messages-tuple":
            continue
        data = event.data
        if data.get("type") == "tool":
            results.append(dict(data))
    return results


def final_ai_text(events: list[Any]) -> str:
    chunks_by_id: dict[str, list[str]] = {}
    last_id = ""
    for event in events:
        if event.type != "messages-tuple":
            continue
        data = event.data
        if data.get("type") != "ai":
            continue
        content = data.get("content")
        if not content:
            continue
        msg_id = data.get("id") or ""
        chunks_by_id.setdefault(msg_id, []).append(str(content))
        last_id = msg_id
    return "".join(chunks_by_id.get(last_id, []))


def first_content_latency_ms(events_with_time: list[tuple[int, Any]]) -> int | None:
    if not events_with_time:
        return None
    for elapsed_ms, event in events_with_time:
        if event.type != "messages-tuple":
            continue
        data = event.data
        if data.get("type") == "ai" and data.get("content"):
            return elapsed_ms
    return None


def end_usage(events: list[Any]) -> dict[str, Any]:
    for event in reversed(events):
        if event.type == "end":
            return dict(event.data.get("usage") or {})
    return {}


def find_tool_call(tool_calls: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for tool_call in tool_calls:
        if tool_call.get("name") == name:
            return tool_call
    return None


def find_tool_calls(tool_calls: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [tool_call for tool_call in tool_calls if tool_call.get("name") == name]


def required_arg_failure(tool_call: dict[str, Any] | None, required: list[str]) -> str | None:
    if tool_call is None:
        return "no_tool_call"
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return "tool_args_not_object"
    for key in required:
        value = args.get(key)
        if value is None or value == "":
            return f"missing_{key}_arg"
    return None


def classify_tool_failure(result: CaseResult, tool_call: dict[str, Any] | None, required: list[str]) -> str:
    diagnostic_parts = [result.exception or "", result.final_text]
    diagnostic_parts.extend(item.get("content", "") for item in result.tool_results or [])
    diagnostic = "\n".join(diagnostic_parts).lower()
    if looks_like_provider_error(diagnostic):
        return "provider_error"
    for key in required:
        if key in diagnostic and ("field required" in diagnostic or "missing" in diagnostic or "required" in diagnostic):
            return f"missing_{key}_arg"
    return required_arg_failure(tool_call, required) or "file_not_found"


def looks_like_provider_error(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "llm call failed",
        "error code:",
        "api key not found",
        "invalid api key",
        "multiple retries",
        "model_price_error",
        "model_not_supported",
        "not supported",
        "provider is temporarily unavailable",
        "temporarily unavailable",
        "bad_response_status_code",
        "authenticationerror",
        "ratelimiterror",
        "internalservererror",
        "invalid_argument",
    )
    return any(marker in lowered for marker in markers)


def result_has_provider_error(result: CaseResult) -> bool:
    diagnostic_parts = [result.exception or "", result.final_text]
    diagnostic_parts.extend(item.get("content", "") for item in result.tool_results or [])
    return looks_like_provider_error("\n".join(diagnostic_parts))


def artifact_text(client: Any, thread_id: str, filename: str) -> str:
    content, _mime = client.get_artifact(thread_id, f"mnt/user-data/outputs/{filename}")
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return str(content)


def collect_events(client: Any, case: SmokeCase, thread_id: str, timeout_seconds: int, recursion_limit: int) -> tuple[list[Any], list[tuple[int, Any]], Exception | None, int]:
    events: list[Any] = []
    timed_events: list[tuple[int, Any]] = []
    started = time.monotonic()
    exception: Exception | None = None
    try:
        with case_timeout(timeout_seconds):
            for event in client.stream(case.prompt, thread_id=thread_id, recursion_limit=recursion_limit):
                elapsed_ms = int((time.monotonic() - started) * 1000)
                events.append(event)
                timed_events.append((elapsed_ms, event))
    except Exception as exc:  # noqa: BLE001 - captured for diagnostic reporting.
        exception = exc
    duration_ms = int((time.monotonic() - started) * 1000)
    return events, timed_events, exception, duration_ms


def base_result(model: str, case: SmokeCase, thread_id: str, events: list[Any], timed_events: list[tuple[int, Any]], exception: Exception | None, duration_ms: int) -> CaseResult:
    return CaseResult(
        model=model,
        case=case.name,
        status="PASS",
        duration_ms=duration_ms,
        first_content_ms=first_content_latency_ms(timed_events),
        thread_id=thread_id,
        tool_calls=event_tool_calls(events),
        tool_results=event_tool_results(events),
        final_text=final_ai_text(events),
        usage=end_usage(events),
        exception="".join(traceback.format_exception_only(type(exception), exception)).strip() if exception else None,
    )


def analyze_basic_chat(result: CaseResult, _client: Any) -> CaseResult:
    if result.exception:
        result.status = "FAIL"
        result.reason = "exception"
    elif result_has_provider_error(result):
        result.status = "FAIL"
        result.reason = "provider_error"
    elif "MODEL_COMPAT_OK" not in result.final_text:
        result.status = "FAIL"
        result.reason = "expected_text_missing"
    return result


def analyze_streaming_health(result: CaseResult, _client: Any) -> CaseResult:
    if result.exception:
        result.status = "FAIL"
        result.reason = "exception"
    elif result_has_provider_error(result):
        result.status = "FAIL"
        result.reason = "provider_error"
    elif result.first_content_ms is None:
        result.status = "FAIL"
        result.reason = "no_ai_content_event"
    return result


def analyze_write_file_required_args(result: CaseResult, client: Any) -> CaseResult:
    write_call = find_tool_call(result.tool_calls or [], "write_file")
    if result_has_provider_error(result):
        result.status = "FAIL"
        result.reason = "provider_error"
        return result
    if write_call is None:
        result.status = "FAIL"
        result.reason = "no_write_file_tool_call"
        return result
    if result.exception:
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, write_call, ["path", "content"])
        return result
    try:
        content = artifact_text(client, result.thread_id, "model_compat_write.txt")
    except Exception as exc:  # noqa: BLE001 - diagnostic result, not library logic.
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, write_call, ["path", "content"])
        result.exception = result.exception or "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return result
    if content != EXPECTED_WRITE_CONTENT:
        result.status = "FAIL"
        result.reason = "content_mismatch"
    return result


def analyze_write_then_read(result: CaseResult, client: Any) -> CaseResult:
    write_call = find_tool_call(result.tool_calls or [], "write_file")
    read_call = find_tool_call(result.tool_calls or [], "read_file")
    if result_has_provider_error(result):
        result.status = "FAIL"
        result.reason = "provider_error"
        return result
    if write_call is None:
        result.status = "FAIL"
        result.reason = "no_write_file_tool_call"
        return result
    if read_call is None:
        result.status = "FAIL"
        result.reason = "no_read_file_tool_call"
        return result
    if result.exception:
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, write_call, ["path", "content"])
        return result
    try:
        content = artifact_text(client, result.thread_id, "model_compat_readback.txt")
    except Exception as exc:  # noqa: BLE001
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, write_call, ["path", "content"])
        result.exception = result.exception or "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return result
    if content != EXPECTED_READBACK_CONTENT:
        result.status = "FAIL"
        result.reason = "content_mismatch"
    elif EXPECTED_READBACK_CONTENT not in result.final_text and not any(EXPECTED_READBACK_CONTENT in item.get("content", "") for item in result.tool_results or []):
        result.status = "FAIL"
        result.reason = "readback_not_reported"
    return result


def analyze_tool_error_recovery(result: CaseResult, client: Any) -> CaseResult:
    read_call = find_tool_call(result.tool_calls or [], "read_file")
    write_calls = find_tool_calls(result.tool_calls or [], "write_file")
    if result_has_provider_error(result):
        result.status = "FAIL"
        result.reason = "provider_error"
        return result
    if read_call is None:
        result.status = "FAIL"
        result.reason = "no_read_file_tool_call"
        return result
    if not write_calls:
        result.status = "FAIL"
        result.reason = "no_recovery_write_file_tool_call"
        return result
    recovery_write = write_calls[-1]
    if result.exception:
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, recovery_write, ["path", "content"])
        return result
    try:
        content = artifact_text(client, result.thread_id, "model_compat_recovered.txt")
    except Exception as exc:  # noqa: BLE001
        result.status = "FAIL"
        result.reason = classify_tool_failure(result, recovery_write, ["path", "content"])
        result.exception = result.exception or "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return result
    if content != EXPECTED_RECOVERY_CONTENT:
        result.status = "FAIL"
        result.reason = "content_mismatch"
    elif "DONE" not in result.final_text:
        result.status = "FAIL"
        result.reason = "done_not_reported"
    return result


ANALYZERS = {
    "basic_chat": analyze_basic_chat,
    "streaming_health": analyze_streaming_health,
    "write_file_required_args": analyze_write_file_required_args,
    "write_then_read": analyze_write_then_read,
    "tool_error_recovery": analyze_tool_error_recovery,
}


def run_case(client: Any, model: str, case: SmokeCase, timeout_seconds: int, recursion_limit: int) -> CaseResult:
    thread_id = f"model-compat-{case.name}-{uuid.uuid4().hex[:8]}"
    events, timed_events, exception, duration_ms = collect_events(client, case, thread_id, timeout_seconds, recursion_limit)
    result = base_result(model, case, thread_id, events, timed_events, exception, duration_ms)
    return ANALYZERS[case.name](result, client)


def print_table(results: list[CaseResult]) -> None:
    rows = [
        ("model", "case", "status", "reason", "duration_ms", "first_content_ms"),
        *[
            (
                result.model,
                result.case,
                result.status,
                result.reason,
                str(result.duration_ms),
                "" if result.first_content_ms is None else str(result.first_content_ms),
            )
            for result in results
        ],
    ]
    widths = [max(len(row[idx]) for row in rows) for idx in range(len(rows[0]))]
    for idx, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)))
        if idx == 0:
            print("  ".join("-" * width for width in widths))


def write_results(results: list[CaseResult], requested_models: list[str], selected_cases: list[str], output_json: str | None) -> Path:
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "models": requested_models,
        "cases": selected_cases,
        "results": [result.to_dict() for result in results],
    }
    if output_json:
        path = Path(output_json)
    else:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = RESULTS_DIR / f"model-compat-{timestamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_models(raw_models: list[str]) -> list[str]:
    if raw_models:
        return raw_models
    env_models = parse_csv(os.getenv("DEERFLOW_COMPAT_MODELS"))
    if env_models:
        return env_models
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run opt-in live model compatibility smoke checks.")
    parser.add_argument("--models", help="Comma-separated model names from config.yaml. Defaults to DEERFLOW_COMPAT_MODELS.")
    parser.add_argument("--cases", help=f"Comma-separated cases. Available: {', '.join(SMOKE_CASES)}")
    parser.add_argument("--timeout", type=int, default=240, help="Per-case wall-clock timeout in seconds. Use 0 to disable.")
    parser.add_argument("--recursion-limit", type=int, default=40, help="LangGraph recursion limit per case.")
    parser.add_argument("--thinking-enabled", action="store_true", help="Enable thinking mode for the smoke run.")
    parser.add_argument("--output-json", help="Optional output JSON path. Defaults to backend/.deer-flow/model-compat-runs/.")
    parser.add_argument("--list-models", action="store_true", help="List configured model names and exit without live calls.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from deerflow.client import DeerFlowClient

    probe_client = DeerFlowClient(thinking_enabled=False, available_skills=set())
    configured_models = {item["name"] for item in probe_client.list_models()["models"]}

    if args.list_models:
        for model_name in sorted(configured_models):
            print(model_name)
        return 0

    requested_models = resolve_models(parse_csv(args.models))
    if not requested_models:
        print("No models provided. Use --models or DEERFLOW_COMPAT_MODELS.", file=sys.stderr)
        print("Configured models:", ", ".join(sorted(configured_models)) or "(none)", file=sys.stderr)
        return 2

    selected_cases = parse_csv(args.cases) or list(SMOKE_CASES)
    unknown_cases = [name for name in selected_cases if name not in SMOKE_CASES]
    if unknown_cases:
        print(f"Unknown case(s): {', '.join(unknown_cases)}", file=sys.stderr)
        return 2

    results: list[CaseResult] = []
    for model in requested_models:
        if model not in configured_models:
            results.append(
                CaseResult(
                    model=model,
                    case="config",
                    status="FAIL",
                    reason="model_not_configured",
                )
            )
            continue

        client = DeerFlowClient(
            model_name=model,
            thinking_enabled=args.thinking_enabled,
            available_skills=set(),
        )
        for case_name in selected_cases:
            print(f"\n>>> {model} / {case_name}", flush=True)
            result = run_case(
                client,
                model,
                SMOKE_CASES[case_name],
                timeout_seconds=args.timeout,
                recursion_limit=args.recursion_limit,
            )
            results.append(result)
            print(f"{result.status}: {result.reason or 'ok'} ({result.duration_ms} ms)", flush=True)

    print()
    print_table(results)
    path = write_results(results, requested_models, selected_cases, args.output_json)
    print(f"\nWrote JSON results: {path}")
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
