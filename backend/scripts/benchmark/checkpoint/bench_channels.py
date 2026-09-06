#!/usr/bin/env python3
"""Benchmark DeerFlow's full and DeltaChannel checkpoint message storage.

The public CLI is a controller. Every benchmark case runs in a fresh child
process and, for SQLite, a fresh database. This mirrors the restart-required
checkpoint mode boundary and prevents one mode's graph/channel caches from
warming the other.

Examples::

    PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_channels.py \
        --updates 10,100,500,999,1000,1001,2000 \
        --payload-bytes 128,4096 \
        --output checkpoint-bench.jsonl

    PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_channels.py \
        --backends sqlite --updates 1000 --payload-bytes 128 \
        --repetitions 7 --output snapshot-boundary.jsonl

    TEST_POSTGRES_URI=postgresql://... \
    PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_channels.py \
        --backends sqlite,postgres --updates 100 --payload-bytes 128 \
        --output cross-backend.jsonl

The controller suppresses matrix cells whose estimated cumulative full-mode
message payload exceeds ``--max-estimated-full-bytes``. Full mode and every
swept delta cadence are skipped together so every emitted result remains
comparable and subject to the same safety cap. Use
``--allow-large-cases`` only on a machine provisioned for the resulting disk
and memory use.

Postgres is opt-in through ``TEST_POSTGRES_URI``. Each case uses a unique
benchmark thread and removes only that thread through the saver's public
``adelete_thread`` API after collecting the measurements.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from deerflow.agents.thread_state import merge_message_writes
from deerflow.config.database_config import DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint_bench_common as _common  # noqa: E402

_GIT_SHA_ENV = _common.GIT_SHA_ENV
_parse_positive_int_csv = _common.parse_positive_int_csv
_parse_choice_csv = _common.parse_choice_csv
_canonical_messages_digest = _common.canonical_messages_digest
_percentile = _common.percentile
_window_median = _common.window_median
_resolve_git_sha = _common.resolve_git_sha
_safe_error = _common.safe_error
_file_size = _common.file_size
_peak_rss_bytes = _common.peak_rss_bytes

Mode = Literal["full", "delta"]
Backend = Literal["memory", "sqlite", "postgres"]

SCHEMA_VERSION = 2
BENCHMARK_VERSION = 2
PRODUCTION_SNAPSHOT_FREQUENCY = DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY
DEFAULT_MAX_ESTIMATED_FULL_BYTES = 1024**3
_MODES: tuple[Mode, ...] = ("full", "delta")
_BACKENDS: tuple[Backend, ...] = ("memory", "sqlite", "postgres")
_STORAGE_STAT_FIELDS = (
    "logical_checkpoint_bytes",
    "logical_write_bytes",
    "checkpoint_rows",
    "checkpoint_bytes",
    "blob_rows",
    "blob_bytes",
    "write_rows",
    "write_bytes",
)
_PROCESS_RUN_ID = uuid4().hex[:12]


class _FullBenchmarkState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


@cache
def _delta_benchmark_state(snapshot_frequency: int) -> type:
    """Delta benchmark schema for one snapshot cadence (cached per value)."""
    return TypedDict(
        f"_DeltaBenchmarkState_f{snapshot_frequency}",
        {"messages": Annotated[list[AnyMessage], DeltaChannel(merge_message_writes, snapshot_frequency=snapshot_frequency)]},
    )


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
        if self.snapshot_frequency <= 0:
            raise ValueError("snapshot_frequency must be positive")
        if self.scenario != "append":
            raise ValueError(f"unsupported scenario: {self.scenario!r}")


def _expand_cases(
    *,
    modes: list[str],
    backends: list[str],
    update_counts: list[int],
    payload_bytes: list[int],
    repetitions: int,
    seed: int,
    snapshot_frequencies: list[int] | None = None,
) -> list[BenchmarkCase]:
    """Build a matrix with alternating mode order to reduce order bias.

    ``snapshot_frequencies`` sweeps delta cases across cadences. Full-mode
    cases ignore the cadence and run once per cell at the production default,
    so a sweep costs no duplicate full-mode measurements.
    """
    frequencies = snapshot_frequencies or [PRODUCTION_SNAPSHOT_FREQUENCY]
    cases: list[BenchmarkCase] = []
    for repetition in range(repetitions):
        for backend in backends:
            for payload in payload_bytes:
                for update_index, update_count in enumerate(update_counts):
                    ordered_modes = list(modes)
                    if (repetition + update_index) % 2 == 1:
                        ordered_modes.reverse()
                    for mode in ordered_modes:
                        mode_frequencies = frequencies if mode == "delta" else [PRODUCTION_SNAPSHOT_FREQUENCY]
                        for snapshot_frequency in mode_frequencies:
                            cases.append(
                                BenchmarkCase(
                                    mode=mode,  # type: ignore[arg-type]
                                    backend=backend,  # type: ignore[arg-type]
                                    update_count=update_count,
                                    payload_bytes=payload,
                                    repetition=repetition,
                                    seed=seed,
                                    snapshot_frequency=snapshot_frequency,
                                )
                            )
    return cases


def _estimated_full_payload_bytes(case: BenchmarkCase) -> int:
    """Lower-bound cumulative message content serialized by full mode."""
    return case.payload_bytes * case.update_count * (case.update_count + 1) // 2


def _filter_oversized_pairs(cases: list[BenchmarkCase], *, max_bytes: int | None) -> tuple[list[BenchmarkCase], list[BenchmarkCase]]:
    if max_bytes is None:
        return cases, []
    # Cadence is a delta-only sweep dimension: full mode runs once per benchmark
    # cell at the production default. Excluding it ensures an oversized full
    # case suppresses every delta cadence in that same cell.
    group_fields = ("backend", "scenario", "update_count", "payload_bytes", "repetition")
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


def _noop(_state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _build_graph(mode: Mode, saver: Any, snapshot_frequency: int) -> Any:
    schema = _delta_benchmark_state(snapshot_frequency) if mode == "delta" else _FullBenchmarkState
    builder = StateGraph(schema)
    builder.add_node("noop", _noop)
    builder.set_entry_point("noop")
    builder.set_finish_point("noop")
    return builder.compile(checkpointer=saver)


def _config(case: BenchmarkCase) -> dict[str, Any]:
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": (f"checkpoint-bench-{case.seed}-{case.repetition}-{case.backend}-{case.mode}-{case.update_count}-{case.payload_bytes}-{_PROCESS_RUN_ID}"),
        }
    }
    inject_checkpoint_mode(config, case.mode)
    return config


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


def _safe_benchmark_error(error: BaseException | str, *, work_dir: Path | None = None) -> str:
    message = _safe_error(error, work_dir=work_dir)
    postgres_uri = os.environ.get("TEST_POSTGRES_URI")
    return message.replace(postgres_uri, "<TEST_POSTGRES_URI>") if postgres_uri else message


def _collect_storage_stats(collector: Callable[[], dict[str, int]]) -> dict[str, Any]:
    """Keep timing data usable when a saver's diagnostic layout changes."""
    try:
        return {**collector(), "storage_stats_error": None}
    except Exception as exc:
        return {
            **dict.fromkeys(_STORAGE_STAT_FIELDS),
            "storage_stats_error": _safe_benchmark_error(exc),
        }


