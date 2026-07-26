#!/usr/bin/env python3
"""Benchmark DeerFlow's full and DeltaChannel checkpoint message storage.

The public CLI is a controller. Every benchmark case runs in a fresh child
process and, for SQLite, a fresh database. This mirrors the restart-required
checkpoint mode boundary and prevents one mode's graph/channel caches from
warming the other.

Examples::

    PYTHONPATH=. uv run python scripts/benchmark/bench_checkpoint_channels.py \
        --updates 10,100,500,999,1000,1001,2000 \
        --payload-bytes 128,4096 \
        --output checkpoint-bench.jsonl

    PYTHONPATH=. uv run python scripts/benchmark/bench_checkpoint_channels.py \
        --backends sqlite --updates 1000 --payload-bytes 128 \
        --repetitions 7 --output snapshot-boundary.jsonl

The controller suppresses matrix pairs whose estimated cumulative full-mode
message payload exceeds ``--max-estimated-full-bytes``. Both modes are skipped
as a pair so every emitted full/delta result remains comparable. Use
``--allow-large-cases`` only on a machine provisioned for the resulting disk
and memory use.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from deerflow.agents.thread_state import merge_message_writes
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

try:
    import resource
except ImportError:  # pragma: no cover - Windows only
    resource = None  # type: ignore[assignment]

Mode = Literal["full", "delta"]
Backend = Literal["memory", "sqlite"]

SCHEMA_VERSION = 1
BENCHMARK_VERSION = 1
PRODUCTION_SNAPSHOT_FREQUENCY = 1000
DEFAULT_MAX_ESTIMATED_FULL_BYTES = 1024**3
_GIT_SHA_ENV = "DEERFLOW_CHECKPOINT_BENCH_GIT_SHA"
_MODES: tuple[Mode, ...] = ("full", "delta")
_BACKENDS: tuple[Backend, ...] = ("memory", "sqlite")
_STORAGE_STAT_FIELDS = (
    "logical_checkpoint_bytes",
    "logical_write_bytes",
    "checkpoint_rows",
    "write_rows",
)


class _FullBenchmarkState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class _DeltaBenchmarkState(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(merge_message_writes, snapshot_frequency=PRODUCTION_SNAPSHOT_FREQUENCY),
    ]


@dataclass(frozen=True)
class BenchmarkCase:
    mode: Mode
    backend: Backend
    update_count: int
    payload_bytes: int
    repetition: int
    seed: int
    scenario: str = "append"
    snapshot_frequency: int = PRODUCTION_SNAPSHOT_FREQUENCY

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"unsupported mode: {self.mode!r}")
        if self.backend not in _BACKENDS:
            raise ValueError(f"unsupported backend: {self.backend!r}")
        if self.update_count <= 0:
            raise ValueError("update_count must be positive")
        if self.payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        if self.repetition < 0:
            raise ValueError("repetition must be non-negative")
        if self.snapshot_frequency != PRODUCTION_SNAPSHOT_FREQUENCY:
            raise ValueError(f"Phase 1 supports only production snapshot_frequency={PRODUCTION_SNAPSHOT_FREQUENCY}")
        if self.scenario != "append":
            raise ValueError(f"unsupported scenario: {self.scenario!r}")


def _parse_positive_int_csv(value: str, *, option: str) -> list[int]:
    if not value or value.startswith(",") or value.endswith(",") or ",," in value:
        raise ValueError(f"{option} must be a comma-separated list of positive integers")
    result: list[int] = []
    seen: set[int] = set()
    duplicates: list[int] = []
    try:
        parsed = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise ValueError(f"{option} must be a comma-separated list of positive integers") from exc
    if any(item <= 0 for item in parsed):
        raise ValueError(f"{option} values must be positive integers")
    for item in parsed:
        if item not in seen:
            result.append(item)
            seen.add(item)
        elif item not in duplicates:
            duplicates.append(item)
    if duplicates:
        print(
            f"{option}: ignored duplicate value(s): {', '.join(str(item) for item in duplicates)}; use --repetitions for repeated samples.",
            file=sys.stderr,
        )
    return result


def _parse_choice_csv(value: str, *, option: str, choices: tuple[str, ...]) -> list[str]:
    if not value or value.startswith(",") or value.endswith(",") or ",," in value:
        raise ValueError(f"{option} must contain one or more of: {', '.join(choices)}")
    result: list[str] = []
    duplicates: list[str] = []
    for raw in value.split(","):
        item = raw.strip()
        if item not in choices:
            raise ValueError(f"{option} contains unsupported value {item!r}; expected: {', '.join(choices)}")
        if item not in result:
            result.append(item)
        elif item not in duplicates:
            duplicates.append(item)
    if duplicates:
        print(
            f"{option}: ignored duplicate value(s): {', '.join(duplicates)}; use --repetitions for repeated samples.",
            file=sys.stderr,
        )
    return result


def _expand_cases(
    *,
    modes: list[str],
    backends: list[str],
    update_counts: list[int],
    payload_bytes: list[int],
    repetitions: int,
    seed: int,
) -> list[BenchmarkCase]:
    """Build a matrix with alternating mode order to reduce order bias."""
    cases: list[BenchmarkCase] = []
    for repetition in range(repetitions):
        for backend in backends:
            for payload in payload_bytes:
                for update_index, update_count in enumerate(update_counts):
                    ordered_modes = list(modes)
                    if (repetition + update_index) % 2 == 1:
                        ordered_modes.reverse()
                    for mode in ordered_modes:
                        cases.append(
                            BenchmarkCase(
                                mode=mode,  # type: ignore[arg-type]
                                backend=backend,  # type: ignore[arg-type]
                                update_count=update_count,
                                payload_bytes=payload,
                                repetition=repetition,
                                seed=seed,
                            )
                        )
    return cases


def _estimated_full_payload_bytes(case: BenchmarkCase) -> int:
    """Lower-bound cumulative message content serialized by full mode."""
    return case.payload_bytes * case.update_count * (case.update_count + 1) // 2


def _filter_oversized_pairs(cases: list[BenchmarkCase], *, max_bytes: int | None) -> tuple[list[BenchmarkCase], list[BenchmarkCase]]:
    if max_bytes is None:
        return cases, []
    group_fields = ("backend", "scenario", "snapshot_frequency", "update_count", "payload_bytes", "repetition")
    oversized_keys = {tuple(getattr(case, field) for field in group_fields) for case in cases if case.mode == "full" and _estimated_full_payload_bytes(case) > max_bytes}
    kept = [case for case in cases if tuple(getattr(case, field) for field in group_fields) not in oversized_keys]
    skipped = [case for case in cases if tuple(getattr(case, field) for field in group_fields) in oversized_keys]
    return kept, skipped


def _message_for_update(index: int, payload_bytes: int) -> BaseMessage:
    content = "x" * payload_bytes
    message_id = f"bench-message-{index:08d}"
    if index % 2 == 0:
        return HumanMessage(id=message_id, content=content)
    return AIMessage(id=message_id, content=content)


def _canonical_messages_digest(messages: list[AnyMessage]) -> str:
    canonical = [
        {
            "id": message.id,
            "type": message.type,
            "content": message.content,
        }
        for message in messages
    ]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _window_median(values: list[float], window: Literal["first", "middle", "last"]) -> float:
    if not values:
        return 0.0
    width = max(1, len(values) // 10)
    if window == "first":
        selected = values[:width]
    elif window == "last":
        selected = values[-width:]
    else:
        center = len(values) // 2
        start = max(0, center - width // 2)
        selected = values[start : start + width]
    return statistics.median(selected)


def _noop(_state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _build_graph(mode: Mode, saver: Any) -> Any:
    schema = _DeltaBenchmarkState if mode == "delta" else _FullBenchmarkState
    builder = StateGraph(schema)
    builder.add_node("noop", _noop)
    builder.set_entry_point("noop")
    builder.set_finish_point("noop")
    return builder.compile(checkpointer=saver)


def _config(case: BenchmarkCase) -> dict[str, Any]:
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": f"checkpoint-bench-{case.seed}-{case.repetition}",
        }
    }
    inject_checkpoint_mode(config, case.mode)
    return config


def _resolve_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _base_row(case: BenchmarkCase) -> dict[str, Any]:
    git_sha = os.environ.get(_GIT_SHA_ENV) or _resolve_git_sha()
    try:
        langgraph_version = importlib.metadata.version("langgraph")
    except importlib.metadata.PackageNotFoundError:
        langgraph_version = "unknown"
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "success": True,
        "error": None,
        "profiled": False,
        "git_sha": git_sha,
        "python_version": platform.python_version(),
        "langgraph_version": langgraph_version,
        "platform": platform.platform(),
        "mode": case.mode,
        "backend": case.backend,
        "scenario": case.scenario,
        "snapshot_frequency": case.snapshot_frequency,
        "update_count": case.update_count,
        "payload_bytes": case.payload_bytes,
        "repetition": case.repetition,
        "seed": case.seed,
    }


def _safe_error(error: BaseException | str, *, work_dir: Path | None = None) -> str:
    message = str(error).replace(str(Path.home()), "<home>")
    if work_dir is not None:
        message = message.replace(str(work_dir), "<work-dir>")
    return message[:2000]


def _collect_storage_stats(collector: Callable[[], dict[str, int]]) -> dict[str, Any]:
    """Keep timing data usable when a saver's diagnostic layout changes."""
    try:
        return {**collector(), "storage_stats_error": None}
    except Exception as exc:
        return {
            **dict.fromkeys(_STORAGE_STAT_FIELDS),
            "storage_stats_error": _safe_error(exc),
        }


