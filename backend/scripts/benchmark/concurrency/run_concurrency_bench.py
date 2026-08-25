#!/usr/bin/env python3
"""Real concurrency benchmark: N SEPARATE OS processes (subprocess.Popen,
not asyncio.gather, not threading) hitting the SAME users table at the same
time, comparing SQLite vs Postgres at 2/4/8/16 workers.

This tests exactly the scenario DeerFlow's own docs describe
(CONFIGURATION.md line 325): "Multi-worker deployments (GATEWAY_WORKERS > 1)
must use the Postgres database backend... SQLite silently ignores row-level
locks" -- multiple Gateway PROCESSES, each with its own connection, not
multiple async tasks inside ONE process (which a prior single-process
benchmark already showed has no problem).

Usage:
    uv run python scripts/benchmark/concurrency/run_concurrency_bench.py \
        --backend sqlite --workers 2,4,8,16 --ops-per-worker 50 --read-ratio 0.7

    uv run python scripts/benchmark/concurrency/run_concurrency_bench.py \
        --backend postgres --workers 2,4,8,16 --ops-per-worker 50 --read-ratio 0.7 \
        --pg-url postgresql+asyncpg://deerflow_test:deerflow_test_pw@localhost/deerflow_test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/opt/deer-flow/backend")

WORKER_SCRIPT = Path(__file__).parent / "worker.py"
UV_RUN = ["/opt/deer-flow/backend/.venv/bin/python3"]
BACKEND_DIR = Path("/opt/deer-flow/backend")


async def seed_baseline(backend: str, pg_url: str, n_users: int = 100) -> list[str]:
    """Populate a known baseline BEFORE the concurrent run starts -- worker
    reads target these known emails (not ones the workers themselves are
    creating), so read and write paths don't depend on each other within
    the same run."""
    from app.gateway.auth.models import User
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config

    if backend == "sqlite":
        sqlite_dir = BACKEND_DIR / ".deer-flow" / "bench_data"
        if sqlite_dir.exists():
            shutil.rmtree(sqlite_dir)
        cfg = DatabaseConfig(backend="sqlite", sqlite_dir=".deer-flow/bench_data")
    else:
        cfg = DatabaseConfig(backend="postgres", postgres_url=pg_url, postgres_schema="public")

    await init_engine_from_config(cfg)
    sf = get_session_factory()
    repo = SQLiteUserRepository(sf)
    if backend == "postgres":
        # clean prior run's rows so they don't accumulate across executions
        from sqlalchemy import text

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users"))
    emails = []
    for i in range(n_users):
        email = f"baseline_{i}@conc-bench-teste.com"
        u = User(id=uuid4(), email=email, password_hash="h", system_role="user", created_at=datetime.now(UTC), oauth_provider=None, oauth_id=None, needs_setup=False, token_version=0)
        await repo.create_user(u)
        emails.append(email)
    await close_engine()
    return emails


def run_workers(backend: str, n_workers: int, ops_per_worker: int, read_ratio: float, known_emails: list[str], pg_url: str):
    emails_arg = ",".join(known_emails)
    procs = []
    t_start = time.perf_counter()
    for wid in range(n_workers):
        cmd = UV_RUN + [str(WORKER_SCRIPT), backend, str(wid), str(ops_per_worker), str(read_ratio), emails_arg, pg_url]
        p = subprocess.Popen(cmd, cwd=str(BACKEND_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append(p)

    worker_outputs = []
    for p in procs:
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            worker_outputs.append({"worker_id": None, "crashed": True, "stderr": stderr[-2000:], "results": []})
            continue
        try:
            worker_outputs.append(json.loads(stdout.strip().splitlines()[-1]))
        except Exception as e:
            worker_outputs.append({"worker_id": None, "crashed": True, "stderr": f"parse error: {e}; stdout={stdout[-500:]}; stderr={stderr[-500:]}", "results": []})
    wall_time = time.perf_counter() - t_start
    return worker_outputs, wall_time


def summarize(worker_outputs, wall_time: float, n_workers: int, ops_per_worker: int) -> dict:
    all_results = []
    crashed = 0
    for w in worker_outputs:
        if w.get("crashed"):
            crashed += 1
            continue
        all_results.extend(w["results"])

    total_ops = len(all_results)
    errors = [r for r in all_results if not r["ok"]]
    latencies = sorted(r["latency_s"] for r in all_results)
    err_types = {}
    for r in errors:
        key = r["err"].split(":")[0] if r["err"] else "unknown"
        err_types[key] = err_types.get(key, 0) + 1

    def pct(p):
        if not latencies:
            return None
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return latencies[idx]

    return {
        "n_workers": n_workers,
        "ops_per_worker": ops_per_worker,
        "expected_total_ops": n_workers * ops_per_worker,
        "completed_ops": total_ops,
        "crashed_workers": crashed,
        "errors": len(errors),
        "error_types": err_types,
        "wall_time_s": round(wall_time, 3),
        "throughput_ops_per_s": round(total_ops / wall_time, 2) if wall_time > 0 else None,
        "latency_p50_ms": round(pct(0.50) * 1000, 3) if pct(0.50) is not None else None,
        "latency_p95_ms": round(pct(0.95) * 1000, 3) if pct(0.95) is not None else None,
        "latency_p99_ms": round(pct(0.99) * 1000, 3) if pct(0.99) is not None else None,
        "latency_max_ms": round(latencies[-1] * 1000, 3) if latencies else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=["sqlite", "postgres"])
    ap.add_argument("--workers", required=True, help="comma-separated list, e.g. 2,4,8,16")
    ap.add_argument("--ops-per-worker", type=int, default=50)
    ap.add_argument("--read-ratio", type=float, default=0.7)
    ap.add_argument("--pg-url", default="")
    ap.add_argument("--baseline-users", type=int, default=100)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    worker_counts = [int(x) for x in args.workers.split(",")]
    all_summaries = []

    for n_workers in worker_counts:
        print(f"--- seeding baseline ({args.backend}, {args.baseline_users} users) ---", file=sys.stderr)
        emails = asyncio.run(seed_baseline(args.backend, args.pg_url, args.baseline_users))

        print(f"--- running {n_workers} workers ({args.backend}, {args.ops_per_worker} ops/worker) ---", file=sys.stderr)
        worker_outputs, wall_time = run_workers(args.backend, n_workers, args.ops_per_worker, args.read_ratio, emails, args.pg_url)
        summary = summarize(worker_outputs, wall_time, n_workers, args.ops_per_worker)
        summary["backend"] = args.backend
        all_summaries.append(summary)
        print(json.dumps(summary, indent=2), file=sys.stderr)

    result = {"backend": args.backend, "read_ratio": args.read_ratio, "runs": all_summaries}
    output = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(output)
    print(output)


if __name__ == "__main__":
    main()