async def _collect_storage_stats_async(collector: Callable[[], Awaitable[dict[str, int]]]) -> dict[str, Any]:
    """Async counterpart for saver diagnostics backed by an async cursor."""
    try:
        return {**(await collector()), "storage_stats_error": None}
    except Exception as exc:
        return {
            **dict.fromkeys(_STORAGE_STAT_FIELDS),
            "storage_stats_error": _safe_benchmark_error(exc),
        }


def _normalized_storage_stats(
    *,
    checkpoint_rows: int,
    checkpoint_bytes: int,
    blob_rows: int,
    blob_bytes: int,
    write_rows: int,
    write_bytes: int,
) -> dict[str, int]:
    """Return one backend-neutral checkpoint/blob/write measurement shape."""
    return {
        "logical_checkpoint_bytes": checkpoint_bytes + blob_bytes,
        "logical_write_bytes": write_bytes,
        "checkpoint_rows": checkpoint_rows,
        "checkpoint_bytes": checkpoint_bytes,
        "blob_rows": blob_rows,
        "blob_bytes": blob_bytes,
        "write_rows": write_rows,
        "write_bytes": write_bytes,
    }


def _memory_storage_stats(saver: InMemorySaver, thread_id: str) -> dict[str, int]:
    checkpoint_rows = 0
    checkpoint_bytes = 0
    for namespace in saver.storage.get(thread_id, {}).values():
        for checkpoint, metadata, _parent_id in namespace.values():
            checkpoint_rows += 1
            checkpoint_bytes += len(checkpoint[1]) + len(metadata[1])
    blob_rows = 0
    blob_bytes = 0
    for (stored_thread_id, _namespace, _channel, _version), (_type_tag, blob) in saver.blobs.items():
        if stored_thread_id == thread_id:
            blob_rows += 1
            blob_bytes += len(blob)

    write_rows = 0
    write_bytes = 0
    for (stored_thread_id, _namespace, _checkpoint_id), writes in saver.writes.items():
        if stored_thread_id != thread_id:
            continue
        for _task_id, _channel, (_type_tag, blob), _task_path in writes.values():
            write_rows += 1
            write_bytes += len(blob)
    return _normalized_storage_stats(
        checkpoint_rows=checkpoint_rows,
        checkpoint_bytes=checkpoint_bytes,
        blob_rows=blob_rows,
        blob_bytes=blob_bytes,
        write_rows=write_rows,
        write_bytes=write_bytes,
    )


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
    return _normalized_storage_stats(
        checkpoint_rows=int(checkpoint_rows),
        checkpoint_bytes=int(checkpoint_bytes),
        # SqliteSaver stores channel values inside the serialized checkpoint
        # payload; unlike PostgresSaver, it has no separate blob table.
        blob_rows=0,
        blob_bytes=0,
        write_rows=int(write_rows),
        write_bytes=int(write_bytes),
    )