def _memory_storage_stats(saver: InMemorySaver, thread_id: str) -> dict[str, int]:
    checkpoint_rows = 0
    checkpoint_bytes = 0
    for namespace in saver.storage.get(thread_id, {}).values():
        for checkpoint, metadata, _parent_id in namespace.values():
            checkpoint_rows += 1
            checkpoint_bytes += len(checkpoint[1]) + len(metadata[1])
    for (stored_thread_id, _namespace, _channel, _version), (_type_tag, blob) in saver.blobs.items():
        if stored_thread_id == thread_id:
            checkpoint_bytes += len(blob)

    write_rows = 0
    write_bytes = 0
    for (stored_thread_id, _namespace, _checkpoint_id), writes in saver.writes.items():
        if stored_thread_id != thread_id:
            continue
        for _task_id, _channel, (_type_tag, blob), _task_path in writes.values():
            write_rows += 1
            write_bytes += len(blob)
    return {
        "logical_checkpoint_bytes": checkpoint_bytes,
        "logical_write_bytes": write_bytes,
        "checkpoint_rows": checkpoint_rows,
        "write_rows": write_rows,
    }


def _sqlite_storage_stats(saver: SqliteSaver, thread_id: str) -> dict[str, int]:
    with saver.cursor(transaction=False) as cursor:
        checkpoint_rows, checkpoint_bytes = cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(checkpoint) + length(metadata)), 0) FROM checkpoints WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        write_rows, write_bytes = cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(value)), 0) FROM writes WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    return {
        "logical_checkpoint_bytes": int(checkpoint_bytes),
        "logical_write_bytes": int(write_bytes),
        "checkpoint_rows": int(checkpoint_rows),
        "write_rows": int(write_rows),
    }


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak_rss) if sys.platform == "darwin" else int(peak_rss * 1024)


