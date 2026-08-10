"""Offline-testable core for the opt-in model/tool compatibility smoke runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Protocol

LIVE_OPT_IN = "DEER_FLOW_RUN_LIVE_TESTS"


class CaseName(StrEnum):
    BASIC_CHAT = "basic_chat"
    STREAMING = "streaming"
    WRITE_FILE = "write_file"
    WRITE_READ = "write_then_read"
    TOOL_ERROR_RECOVERY = "tool_error_recovery"


class ErrorCategory(StrEnum):
    CONFIGURATION = "configuration_error"
    MODEL_INCOMPATIBLE = "model_incompatible"
    TOOL_FAILURE = "tool_failure"
    RUNNER = "runner_error"


class ExitCode(IntEnum):
    OK = 0
    CHECK_FAILED = 1
    CONFIGURATION = 2
    RUNNER_ERROR = 3


class ConfigurationError(RuntimeError):
    """A safe-to-report invocation or local configuration failure."""


@dataclass(frozen=True)
class CaseSpec:
    name: CaseName
    prompt: str
    artifact_path: str | None = None
    expected_artifact: bytes | None = None


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        CaseName.BASIC_CHAT,
        "Reply with exactly DEERFLOW_SMOKE_CHAT_OK and do not call any tools.",
    ),
    CaseSpec(
        CaseName.STREAMING,
        "Reply with a short sentence beginning with DEERFLOW_SMOKE_STREAM_OK. Do not call tools.",
    ),
    CaseSpec(
        CaseName.WRITE_FILE,
        "Use write_file to create /mnt/user-data/outputs/model_compat_write.txt containing exactly DEERFLOW_SMOKE_WRITE_OK, then confirm completion.",
        "/mnt/user-data/outputs/model_compat_write.txt",
        b"DEERFLOW_SMOKE_WRITE_OK",
    ),
    CaseSpec(
        CaseName.WRITE_READ,
        "First use write_file to create /mnt/user-data/outputs/model_compat_chain.txt containing exactly DEERFLOW_SMOKE_CHAIN_OK. Then use read_file to read that same file before replying with what you read.",
        "/mnt/user-data/outputs/model_compat_chain.txt",
        b"DEERFLOW_SMOKE_CHAIN_OK",
    ),
    CaseSpec(
        CaseName.TOOL_ERROR_RECOVERY,
        "First use read_file on "
        "/mnt/user-data/outputs/definitely_missing_model_compat_file.txt and observe the "
        "expected error. Then recover by using write_file to create "
        "/mnt/user-data/outputs/model_compat_recovery.txt containing exactly "
        "DEERFLOW_SMOKE_RECOVERY_OK, and confirm recovery.",
        "/mnt/user-data/outputs/model_compat_recovery.txt",
        b"DEERFLOW_SMOKE_RECOVERY_OK",
    ),
)


@dataclass
class ToolCall:
    name: str
    call_id: str | None
    args: dict[str, Any]
    sequence: int


@dataclass
class ToolResult:
    name: str
    call_id: str | None
    content: str
    status: str
    error_type: str | None
    sequence: int
    message_id: str | None = None


@dataclass
class Observation:
    text_chunks: list[str] = field(default_factory=list)
    first_content_ms: float | None = None
    ended: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    provider_fallback: bool = False
    provider_error_type: str | None = None

    @property
    def text(self) -> str:
        return "".join(self.text_chunks)


@dataclass
class SmokeResult:
    model: str
    case: CaseName
    passed: bool
    detail: str
    category: ErrorCategory | None = None
    first_content_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["model"] = redact_text(self.model)
        data["detail"] = redact_text(self.detail)
        data["case"] = self.case.value
        data["category"] = self.category.value if self.category else None
        return data


class Runtime(Protocol):
    def list_models(self) -> list[str]: ...

    def run_case(self, model: str, case: CaseSpec, thread_id: str, user_id: str) -> SmokeResult: ...

    def cleanup(self, thread_id: str, user_id: str) -> None: ...


_BEARER_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_URL_USERINFO_RE = re.compile(r"([a-zA-Z][\w+.-]*://)([^/?#\s@]+)@")
_NAMED_SECRET_RE = re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|secret|password|authorization)\s*[=:]\s*)([^\s&]+)")
_SECRET_ENV_NAME_RE = re.compile(r"(?i)(api[_-]?key|access[_-]?key|token|secret|password|passwd|credential|authorization|cookie|dsn)")


def redact_text(value: object) -> str:
    """Remove common credential forms from free-form runner output."""
    text = str(value)
    text = _URL_USERINFO_RE.sub(r"\1<redacted>@", text)
    text = _BEARER_RE.sub(r"\1<redacted>", text)
    text = _NAMED_SECRET_RE.sub(r"\1<redacted>", text)
    text = _OPENAI_KEY_RE.sub("sk-<redacted>", text)
    for name, secret in os.environ.items():
        if _SECRET_ENV_NAME_RE.search(name) and len(secret) >= 6:
            text = text.replace(secret, "<redacted>")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run explicit live smoke checks against configured DeerFlow models.",
        epilog="WARNING: smoke checks call real models and may incur API charges.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--model", dest="models", action="append", help="Configured model name; repeat to test multiple models.")
    selection.add_argument("--all-models", action="store_true", help="Test every configured model.")
    selection.add_argument("--list-models", action="store_true", help="List configured model names without calling a model.")
    parser.add_argument("--case", dest="cases", action="append", choices=[case.value for case in CaseName], help="Run only this case; repeat to select several.")
    parser.add_argument("--json-output", type=Path, help="Write the redacted result report to this path.")
    parser.add_argument("--keep-workspaces", action="store_true", help="Keep isolated smoke workspaces for debugging.")
    return parser


def select_models(requested: list[str], all_models: bool, configured: list[str]) -> list[str]:
    configured_unique = list(dict.fromkeys(configured))
    if all_models:
        if not configured_unique:
            raise ValueError("no models are configured")
        return configured_unique

    selected = list(dict.fromkeys(requested))
    unknown = [name for name in selected if name not in configured_unique]
    if unknown:
        raise ValueError(f"unknown model(s): {', '.join(unknown)}")
    return selected


def _message_meta(data: Mapping[str, Any]) -> Mapping[str, Any]:
    additional = data.get("additional_kwargs")
    if not isinstance(additional, Mapping):
        return {}
    meta = additional.get("deerflow_tool_meta")
    return meta if isinstance(meta, Mapping) else {}


def _upsert_tool_result(results: list[ToolResult], data: Mapping[str, Any], sequence: int) -> None:
    message_id = data.get("id")
    call_id = data.get("tool_call_id")
    existing = next(
        (result for result in results if (message_id and result.message_id == message_id) or (call_id and result.call_id == call_id)),
        None,
    )
    meta = _message_meta(data)
    content = str(data.get("content") or "")
    status = str(meta.get("status") or ("error" if content.lstrip().lower().startswith("error:") else "success"))
    error_type = str(meta["error_type"]) if meta.get("error_type") else None
    if existing:
        existing.content = content or existing.content
        existing.status = status
        existing.error_type = error_type
        return
    results.append(
        ToolResult(
            name=str(data.get("name") or ""),
            call_id=str(call_id) if call_id else None,
            content=content,
            status=status,
            error_type=error_type,
            sequence=sequence,
            message_id=str(message_id) if message_id else None,
        )
    )


def observe_events(events: Iterable[Any], *, clock: Callable[[], float] = time.monotonic) -> Observation:
    started = clock()
    observation = Observation()
    sequence = 0
    for event in events:
        sequence += 1
        event_type = getattr(event, "type", None)
        data = getattr(event, "data", {})
        if not isinstance(data, Mapping):
            continue
        if event_type == "end":
            observation.ended = True
            continue
        if event_type == "values":
            messages = data.get("messages") or []
            for message in messages:
                if isinstance(message, Mapping) and message.get("type") == "tool":
                    _upsert_tool_result(observation.tool_results, message, sequence)
            continue
        if event_type != "messages-tuple":
            continue

        if data.get("type") == "ai":
            content = str(data.get("content") or "")
            if content:
                if observation.first_content_ms is None:
                    observation.first_content_ms = (clock() - started) * 1000
                observation.text_chunks.append(content)
            additional = data.get("additional_kwargs")
            if isinstance(additional, Mapping) and additional.get("deerflow_error_fallback") is True:
                observation.provider_fallback = True
                if additional.get("error_type"):
                    observation.provider_error_type = str(additional["error_type"])
            for raw_call in data.get("tool_calls") or []:
                if not isinstance(raw_call, Mapping):
                    continue
                args = raw_call.get("args")
                observation.tool_calls.append(
                    ToolCall(
                        name=str(raw_call.get("name") or ""),
                        call_id=str(raw_call["id"]) if raw_call.get("id") else None,
                        args=dict(args) if isinstance(args, Mapping) else {},
                        sequence=sequence,
                    )
                )
        elif data.get("type") == "tool":
            _upsert_tool_result(observation.tool_results, data, sequence)
    return observation


def _failure(model: str, case: CaseName, category: ErrorCategory, detail: str, observation: Observation) -> SmokeResult:
    return SmokeResult(
        model=model,
        case=case,
        passed=False,
        category=category,
        detail=detail,
        first_content_ms=observation.first_content_ms,
    )


def _calls(observation: Observation, name: str) -> list[ToolCall]:
    return [call for call in observation.tool_calls if call.name == name]


def _result_for(observation: Observation, call: ToolCall) -> ToolResult | None:
    return next((result for result in observation.tool_results if result.call_id == call.call_id or (not call.call_id and result.name == call.name)), None)


def evaluate_case(
    model: str,
    case: CaseName,
    observation: Observation,
    *,
    artifact: bytes | None = None,
    artifact_error: str | None = None,
) -> SmokeResult:
    if observation.provider_fallback:
        detail = f"model provider fallback ({observation.provider_error_type or 'unknown error'})"
        return _failure(model, case, ErrorCategory.CONFIGURATION, detail, observation)

    if case is CaseName.BASIC_CHAT:
        if "DEERFLOW_SMOKE_CHAT_OK" not in observation.text:
            return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "expected basic-chat marker was not returned", observation)
    elif case is CaseName.STREAMING:
        if observation.first_content_ms is None:
            return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "stream produced no content", observation)
        if not observation.ended:
            return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "stream ended without an end event", observation)
    else:
        write_calls = _calls(observation, "write_file")
        if not write_calls:
            return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "model did not call write_file", observation)

        for call in write_calls:
            result = _result_for(observation, call)
            if result is not None and result.status == "error":
                return _failure(model, case, ErrorCategory.TOOL_FAILURE, f"write_file failed ({result.error_type or 'unknown error'})", observation)

        if case is CaseName.WRITE_READ:
            read_calls = _calls(observation, "read_file")
            if not read_calls or read_calls[-1].sequence <= write_calls[0].sequence:
                return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "model did not call read_file after write_file", observation)
            read_result = _result_for(observation, read_calls[-1])
            if read_result is not None and read_result.status == "error":
                return _failure(model, case, ErrorCategory.TOOL_FAILURE, f"read_file failed ({read_result.error_type or 'unknown error'})", observation)
            if read_result is None or "DEERFLOW_SMOKE_CHAIN_OK" not in read_result.content:
                return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "read_file did not return the expected marker", observation)

        if case is CaseName.TOOL_ERROR_RECOVERY:
            read_calls = _calls(observation, "read_file")
            if not read_calls:
                return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "model did not attempt the expected failing read_file call", observation)
            read_result = _result_for(observation, read_calls[0])
            if read_result is None or read_result.status != "error":
                return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "expected read_file failure was not observed", observation)
            if write_calls[-1].sequence == read_calls[0].sequence:
                return _failure(
                    model,
                    case,
                    ErrorCategory.MODEL_INCOMPATIBLE,
                    "model issued read_file and write_file in parallel instead of recovering after the tool error",
                    observation,
                )
            if write_calls[-1].sequence < read_calls[0].sequence:
                return _failure(model, case, ErrorCategory.MODEL_INCOMPATIBLE, "model did not recover with write_file after the tool error", observation)

        expected = next(spec.expected_artifact for spec in CASES if spec.name is case)
        if artifact_error:
            return _failure(model, case, ErrorCategory.TOOL_FAILURE, f"artifact verification failed: {artifact_error}", observation)
        if artifact != expected:
            actual_size = len(artifact) if artifact is not None else 0
            return _failure(
                model,
                case,
                ErrorCategory.TOOL_FAILURE,
                f"artifact content did not match the expected marker ({actual_size} bytes)",
                observation,
            )

    return SmokeResult(
        model=model,
        case=case,
        passed=True,
        detail="contract satisfied",
        first_content_ms=observation.first_content_ms,
    )


def _summary(results: list[SmokeResult]) -> dict[str, int]:
    passed = sum(result.passed for result in results)
    return {"passed": passed, "failed": len(results) - passed, "total": len(results)}


def _print_results(results: list[SmokeResult]) -> None:
    print("MODEL\tCASE\tSTATUS\tCATEGORY\tFIRST_CONTENT_MS\tDETAIL")
    for result in results:
        latency = f"{result.first_content_ms:.1f}" if result.first_content_ms is not None else "-"
        print(
            "\t".join(
                [
                    redact_text(result.model),
                    result.case.value,
                    "PASS" if result.passed else "FAIL",
                    result.category.value if result.category else "-",
                    latency,
                    redact_text(result.detail),
                ]
            )
        )
    summary = _summary(results)
    print(f"Summary: {summary['passed']} passed, {summary['failed']} failed, {summary['total']} total")


def run_cli(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    runtime_factory: Callable[[], Runtime],
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> ExitCode:
    args = build_parser().parse_args(argv)
    if "CI" in environ:
        print("configuration_error: live model smoke checks are disabled in CI", file=sys.stderr)
        return ExitCode.CONFIGURATION
    if not args.list_models and environ.get(LIVE_OPT_IN) != "1":
        print(
            f"configuration_error: set {LIVE_OPT_IN}=1 to acknowledge that this command calls a real model and may incur charges",
            file=sys.stderr,
        )
        return ExitCode.CONFIGURATION

    try:
        runtime = runtime_factory()
        configured = runtime.list_models()
        if args.list_models:
            for model in configured:
                print(redact_text(model))
            return ExitCode.OK
        models = select_models(args.models or [], args.all_models, configured)
    except ConfigurationError as exc:
        print(f"configuration_error: {redact_text(exc)}", file=sys.stderr)
        return ExitCode.CONFIGURATION
    except ValueError as exc:
        print(f"configuration_error: {redact_text(exc)}", file=sys.stderr)
        return ExitCode.CONFIGURATION
    except Exception as exc:
        print(f"runner_error: {redact_text(exc)}", file=sys.stderr)
        return ExitCode.RUNNER_ERROR

    selected_cases = set(args.cases or [case.value for case in CaseName])
    specs = [spec for spec in CASES if spec.name.value in selected_cases]
    results: list[SmokeResult] = []
    runner_failed = False
    for model in models:
        for spec in specs:
            thread_id = f"smoke-{id_factory()[:24]}"
            user_id = f"smoke-{id_factory()[:24]}"
            result: SmokeResult | None = None
            try:
                result = runtime.run_case(model, spec, thread_id, user_id)
            except ConfigurationError as exc:
                result = SmokeResult(model, spec.name, False, redact_text(exc), ErrorCategory.CONFIGURATION)
            except Exception as exc:
                runner_failed = True
                result = SmokeResult(model, spec.name, False, redact_text(exc), ErrorCategory.RUNNER)
            finally:
                if not args.keep_workspaces:
                    try:
                        runtime.cleanup(thread_id, user_id)
                    except Exception as exc:
                        runner_failed = True
                        if result is None:
                            original_status = "not completed"
                        elif result.passed:
                            original_status = "passed"
                        else:
                            original_status = f"failed ({result.category.value if result.category else 'uncategorized'})"
                        result = SmokeResult(
                            model,
                            spec.name,
                            False,
                            f"cleanup failed (original check: {original_status}): {redact_text(exc)}",
                            ErrorCategory.RUNNER,
                        )
            if result is None:  # pragma: no cover - a BaseException propagates before this point
                raise RuntimeError("smoke case completed without a result")
            results.append(result)

    _print_results(results)
    if args.json_output:
        payload = {"results": [result.to_dict() for result in results], "summary": _summary(results)}
        try:
            args.json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"runner_error: could not write JSON report: {redact_text(exc)}", file=sys.stderr)
            return ExitCode.RUNNER_ERROR

    if runner_failed or any(result.category is ErrorCategory.RUNNER for result in results):
        return ExitCode.RUNNER_ERROR
    if any(result.category is ErrorCategory.CONFIGURATION for result in results):
        return ExitCode.CONFIGURATION
    if any(not result.passed for result in results):
        return ExitCode.CHECK_FAILED
    return ExitCode.OK