async def _postgres_storage_stats(saver: Any, thread_id: str) -> dict[str, int]:
    """Measure the LangGraph-owned Postgres tables for one benchmark thread."""
    queries = (
        "SELECT COUNT(*) AS rows, COALESCE(SUM(pg_column_size(checkpoint) + pg_column_size(metadata)), 0) AS bytes FROM checkpoints WHERE thread_id = %s",
        "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_blobs WHERE thread_id = %s",
        "SELECT COUNT(*) AS rows, COALESCE(SUM(octet_length(blob)), 0) AS bytes FROM checkpoint_writes WHERE thread_id = %s",
    )
    measured: list[tuple[int, int]] = []
    async with saver._cursor() as cursor:
        for query in queries:
            await cursor.execute(query, (thread_id,))
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Postgres storage diagnostic returned no row")
            measured.append((int(row["rows"]), int(row["bytes"])))
    (checkpoint_rows, checkpoint_bytes), (blob_rows, blob_bytes), (write_rows, write_bytes) = measured
    return _normalized_storage_stats(
        checkpoint_rows=checkpoint_rows,
        checkpoint_bytes=checkpoint_bytes,
        blob_rows=blob_rows,
        blob_bytes=blob_bytes,
        write_rows=write_rows,
        write_bytes=write_bytes,
    )


def _write_and_read(case: BenchmarkCase, saver: Any, messages: list[BaseMessage]) -> tuple[dict[str, Any], list[AnyMessage]]:
    graph = _build_graph(case.mode, saver, case.snapshot_frequency)
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
    graph = _build_graph(case.mode, saver, case.snapshot_frequency)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=case.mode)
    gc.collect()
    start = time.perf_counter()
    snapshot = accessor.get(_config(case))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, list(snapshot.values.get("messages", []))