def _write_and_read(case: BenchmarkCase, saver: Any, messages: list[BaseMessage]) -> tuple[dict[str, Any], list[AnyMessage]]:
    graph = _build_graph(case.mode, saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=case.mode)
    config = _config(case)
    update_latencies: list[float] = []
    write_start = time.perf_counter()
    for message in messages:
        update_start = time.perf_counter()
        graph.invoke({"messages": [message]}, config)
        update_latencies.append((time.perf_counter() - update_start) * 1000)
    write_total_ms = (time.perf_counter() - write_start) * 1000

    warm_start = time.perf_counter()
    snapshot = accessor.get(config)
    warm_read_ms = (time.perf_counter() - warm_start) * 1000
    materialized = list(snapshot.values.get("messages", []))
    metrics = {
        "write_total_ms": write_total_ms,
        "write_p50_ms": _percentile(update_latencies, 50),
        "write_p95_ms": _percentile(update_latencies, 95),
        "write_p99_ms": _percentile(update_latencies, 99),
        "write_first_window_ms": _window_median(update_latencies, "first"),
        "write_middle_window_ms": _window_median(update_latencies, "middle"),
        "write_last_window_ms": _window_median(update_latencies, "last"),
        "warm_read_ms": warm_read_ms,
    }
    return metrics, materialized


