"""Unit tests for scripts/benchmark/concurrency/worker.py's read/write op
scheduling -- fast, no DB required, same load-as-module pattern as
test_bench_concurrency.py (which covers run_concurrency_bench.py's
aggregation logic)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark/concurrency/worker.py"
    spec = importlib.util.spec_from_file_location("bench_worker", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


worker = _load_module()


def _schedule(n_ops: int, read_ratio: float) -> list[bool]:
    n_reads = worker.read_count(n_ops, read_ratio)
    return [worker.is_read_op(i, n_ops, n_reads) for i in range(n_ops)]


def test_default_ops_per_worker_and_read_ratio_produce_a_mixed_workload() -> None:
    """The documented/default invocation (--ops-per-worker 50 --read-ratio
    0.7, per run_concurrency_bench.py's own --help and usage docstring) must
    produce both reads and writes. The prior `(i % 100) < int(read_ratio *
    100)` check made every op a read here (50 < 100), reproducing the
    reviewer's finding directly."""
    schedule = _schedule(n_ops=50, read_ratio=0.7)
    assert schedule.count(True) == 35
    assert schedule.count(False) == 15


def test_reads_are_spread_across_the_sequence_not_clustered() -> None:
    """A schedule that is technically mixed but front-loaded (e.g. all 35
    reads before any write) would still misrepresent steady-state concurrent
    load. Both halves of the sequence must contain each op type."""
    schedule = _schedule(n_ops=50, read_ratio=0.7)
    first_half, second_half = schedule[:25], schedule[25:]
    assert True in first_half and False in first_half
    assert True in second_half and False in second_half


def test_read_count_rounds_rather_than_truncates() -> None:
    assert worker.read_count(50, 0.7) == 35  # round(35.0), not int(34.999...)


def test_zero_read_ratio_is_all_writes() -> None:
    schedule = _schedule(n_ops=20, read_ratio=0.0)
    assert schedule.count(True) == 0


def test_full_read_ratio_is_all_reads() -> None:
    schedule = _schedule(n_ops=20, read_ratio=1.0)
    assert schedule.count(True) == 20


def test_small_op_counts_still_get_an_exact_mix() -> None:
    """n_ops well under 100 (e.g. a quick manual smoke run) is exactly the
    regime the old modulo-100 logic silently broke."""
    for n_ops in (1, 2, 3, 7, 13, 30, 99):
        schedule = _schedule(n_ops=n_ops, read_ratio=0.7)
        assert len(schedule) == n_ops
        assert schedule.count(True) == round(n_ops * 0.7)


def test_sqlite_worker_engine_matches_the_app_connection_pragmas(tmp_path, monkeypatch) -> None:
    """synchronous and foreign_keys are per-connection PRAGMAs: without the
    worker mirroring the app's connect listener
    (persistence/engine.py::_enable_sqlite_wal) it runs at SQLite's
    synchronous=FULL / foreign_keys=OFF defaults, and its measured write
    path pays a heavier per-commit fsync than the deployment being
    benchmarked -- overstating SQLite's cost in the direction that flatters
    the 'use Postgres' conclusion."""
    import asyncio

    from sqlalchemy import text

    monkeypatch.setattr(worker, "SQLITE_BENCH_DIR", str(tmp_path))

    async def _check() -> None:
        engine, _sf = worker.make_session_factory("sqlite", pg_url="", pg_schema="")
        try:
            async with engine.connect() as conn:
                assert (await conn.execute(text("PRAGMA synchronous"))).scalar() == 1  # NORMAL
                assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1  # ON
                assert (await conn.execute(text("PRAGMA journal_mode"))).scalar().lower() == "wal"
        finally:
            await engine.dispose()

    asyncio.run(_check())
