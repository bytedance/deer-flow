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


def _worker(worker_id, results: list[dict], ops_elapsed_s: float = 1.0) -> dict:
    return {"worker_id": worker_id, "ops_elapsed_s": ops_elapsed_s, "results": results}


def _crashed(worker_id, stderr: str = "boom") -> dict:
    return {"worker_id": worker_id, "crashed": True, "stderr": stderr, "results": []}


def test_summarize_counts_completed_ops_across_workers() -> None:
    workers = [
        _worker(0, [_result(True, 0.001), _result(True, 0.002)]),
        _worker(1, [_result(True, 0.003)]),
    ]
    summary = bench.summarize(workers, n_workers=2, ops_per_worker=2)
    assert summary["completed_ops"] == 3
    assert summary["crashed_workers"] == 0
    assert summary["errors"] == 0


def test_summarize_separates_crashed_workers_from_completed_ops() -> None:
    workers = [
        _worker(0, [_result(True, 0.001)]),
        _crashed(None),
    ]
    summary = bench.summarize(workers, n_workers=2, ops_per_worker=5)
    assert summary["crashed_workers"] == 1
    assert summary["completed_ops"] == 1
    assert summary["expected_total_ops"] == 10


def test_summarize_groups_errors_by_exception_type() -> None:
    workers = [
        _worker(
            0,
            [
                _result(False, 0.5, err="OperationalError: database is locked"),
                _result(False, 0.6, err="OperationalError: database is locked"),
                _result(False, 0.1, err="IntegrityError: duplicate key"),
                _result(True, 0.001),
            ],
        )
    ]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=4)
    assert summary["errors"] == 3
    assert summary["error_types"] == {"OperationalError": 2, "IntegrityError": 1}


def test_summarize_percentiles_are_monotonic_and_within_observed_range() -> None:
    """p50 <= p95 <= p99 <= max always holds for any nonempty, nonnegative
    latency distribution -- a basic sanity invariant on the aggregation
    math itself, independent of what a real run happens to produce."""
    latencies = [0.001 * i for i in range(1, 101)]  # 1ms..100ms, evenly spaced
    workers = [_worker(0, [_result(True, latency) for latency in latencies])]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=100)

    assert summary["latency_p50_ms"] <= summary["latency_p95_ms"]
    assert summary["latency_p95_ms"] <= summary["latency_p99_ms"]
    assert summary["latency_p99_ms"] <= summary["latency_max_ms"]
    assert summary["latency_max_ms"] == 100.0  # the largest input, in ms


def test_summarize_percentiles_match_hand_computed_nearest_rank_values() -> None:
    """Exact p50/p95/p99 for a small, hand-computable distribution -- the
    monotonicity test above can't catch a bug where p95 and p99 both
    collapse to the same (wrong) value, since max <= max still holds.

    latencies here are 1ms..20ms. The reviewer's finding: the old
    `int(len(latencies) * p)` used directly as a zero-based index put both
    p95 and p99 at index 19 -- the maximum -- for any 20-sample run.
    checkpoint_bench_common.percentile's (n-1)*p/100 nearest-rank
    interpolation, reused here, keeps them distinct from the max.
    """
    latencies = [0.001 * i for i in range(1, 21)]  # 1ms..20ms
    workers = [_worker(0, [_result(True, latency) for latency in latencies])]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=20)

    assert summary["latency_p50_ms"] == 10.5
    assert summary["latency_p95_ms"] == 19.05
    assert summary["latency_p99_ms"] == 19.81
    assert summary["latency_max_ms"] == 20.0
    # the specific bug: p95 and p99 must NOT both equal the max
    assert summary["latency_p95_ms"] != summary["latency_max_ms"]
    assert summary["latency_p99_ms"] != summary["latency_max_ms"]


def test_summarize_percentiles_match_hand_computed_values_at_documented_sample_size() -> None:
    """Same shape of check at the documented default sample size (100 ops)."""
    latencies = [0.001 * i for i in range(1, 101)]  # 1ms..100ms
    workers = [_worker(0, [_result(True, latency) for latency in latencies])]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=100)

    assert summary["latency_p50_ms"] == 50.5
    assert summary["latency_p95_ms"] == 95.05
    assert summary["latency_p99_ms"] == 99.01