def _cold_read(case: BenchmarkCase, saver: Any) -> tuple[float, list[AnyMessage]]:
    graph = _build_graph(case.mode, saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=case.mode)
    gc.collect()
    start = time.perf_counter()
    snapshot = accessor.get(_config(case))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, list(snapshot.values.get("messages", []))


def _validate_materialized(case: BenchmarkCase, expected: list[BaseMessage], warm: list[AnyMessage], cold: list[AnyMessage]) -> tuple[int, str]:
    expected_digest = _canonical_messages_digest(expected)
    warm_digest = _canonical_messages_digest(warm)
    cold_digest = _canonical_messages_digest(cold)
    if len(warm) != case.update_count or len(cold) != case.update_count:
        raise AssertionError(f"expected {case.update_count} messages, materialized warm={len(warm)} cold={len(cold)}")
    if warm_digest != expected_digest or cold_digest != expected_digest:
        raise AssertionError("materialized message content or ordering differs from deterministic input")
    return len(cold), cold_digest


def _run_memory_case(case: BenchmarkCase, messages: list[BaseMessage]) -> dict[str, Any]:
    saver = InMemorySaver()
    metrics, warm = _write_and_read(case, saver, messages)
    stats = _collect_storage_stats(lambda: _memory_storage_stats(saver, _config(case)["configurable"]["thread_id"]))
    cold_read_ms, cold = _cold_read(case, saver)
    actual_count, digest = _validate_materialized(case, messages, warm, cold)
    return {
        **metrics,
        **stats,
        "cold_read_ms": cold_read_ms,
        # InMemorySaver has no durable external storage to reopen. The cold
        # sample rebuilds the graph/channel table over the same saver only.
        "saver_reopen_ms": 0.0,
        "db_bytes": None,
        "wal_bytes": None,
        "shm_bytes": None,
        "durable_db_bytes": None,
        "expected_message_count": case.update_count,
        "actual_message_count": actual_count,
        "content_sha256": digest,
    }


def _run_sqlite_case(case: BenchmarkCase, messages: list[BaseMessage], db_path: Path) -> dict[str, Any]:
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        saver.setup()
        metrics, warm = _write_and_read(case, saver, messages)
        stats = _collect_storage_stats(lambda: _sqlite_storage_stats(saver, _config(case)["configurable"]["thread_id"]))
        db_bytes = _file_size(db_path)
        wal_bytes = _file_size(Path(f"{db_path}-wal"))
        shm_bytes = _file_size(Path(f"{db_path}-shm"))

    durable_db_bytes = _file_size(db_path)
    reopen_start = time.perf_counter()
    with SqliteSaver.from_conn_string(str(db_path)) as reopened:
        reopened.setup()
        saver_reopen_ms = (time.perf_counter() - reopen_start) * 1000
        cold_read_ms, cold = _cold_read(case, reopened)

    actual_count, digest = _validate_materialized(case, messages, warm, cold)
    return {
        **metrics,
        **stats,
        "cold_read_ms": cold_read_ms,
        "saver_reopen_ms": saver_reopen_ms,
        "db_bytes": db_bytes,
        "wal_bytes": wal_bytes,
        "shm_bytes": shm_bytes,
        "durable_db_bytes": durable_db_bytes,
        "expected_message_count": case.update_count,
        "actual_message_count": actual_count,
        "content_sha256": digest,
    }


