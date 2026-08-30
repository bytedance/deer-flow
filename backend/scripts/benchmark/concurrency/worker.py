#!/usr/bin/env python3
"""A worker running as its own separate OS process -- its own engine/connection,
sharing nothing with the parent process or other workers, to simulate real
Gateway workers (separate processes, not asyncio tasks inside one process).

Connects DIRECTLY via SQLAlchemy (bypassing init_engine_from_config's
Alembic schema-state bootstrap, which costs ~8.5s per call regardless of
backend -- a real, separately-disclosed cost, but not what this benchmark
measures. The schema is already bootstrapped once by the orchestrator's
seed_baseline() before any worker starts, so a worker attaching directly is
exactly what a warm Gateway worker process does after its own one-time
startup, and isolates DB lock/throughput behavior from Python/import
cold-start cost).

Each worker does a fixed mix of reads (get_user_by_email) and writes
(create_user) against the SAME shared users table, and prints one JSON line
to stdout (latency + success/error per op), collected by the orchestrator
(run_concurrency_bench.py) afterward.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# scripts/benchmark/concurrency/worker.py -> backend/ is 3 levels up, same
# derivation as run_concurrency_bench.py (which spawns this file as a
# subprocess with cwd already set to BACKEND_DIR, but this file is also
# runnable/importable on its own, so it derives its own sys.path entry
# rather than relying on the parent's cwd).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.config.database_config import DatabaseConfig


def read_count(n_ops: int, read_ratio: float) -> int:
    """Exact number of reads out of n_ops -- round() rather than int()'s
    truncation-toward-zero, so the documented default (n_ops=50,
    read_ratio=0.7) yields 35 reads, not 34."""
    return round(n_ops * read_ratio)


def is_read_op(i: int, n_ops: int, n_reads: int) -> bool:
    """Whether op index i (0-based) is a read, given exactly n_reads reads
    spread evenly across n_ops slots.

    The previous check, `(i % 100) < int(read_ratio * 100)`, assumed n_ops
    was always >= 100: for the documented/default n_ops=50 (or any n_ops <=
    100), i % 100 == i, so every op satisfies i < read_ratio*100 up to i=69
    and every op after that fails it -- meaning the entire 50-op run was
    either all reads or all writes depending on read_ratio, never the
    claimed mixed workload.

    This instead uses modular (Bresenham-style) spacing: stepping i*n_reads
    through n_ops slots visits exactly n_reads distinct residues below
    n_reads, evenly distributed rather than clustered at the front, and
    produces precisely n_reads True values across the n_ops calls for any
    n_ops/n_reads pair.
    """
    if n_ops <= 0 or n_reads <= 0:
        return False
    if n_reads >= n_ops:
        return True
    return (i * n_reads) % n_ops < n_reads


def make_session_factory(backend: str, pg_url: str, pg_schema: str):
    """Build engine + session factory directly, without the Alembic
    bootstrap dance -- caller guarantees the schema already exists.

    pg_schema is the SAME disposable per-run schema the orchestrator's
    seed_baseline() already bootstrapped -- never "public" -- so a worker
    attaching directly lands in the right namespace instead of falling
    back to whatever the connection's default search_path happens to be.
    """
    if backend == "sqlite":
        cfg = DatabaseConfig(backend="sqlite", sqlite_dir=".deer-flow/bench_data")
        url = cfg.app_sqlalchemy_url
        engine = create_async_engine(url, connect_args={"timeout": 30})
    else:
        cfg = DatabaseConfig(backend="postgres", postgres_url=pg_url, postgres_schema=pg_schema)
        url = cfg.app_sqlalchemy_url
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": pg_schema}})
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def run_worker(backend: str, worker_id: int, n_ops: int, read_ratio: float, known_emails: list[str], pg_url: str, pg_schema: str):
    t_conn0 = time.perf_counter()
    engine, sf = make_session_factory(backend, pg_url, pg_schema)
    # Force a real physical connection now (not lazy) so conn_time reflects
    # the actual cost of a worker's first DB round-trip, same as a real
    # Gateway worker would pay on its first request. Entering an empty
    # AsyncSession does NOT check out a connection -- SQLAlchemy stays lazy
    # until the first statement executes -- so this must run an actual
    # lightweight query, not just `async with sf(): pass`, or the first
    # timed op in the loop below silently absorbs connection-establishment
    # cost instead of conn_time (a real distortion at 16 workers: those 16
    # cold first-ops are 1% of a 1600-op sample and can skew the reported
    # p99).
    async with sf() as session:
        await session.execute(text("SELECT 1"))
    conn_time = time.perf_counter() - t_conn0
    repo = SQLiteUserRepository(sf)

    # Signal ready, then block for the orchestrator's start signal, before
    # touching the operation loop's timer. Without this, each worker starts
    # its timed loop as soon as ITS OWN imports+connection finish -- so the
    # orchestrator's wall_time (started before any worker was even spawned)
    # includes N staggered process-startup costs, and early workers run
    # ahead of workers that are still starting. This makes every worker
    # cross the same starting line together, so wall_time measures actual
    # concurrent execution instead of startup skew (see run_workers() in
    # run_concurrency_bench.py for the other half of this handshake).
    print("READY", flush=True)
    sys.stdin.readline()

    results = []
    n_reads = read_count(n_ops, read_ratio)
    for i in range(n_ops):
        is_read = is_read_op(i, n_ops, n_reads)
        t0 = time.perf_counter()
        ok = True
        err = None
        try:
            if is_read:
                email = known_emails[(worker_id * n_ops + i) % len(known_emails)]
                await repo.get_user_by_email(email)
            else:
                u = User(
                    id=uuid4(),
                    email=f"bench_w{worker_id}_{i}_{uuid4().hex[:8]}@conc-bench-teste.com",
                    password_hash="h",
                    system_role="user",
                    created_at=datetime.now(UTC),
                    oauth_provider=None,
                    oauth_id=None,
                    needs_setup=False,
                    token_version=0,
                )
                await repo.create_user(u)
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {str(e)[:200]}"
        elapsed = time.perf_counter() - t0
        results.append({"op": "read" if is_read else "write", "ok": ok, "err": err, "latency_s": elapsed})

    await engine.dispose()
    return {"worker_id": worker_id, "conn_time_s": conn_time, "results": results}


def main():
    backend = sys.argv[1]
    worker_id = int(sys.argv[2])
    n_ops = int(sys.argv[3])
    read_ratio = float(sys.argv[4])
    known_emails = sys.argv[5].split(",")
    pg_url = sys.argv[6] if len(sys.argv) > 6 else ""
    pg_schema = sys.argv[7] if len(sys.argv) > 7 else ""

    out = asyncio.run(run_worker(backend, worker_id, n_ops, read_ratio, known_emails, pg_url, pg_schema))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