async def _awrite_and_read(case: BenchmarkCase, saver: Any, messages: list[BaseMessage]) -> tuple[dict[str, Any], list[AnyMessage]]:
    graph = _build_graph(case.mode, saver, case.snapshot_frequency)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=case.mode)
    config = _config(case)
    update_latencies: list[float] = []
    write_start = time.perf_counter()
    for message in messages:
        update_start = time.perf_counter()
        await graph.ainvoke({"messages": [message]}, config)
        update_latencies.append((time.perf_counter() - update_start) * 1000)
    write_total_ms = (time.perf_counter() - write_start) * 1000

    warm_start = time.perf_counter()
    snapshot = await accessor.aget(config)
    warm_read_ms = (time.perf_counter() - warm_start) * 1000
    return {
        "write_total_ms": write_total_ms,
        "write_p50_ms": _percentile(update_latencies, 50),
        "write_p95_ms": _percentile(update_latencies, 95),
        "write_p99_ms": _percentile(update_latencies, 99),
        "write_first_window_ms": _window_median(update_latencies, "first"),
        "write_middle_window_ms": _window_median(update_latencies, "middle"),
        "write_last_window_ms": _window_median(update_latencies, "last"),
        "warm_read_ms": warm_read_ms,
    }, list(snapshot.values.get("messages", []))


async def _acold_read(case: BenchmarkCase, saver: Any) -> tuple[float, list[AnyMessage]]:
    graph = _build_graph(case.mode, saver, case.snapshot_frequency)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode=case.mode)
    gc.collect()
    start = time.perf_counter()
    snapshot = await accessor.aget(_config(case))
    return (time.perf_counter() - start) * 1000, list(snapshot.values.get("messages", []))


def _validate_materialized(case: BenchmarkCase, expected: list[BaseMessage], warm: list[AnyMessage], cold: list[AnyMessage]) -> tuple[int, str]:
    expected_digest = _canonical_messages_digest(expected)
    warm_digest = _canonical_messages_digest(warm)
    cold_digest = _canonical_messages_digest(cold)
    if len(warm) != case.update_count or len(cold) != case.update_count:
        raise AssertionError(f"expected {case.update_count} messages, materialized warm={len(warm)} cold={len(cold)}")
    if warm_digest != expected_digest or cold_digest != expected_digest:
        raise AssertionError("materialized message content or ordering differs from deterministic input")
    return len(cold), cold_digest


_HISTORY_CACHE_ENV = "DEERFLOW_CHECKPOINT_BENCH_HISTORY_CACHE"


def _wrap_history_cache(saver: Any) -> Any:
    """Wrap *saver* in a CachedHistorySaver with a fresh, unbounded memory cache.

    Opt-in via DEERFLOW_CHECKPOINT_BENCH_HISTORY_CACHE=1 so default rows are
    byte-identical to the pre-cache benchmark. A fresh wrapper per phase keeps
    the cold read genuinely cold: the write-phase cache is discarded, mirroring
    a process restart (cache lifetime == checkpointer CM lifetime).
    """
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
    from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

    return CachedHistorySaver(
        saver,
        MemoryCheckpointHistoryCache(max_entries=1_000_000),
        key_prefix="bench:v1:checkpoint-bench",
    )


def _history_cache_stats(wrapper: Any, prefix: str) -> dict[str, Any]:
    return {f"{prefix}{key}": value for key, value in wrapper.stats().items()}