def _run_case(case: BenchmarkCase, *, work_dir: Path) -> dict[str, Any]:
    row = _base_row(case)
    messages = [_message_for_update(index, case.payload_bytes) for index in range(case.update_count)]
    try:
        if case.backend == "memory":
            measured = _run_memory_case(case, messages)
        else:
            measured = _run_sqlite_case(case, messages, work_dir / "checkpoint-benchmark.sqlite")

        reducer_writes = [[message] for message in messages]
        reducer_start = time.perf_counter()
        reduced = merge_message_writes([], reducer_writes)
        reducer_replay_ms = (time.perf_counter() - reducer_start) * 1000
        if _canonical_messages_digest(reduced) != _canonical_messages_digest(messages):
            raise AssertionError("standalone reducer diagnostic produced incorrect state")

        row.update(measured)
        row["reducer_replay_ms"] = reducer_replay_ms
        row["peak_rss_bytes"] = _peak_rss_bytes()
    except Exception as exc:
        row["success"] = False
        row["error"] = _safe_error(exc, work_dir=work_dir)
    return row


def _run_profiled_case(case: BenchmarkCase, *, work_dir: Path, profile_path: Path) -> dict[str, Any]:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profiler = cProfile.Profile()
    row = profiler.runcall(_run_case, case, work_dir=work_dir)
    row["profiled"] = True
    profiler.dump_stats(profile_path)
    return row


def _comparison_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(field)
        for field in (
            "backend",
            "scenario",
            "snapshot_frequency",
            "update_count",
            "payload_bytes",
            "repetition",
        )
    )


def _validate_cross_mode_rows(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_comparison_key(row), []).append(row)
    for group in grouped.values():
        successful = [row for row in group if row.get("success")]
        modes = {row.get("mode") for row in successful}
        if not {"full", "delta"}.issubset(modes):
            continue
        signatures = {(row.get("actual_message_count"), row.get("content_sha256")) for row in successful if row.get("mode") in {"full", "delta"}}
        if len(signatures) == 1:
            continue
        for row in successful:
            row["success"] = False
            row["error"] = "cross-mode materialized state mismatch"


def _failure_row(case: BenchmarkCase, error: str) -> dict[str, Any]:
    row = _base_row(case)
    row["success"] = False
    row["error"] = _safe_error(error)
    return row


def _profile_filename(case: BenchmarkCase) -> str:
    return f"{case.backend}-{case.mode}-updates-{case.update_count}-payload-{case.payload_bytes}-rep-{case.repetition}.prof"


