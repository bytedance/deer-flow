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
from uuid import uuid4

sys.path.insert(0, "/opt/deer-flow/backend")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.config.database_config import DatabaseConfig


def make_session_factory(backend: str, pg_url: str):
    """Build engine + session factory directly, without the Alembic
    bootstrap dance -- caller guarantees the schema already exists."""
    if backend == "sqlite":
        cfg = DatabaseConfig(backend="sqlite", sqlite_dir=".deer-flow/bench_data")
        url = cfg.app_sqlalchemy_url
        engine = create_async_engine(url, connect_args={"timeout": 30})
    else:
        cfg = DatabaseConfig(backend="postgres", postgres_url=pg_url, postgres_schema="public")
        url = cfg.app_sqlalchemy_url
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": "public"}})
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def run_worker(backend: str, worker_id: int, n_ops: int, read_ratio: float, known_emails: list[str], pg_url: str):
    t_conn0 = time.perf_counter()
    engine, sf = make_session_factory(backend, pg_url)
    # force a real connection now (not lazy) so conn_time reflects the
    # actual cost of a worker's first DB round-trip, same as a real
    # Gateway worker would pay on its first request.
    async with sf():
        pass
    conn_time = time.perf_counter() - t_conn0
    repo = SQLiteUserRepository(sf)

    results = []
    for i in range(n_ops):
        is_read = (i % 100) < int(read_ratio * 100)
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

    out = asyncio.run(run_worker(backend, worker_id, n_ops, read_ratio, known_emails, pg_url))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