def _run_memory_case(case: BenchmarkCase, messages: list[BaseMessage]) -> dict[str, Any]:
    cache_opt_in = os.environ.get(_HISTORY_CACHE_ENV) == "1"
    saver = InMemorySaver()
    write_saver = _wrap_history_cache(saver) if cache_opt_in else saver
    metrics, warm = _write_and_read(case, write_saver, messages)
    stats = _collect_storage_stats(lambda: _memory_storage_stats(saver, _config(case)["configurable"]["thread_id"]))
    cold_saver = _wrap_history_cache(saver) if cache_opt_in else saver
    cold_read_ms, cold = _cold_read(case, cold_saver)
    actual_count, digest = _validate_materialized(case, messages, warm, cold)
    result = {
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
    if cache_opt_in:
        result["history_cache_enabled"] = True
        result.update(_history_cache_stats(write_saver, "history_cache_write_"))
        result.update(_history_cache_stats(cold_saver, "history_cache_cold_"))
    return result


def _run_sqlite_case(case: BenchmarkCase, messages: list[BaseMessage], db_path: Path) -> dict[str, Any]:
    cache_opt_in = os.environ.get(_HISTORY_CACHE_ENV) == "1"
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        saver.setup()
        write_saver = _wrap_history_cache(saver) if cache_opt_in else saver
        metrics, warm = _write_and_read(case, write_saver, messages)
        stats = _collect_storage_stats(lambda: _sqlite_storage_stats(saver, _config(case)["configurable"]["thread_id"]))
        db_bytes = _file_size(db_path)
        wal_bytes = _file_size(Path(f"{db_path}-wal"))
        shm_bytes = _file_size(Path(f"{db_path}-shm"))

    durable_db_bytes = _file_size(db_path)
    reopen_start = time.perf_counter()
    with SqliteSaver.from_conn_string(str(db_path)) as reopened:
        reopened.setup()
        saver_reopen_ms = (time.perf_counter() - reopen_start) * 1000
        cold_saver = _wrap_history_cache(reopened) if cache_opt_in else reopened
        cold_read_ms, cold = _cold_read(case, cold_saver)

    actual_count, digest = _validate_materialized(case, messages, warm, cold)
    result = {
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
    if cache_opt_in:
        result["history_cache_enabled"] = True
        result.update(_history_cache_stats(write_saver, "history_cache_write_"))
        result.update(_history_cache_stats(cold_saver, "history_cache_cold_"))
    return result


async def _delete_postgres_benchmark_thread(uri: str, thread_id: str) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        await saver.setup()
        await saver.adelete_thread(thread_id)


async def _run_postgres_case(case: BenchmarkCase, messages: list[BaseMessage], uri: str) -> dict[str, Any]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    cache_opt_in = os.environ.get(_HISTORY_CACHE_ENV) == "1"
    thread_id = _config(case)["configurable"]["thread_id"]
    completed = False
    try:
        async with AsyncPostgresSaver.from_conn_string(uri) as saver:
            await saver.setup()
            write_saver = _wrap_history_cache(saver) if cache_opt_in else saver
            metrics, warm = await _awrite_and_read(case, write_saver, messages)
            stats = await _collect_storage_stats_async(lambda: _postgres_storage_stats(saver, thread_id))

        reopen_start = time.perf_counter()
        async with AsyncPostgresSaver.from_conn_string(uri) as reopened:
            await reopened.setup()
            saver_reopen_ms = (time.perf_counter() - reopen_start) * 1000
            cold_saver = _wrap_history_cache(reopened) if cache_opt_in else reopened
            cold_read_ms, cold = await _acold_read(case, cold_saver)

        actual_count, digest = _validate_materialized(case, messages, warm, cold)
        result = {
            **metrics,
            **stats,
            "cold_read_ms": cold_read_ms,
            "saver_reopen_ms": saver_reopen_ms,
            "db_bytes": None,
            "wal_bytes": None,
            "shm_bytes": None,
            "durable_db_bytes": None,
            "expected_message_count": case.update_count,
            "actual_message_count": actual_count,
            "content_sha256": digest,
        }
        if cache_opt_in:
            result["history_cache_enabled"] = True
            result.update(_history_cache_stats(write_saver, "history_cache_write_"))
            result.update(_history_cache_stats(cold_saver, "history_cache_cold_"))
        completed = True
        return result
    finally:
        if completed:
            await _delete_postgres_benchmark_thread(uri, thread_id)
        else:
            with suppress(Exception):
                await _delete_postgres_benchmark_thread(uri, thread_id)


def _run_case(case: BenchmarkCase, *, work_dir: Path) -> dict[str, Any]:
    row = _base_row(case)
    messages = [_message_for_update(index, case.payload_bytes) for index in range(case.update_count)]
    try:
        if case.backend == "memory":
            measured = _run_memory_case(case, messages)
        elif case.backend == "sqlite":
            measured = _run_sqlite_case(case, messages, work_dir / "checkpoint-benchmark.sqlite")
        else:
            uri = os.environ.get("TEST_POSTGRES_URI")
            if not uri:
                raise RuntimeError("postgres benchmark requires TEST_POSTGRES_URI")
            measured = asyncio.run(_run_postgres_case(case, messages, uri))

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
        row["error"] = _safe_benchmark_error(exc, work_dir=work_dir)
    return row


def _run_profiled_case(case: BenchmarkCase, *, work_dir: Path, profile_path: Path) -> dict[str, Any]:
    return _common.run_profiled(_run_case, case, work_dir=work_dir, profile_path=profile_path)


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
    return f"{case.backend}-{case.mode}-freq-{case.snapshot_frequency}-updates-{case.update_count}-payload-{case.payload_bytes}-rep-{case.repetition}.prof"


def _run_child_case(case: BenchmarkCase, *, timeout_seconds: float, git_sha: str, profile_dir: Path | None = None) -> dict[str, Any]:
    worker_args = ["--worker-case", json.dumps(asdict(case), separators=(",", ":"))]
    if profile_dir is not None:
        worker_args.extend(["--worker-profile", str(profile_dir / _profile_filename(case))])
    return _common.run_child_case(
        script=Path(__file__).resolve(),
        worker_args=worker_args,
        failure_row=lambda error: _failure_row(case, error),
        timeout_seconds=timeout_seconds,
        git_sha=git_sha,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark full and delta checkpoint message channels")
    parser.add_argument("--modes", default="full,delta", help="Comma-separated modes (default: full,delta)")
    parser.add_argument(
        "--backends",
        default="memory,sqlite",
        help="Comma-separated backends: memory, sqlite, postgres (default: memory,sqlite; postgres requires TEST_POSTGRES_URI)",
    )
    parser.add_argument("--updates", default="10,100", help="Comma-separated message update counts (default: 10,100)")
    parser.add_argument("--payload-bytes", default="128", help="Comma-separated exact message content sizes (default: 128)")
    parser.add_argument(
        "--snapshot-frequencies",
        default=str(PRODUCTION_SNAPSHOT_FREQUENCY),
        help=(
            "Comma-separated DeltaChannel snapshot cadences for delta cases "
            f"(default: {PRODUCTION_SNAPSHOT_FREQUENCY}). Full-mode cases ignore "
            "the cadence and run once per cell at the production default. "
            "Sweep 100,250,500,1000 to compare cadence tradeoffs."
        ),
    )
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
        if "postgres" in backends and not os.environ.get("TEST_POSTGRES_URI"):
            raise ValueError("--backends postgres requires TEST_POSTGRES_URI")
        updates = _parse_positive_int_csv(args.updates, option="--updates")
        payload_bytes = _parse_positive_int_csv(args.payload_bytes, option="--payload-bytes")
        snapshot_frequencies = _parse_positive_int_csv(args.snapshot_frequencies, option="--snapshot-frequencies")
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
        snapshot_frequencies=snapshot_frequencies,
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
        cadence = f" freq={case.snapshot_frequency}" if case.mode == "delta" else ""
        print(
            f"[{index}/{len(cases)}] {case.backend} {case.mode}{cadence} updates={case.update_count} payload={case.payload_bytes} repetition={case.repetition}",
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