def test_summarize_handles_empty_results_without_crashing() -> None:
    """All workers crashed -- no ops completed at all. Percentiles must
    degrade to None rather than raising (e.g. dividing by zero, or
    indexing an empty sorted list); with no operation window there is also
    no throughput to report."""
    workers = [_crashed(None)]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=10)
    assert summary["completed_ops"] == 0
    assert summary["latency_p50_ms"] is None
    assert summary["latency_p99_ms"] is None
    assert summary["throughput_ops_per_s"] is None


def test_summarize_surfaces_crashed_worker_diagnostics_not_just_a_count() -> None:
    """crashed_workers stays an int count (existing contract) but the
    stderr each crashed worker actually printed must also be reachable
    from the summary -- previously captured in run_workers() and then
    discarded, leaving an all-crashed sweep with zero explanation of why."""
    workers = [
        _worker(0, [_result(True, 0.001)]),
        _crashed(1, "OperationalError: unable to open database file"),
        _crashed(2, "sqlite3.IntegrityError: UNIQUE constraint failed"),
    ]
    summary = bench.summarize(workers, n_workers=3, ops_per_worker=1)
    assert summary["crashed_workers"] == 2
    assert summary["crashed_worker_errors"] == [
        {"worker_id": 1, "stderr": "OperationalError: unable to open database file"},
        {"worker_id": 2, "stderr": "sqlite3.IntegrityError: UNIQUE constraint failed"},
    ]


def test_summary_indicates_failure_for_an_all_crashed_sweep() -> None:
    """The exact scenario the reviewer's repro produced: every worker
    crashed, so the summary looks well-formed (completed_ops: 0,
    throughput_ops_per_s: None) but represents no real measurement at all.
    main() must treat this as a failure (nonzero exit), not a quiet 0-op
    result -- this pins the check that decides that, independent of
    main()'s argparse/subprocess machinery."""
    workers = [_crashed(0), _crashed(1)]
    summary = bench.summarize(workers, n_workers=2, ops_per_worker=4)
    assert bench.summary_indicates_failure(summary) is True


def test_summary_indicates_failure_when_completed_ops_falls_short_without_a_crash() -> None:
    """Defense in depth: even if crashed_workers is 0, fewer completed ops
    than expected must still count as a failure rather than being silently
    accepted as a (misleadingly short) real measurement."""
    summary = {"crashed_workers": 0, "completed_ops": 3, "expected_total_ops": 4}
    assert bench.summary_indicates_failure(summary) is True


def test_summary_indicates_failure_when_every_op_errored_without_a_crash() -> None:
    """A sweep where every op ran to completion but raised (e.g. every write
    hitting OperationalError) has crashed_workers == 0 and
    completed_ops == expected_total_ops, so the two checks above accept it.
    errors > 0 must also disqualify it -- the PR's conclusions rest on
    '0 errors on both backends'."""
    workers = [
        _worker(
            0,
            [_result(False, 0.5, err="OperationalError: database is locked", op="write") for _ in range(4)],
        )
    ]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=4)
    assert summary["crashed_workers"] == 0
    assert summary["completed_ops"] == summary["expected_total_ops"] == 4
    assert summary["errors"] == 4
    assert bench.summary_indicates_failure(summary) is True


def test_summary_indicates_failure_is_false_for_a_clean_run() -> None:
    workers = [_worker(0, [_result(True, 0.001) for _ in range(4)])]
    summary = bench.summarize(workers, n_workers=1, ops_per_worker=4)
    assert bench.summary_indicates_failure(summary) is False


def test_summarize_throughput_uses_slowest_worker_operation_window() -> None:
    """Throughput is completed_ops / max(worker ops_elapsed_s), not over the
    orchestrator's post-communicate() wall clock -- so a worker that spends
    extra time in teardown/IPC after its last op does not deflate the
    number, and the slowest still-contending worker sets the window."""
    workers = [
        _worker(0, [_result(True, 0.001) for _ in range(30)], ops_elapsed_s=5.0),
        _worker(1, [_result(True, 0.001) for _ in range(20)], ops_elapsed_s=2.0),
    ]
    summary = bench.summarize(workers, n_workers=2, ops_per_worker=25)
    assert summary["ops_window_s"] == 5.0
    assert summary["throughput_ops_per_s"] == 10.0  # 50 ops / 5s
