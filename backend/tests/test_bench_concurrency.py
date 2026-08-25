"""Unit tests for scripts/benchmark/concurrency/run_concurrency_bench.py's
pure aggregation logic (percentile/error/crash accounting) -- fast, no DB
required, following the same pattern as test_bench_checkpoint_channels.py
(load the script as a module, unit-test its helpers directly rather than
running the actual multi-process sweep in CI)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/concurrency/run_concurrency_bench.py"
    spec = importlib.util.spec_from_file_location("run_concurrency_bench", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module()


def _result(ok: bool, latency_s: float, err: str | None = None, op: str = "read") -> dict:
    return {"op": op, "ok": ok, "err": err, "latency_s": latency_s}


def test_summarize_counts_completed_ops_across_workers() -> None:
    workers = [
        {"worker_id": 0, "results": [_result(True, 0.001), _result(True, 0.002)]},
        {"worker_id": 1, "results": [_result(True, 0.003)]},
    ]
    summary = bench.summarize(workers, wall_time=1.0, n_workers=2, ops_per_worker=2)
    assert summary["completed_ops"] == 3
    assert summary["crashed_workers"] == 0
    assert summary["errors"] == 0


def test_summarize_separates_crashed_workers_from_completed_ops() -> None:
    workers = [
        {"worker_id": 0, "results": [_result(True, 0.001)]},
        {"worker_id": None, "crashed": True, "stderr": "boom", "results": []},
    ]
    summary = bench.summarize(workers, wall_time=1.0, n_workers=2, ops_per_worker=5)
    assert summary["crashed_workers"] == 1
    assert summary["completed_ops"] == 1
    assert summary["expected_total_ops"] == 10


def test_summarize_groups_errors_by_exception_type() -> None:
    workers = [
        {
            "worker_id": 0,
            "results": [
                _result(False, 0.5, err="OperationalError: database is locked"),
                _result(False, 0.6, err="OperationalError: database is locked"),
                _result(False, 0.1, err="IntegrityError: duplicate key"),
                _result(True, 0.001),
            ],
        }
    ]
    summary = bench.summarize(workers, wall_time=1.0, n_workers=1, ops_per_worker=4)
    assert summary["errors"] == 3
    assert summary["error_types"] == {"OperationalError": 2, "IntegrityError": 1}


def test_summarize_percentiles_are_monotonic_and_within_observed_range() -> None:
    """p50 <= p95 <= p99 <= max always holds for any nonempty, nonnegative
    latency distribution -- a basic sanity invariant on the aggregation
    math itself, independent of what a real run happens to produce."""
    latencies = [0.001 * i for i in range(1, 101)]  # 1ms..100ms, evenly spaced
    workers = [{"worker_id": 0, "results": [_result(True, latency) for latency in latencies]}]
    summary = bench.summarize(workers, wall_time=2.5, n_workers=1, ops_per_worker=100)

    assert summary["latency_p50_ms"] <= summary["latency_p95_ms"]
    assert summary["latency_p95_ms"] <= summary["latency_p99_ms"]
    assert summary["latency_p99_ms"] <= summary["latency_max_ms"]
    assert summary["latency_max_ms"] == 100.0  # the largest input, in ms


def test_summarize_handles_empty_results_without_crashing() -> None:
    """All workers crashed -- no ops completed at all. Percentiles must
    degrade to None rather than raising (e.g. dividing by zero, or
    indexing an empty sorted list)."""
    workers = [{"worker_id": None, "crashed": True, "stderr": "boom", "results": []}]
    summary = bench.summarize(workers, wall_time=1.0, n_workers=1, ops_per_worker=10)
    assert summary["completed_ops"] == 0
    assert summary["latency_p50_ms"] is None
    assert summary["latency_p99_ms"] is None
    assert summary["throughput_ops_per_s"] == 0.0


def test_summarize_throughput_matches_completed_ops_over_wall_time() -> None:
    workers = [{"worker_id": 0, "results": [_result(True, 0.001) for _ in range(50)]}]
    summary = bench.summarize(workers, wall_time=5.0, n_workers=1, ops_per_worker=50)
    assert summary["throughput_ops_per_s"] == 10.0  # 50 ops / 5s