def _run_child_case(case: BenchmarkCase, *, timeout_seconds: float, git_sha: str, profile_dir: Path | None = None) -> dict[str, Any]:
    encoded_case = json.dumps(asdict(case), separators=(",", ":"))
    command = [sys.executable, str(Path(__file__).resolve()), "--worker-case", encoded_case]
    if profile_dir is not None:
        command.extend(["--worker-profile", str(profile_dir / _profile_filename(case))])
    started = time.perf_counter()
    child_env = os.environ.copy()
    child_env[_GIT_SHA_ENV] = git_sha
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        return _failure_row(case, f"child process timed out after {timeout_seconds:g} seconds")
    child_process_ms = (time.perf_counter() - started) * 1000
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not output_lines:
        return _failure_row(case, f"child process returned {completed.returncode} without a result")
    try:
        row = json.loads(output_lines[-1])
    except json.JSONDecodeError:
        return _failure_row(case, f"child process returned {completed.returncode} with malformed JSON")
    row["child_process_ms"] = child_process_ms
    if completed.returncode != 0 and row.get("success"):
        row["success"] = False
        row["error"] = f"child process exited with status {completed.returncode}"
    return row


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark full and delta checkpoint message channels")
    parser.add_argument("--modes", default="full,delta", help="Comma-separated modes (default: full,delta)")
    parser.add_argument("--backends", default="memory,sqlite", help="Comma-separated backends (default: memory,sqlite)")
    parser.add_argument("--updates", default="10,100", help="Comma-separated message update counts (default: 10,100)")
    parser.add_argument("--payload-bytes", default="128", help="Comma-separated exact message content sizes (default: 128)")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument(
        "--max-estimated-full-bytes",
        type=int,
        default=DEFAULT_MAX_ESTIMATED_FULL_BYTES,
        help=("Skip comparable pairs whose estimated cumulative full-mode payload exceeds this value. The cap applies only when full mode is selected; delta-only diagnostics bypass it."),
    )
    parser.add_argument("--allow-large-cases", action="store_true", help="Disable the estimated cumulative full-payload safety cap")
    parser.add_argument("--profile-dir", type=Path, help="Write one cProfile file per case; profiling inflates timings")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-case", help=argparse.SUPPRESS)
    parser.add_argument("--worker-profile", type=Path, help=argparse.SUPPRESS)
    return parser


def _worker_main(encoded_case: str, *, profile_path: Path | None = None) -> int:
    try:
        case = BenchmarkCase(**json.loads(encoded_case))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "benchmark_version": BENCHMARK_VERSION, "success": False, "error": _safe_error(exc)}, separators=(",", ":")))
        return 2
    with tempfile.TemporaryDirectory(prefix="deerflow-checkpoint-benchmark-") as temp_dir:
        if profile_path is None:
            row = _run_case(case, work_dir=Path(temp_dir))
        else:
            row = _run_profiled_case(case, work_dir=Path(temp_dir), profile_path=profile_path)
    print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    return 0 if row.get("success") else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.worker_case is not None:
        return _worker_main(args.worker_case, profile_path=args.worker_profile)
    if args.output is None:
        parser.error("--output is required")
    try:
        modes = _parse_choice_csv(args.modes, option="--modes", choices=_MODES)
        backends = _parse_choice_csv(args.backends, option="--backends", choices=_BACKENDS)
        updates = _parse_positive_int_csv(args.updates, option="--updates")
        payload_bytes = _parse_positive_int_csv(args.payload_bytes, option="--payload-bytes")
        if args.repetitions <= 0:
            raise ValueError("--repetitions must be positive")
        if args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be positive")
        if not args.allow_large_cases and args.max_estimated_full_bytes <= 0:
            raise ValueError("--max-estimated-full-bytes must be positive")
    except ValueError as exc:
        parser.error(str(exc))

    cases = _expand_cases(
        modes=modes,
        backends=backends,
        update_counts=updates,
        payload_bytes=payload_bytes,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    cases, skipped = _filter_oversized_pairs(cases, max_bytes=None if args.allow_large_cases else args.max_estimated_full_bytes)
    if skipped:
        skipped_pairs = len(skipped) // max(1, len(modes))
        print(
            f"Skipping {skipped_pairs} oversized comparable case pair(s); use --allow-large-cases to run them.",
            file=sys.stderr,
        )
    if not cases:
        print("No benchmark cases remain after applying the safety cap.", file=sys.stderr)
        return 2

    git_sha = _resolve_git_sha()
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] {case.backend} {case.mode} updates={case.update_count} payload={case.payload_bytes} repetition={case.repetition}",
            file=sys.stderr,
        )
        rows.append(_run_child_case(case, timeout_seconds=args.timeout_seconds, git_sha=git_sha, profile_dir=args.profile_dir))
    _validate_cross_mode_rows(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    failures = sum(1 for row in rows if not row.get("success"))
    print(f"Wrote {len(rows)} result row(s) to {args.output}; failures={failures}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
