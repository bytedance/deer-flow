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
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# scripts/benchmark/concurrency/run_concurrency_bench.py -> backend/ is 3
# levels up (concurrency -> benchmark -> scripts -> backend). Derived from
# this file's own location, not hard-coded, so the documented
# `uv run python scripts/benchmark/concurrency/run_concurrency_bench.py`
# command works from any checkout, not just one at a specific fixed path.
BACKEND_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

# checkpoint_bench_common.py is a sibling script folder, not a package (see
# its own docstring) -- same sys.path-insert-then-import pattern
# bench_channels.py/bench_production.py already use for it, reused here so
# percentile() has one correct implementation instead of two.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checkpoint"))
from checkpoint_bench_common import percentile  # noqa: E402

WORKER_SCRIPT = Path(__file__).parent / "worker.py"
# One absolute path, shared by the seeder (this file) and every worker
# process (worker.py's make_session_factory). DatabaseConfig.sqlite_dir
# resolves relative strings against the CALLER's CWD, not this file's
# location -- passing the literal ".deer-flow/bench_data" meant the
# orchestrator (running from wherever it was invoked) and the workers
# (spawned with cwd=BACKEND_DIR) could silently resolve to two different
# directories whenever this script is invoked from outside backend/,
# leaving workers pointed at a DB the seeder never created (or already
# removed).
SQLITE_BENCH_DIR = str(BACKEND_DIR / ".deer-flow" / "bench_data")
# The orchestrator itself is already running under the correct interpreter
# (`uv run python ...`, per this file's own usage docstring above) -- reuse
# it for workers instead of a second hard-coded venv path that silently
# assumes deer-flow is checked out at /opt/deer-flow.
PYTHON = [sys.executable]


async def seed_baseline(backend: str, pg_url: str, pg_schema: str, n_users: int = 100) -> list[str]:
    """Populate a known baseline BEFORE the concurrent run starts -- worker
    reads target these known emails (not ones the workers themselves are
    creating), so read and write paths don't depend on each other within
    the same run."""
    from app.gateway.auth.models import User
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

    if backend == "sqlite":
        sqlite_dir = Path(SQLITE_BENCH_DIR)
        if sqlite_dir.exists():
            shutil.rmtree(sqlite_dir)
        cfg = DatabaseConfig(backend="sqlite", sqlite_dir=SQLITE_BENCH_DIR)
    else:
        # pg_schema is a unique, disposable schema for this benchmark run
        # (see main()) -- never "public" or any schema a real deployment
        # might already be using. init_engine_from_config creates it
        # automatically and pins search_path to it, so every statement
        # below (including the DELETE re-seed on repeat worker-count
        # sweeps) is scoped to this run's own throwaway namespace.
        cfg = DatabaseConfig(backend="postgres", postgres_url=pg_url, postgres_schema=pg_schema)

    await init_engine_from_config(cfg)
    sf = get_session_factory()
    repo = SQLiteUserRepository(sf)
    if backend == "postgres":
        # clean prior worker-count sweep's rows so they don't accumulate
        # across iterations WITHIN this run -- safe here specifically
        # because it's scoped (via search_path) to this run's own isolated
        # schema, never a shared/production one.
        from sqlalchemy import text

        from deerflow.persistence.engine import get_engine

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


async def drop_isolated_schema(pg_url: str, pg_schema: str) -> None:
    """Drop this run's disposable Postgres schema (and everything in it) once
    every worker-count sweep has finished. Only ever targets the unique
    per-run schema main() generated -- never "public" or a caller-supplied
    name, so there's nothing here that can reach into a real deployment's
    namespace even if --pg-url points at one."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.config.database_config import DatabaseConfig

    cfg = DatabaseConfig(backend="postgres", postgres_url=pg_url, postgres_schema=pg_schema)
    engine = create_async_engine(cfg.app_sqlalchemy_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{pg_schema}" CASCADE'))
    finally:
        await engine.dispose()


def run_workers(backend: str, n_workers: int, ops_per_worker: int, read_ratio: float, known_emails: list[str], pg_url: str, pg_schema: str):
    emails_arg = ",".join(known_emails)
    procs = []  # list of (worker_id, Popen) -- worker_id kept alongside so a
    # crashed worker's diagnostics can be attributed to the right id below,
    # instead of the placeholder "worker_id": None every crash used to get.
    for wid in range(n_workers):
        cmd = PYTHON + [str(WORKER_SCRIPT), backend, str(wid), str(ops_per_worker), str(read_ratio), emails_arg, pg_url, pg_schema]
        p = subprocess.Popen(cmd, cwd=str(BACKEND_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append((wid, p))

    # Start barrier: wait for every worker to print READY (connection
    # established, right before its own timed loop -- see worker.py) before
    # releasing any of them. Otherwise early workers run ahead of ones still
    # starting -- not a controlled N-worker contention measurement. Each
    # worker times its own operation phase (from GO to its last op) and the
    # throughput window is the max of those (see summarize); the staggered
    # Python-startup + connection cost stays out of it (conn_time_s measures
    # that per-worker). A worker that crashes before printing READY closes
    # its stdout, so readline() returns "" rather than hanging; the loop
    # below reports that same worker as crashed via its nonzero returncode.
    for _wid, p in procs:
        p.stdout.readline()

    for _wid, p in procs:
        try:
            p.stdin.write("GO\n")
            p.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass  # worker already exited -- nothing to release
        # Do NOT close p.stdin here: p.communicate() below flushes and closes
        # it, and a second close turns that flush into an uncaught ValueError
        # ("I/O operation on closed file"). The worker reads exactly one line
        # (the GO above), so the flush is all the release it needs.

    worker_outputs = []
    for wid, p in procs:
        stdout, stderr = p.communicate()
        if p.returncode != 0:
            # Surfaced immediately (not just embedded in the summary JSON)
            # so a crash is visible in real time, not just discoverable by
            # someone reading crashed_workers back out of the final report.
            print(f"--- worker {wid} crashed (exit {p.returncode}): {stderr[-2000:]} ---", file=sys.stderr)
            worker_outputs.append({"worker_id": wid, "crashed": True, "stderr": stderr[-2000:], "results": []})
            continue
        try:
            worker_outputs.append(json.loads(stdout.strip().splitlines()[-1]))
        except Exception as e:
            msg = f"parse error: {e}; stdout={stdout[-500:]}; stderr={stderr[-500:]}"
            print(f"--- worker {wid} produced unparseable output: {msg} ---", file=sys.stderr)
            worker_outputs.append({"worker_id": wid, "crashed": True, "stderr": msg, "results": []})
    return worker_outputs


def summarize(worker_outputs, n_workers: int, ops_per_worker: int) -> dict:
    all_results = []
    crashed = 0
    crashed_worker_errors = []
    ops_windows = []
    for w in worker_outputs:
        if w.get("crashed"):
            crashed += 1
            crashed_worker_errors.append({"worker_id": w.get("worker_id"), "stderr": w.get("stderr")})
            continue
        all_results.extend(w["results"])
        if "ops_elapsed_s" in w:
            ops_windows.append(w["ops_elapsed_s"])

    # All non-crashed workers are released by the same GO, so the slowest
    # worker's operation-phase elapsed is the window during which every
    # worker was contending. Using it (not the orchestrator's post-
    # communicate() wall clock) keeps per-worker engine.dispose() +
    # result serialization + stdout transfer out of the throughput figure.
    ops_window = max(ops_windows) if ops_windows else 0.0

    total_ops = len(all_results)
    errors = [r for r in all_results if not r["ok"]]
    latencies = sorted(r["latency_s"] for r in all_results)
    err_types = {}
    for r in errors:
        key = r["err"].split(":")[0] if r["err"] else "unknown"
        err_types[key] = err_types.get(key, 0) + 1

    def pct(p):
        # p is a 0..1 fraction here (0.50/0.95/0.99); checkpoint_bench_common's
        # percentile() takes 0..100 and already does correct nearest-rank
        # interpolation ((n-1)*percentile/100, not int(n*p) used directly as
        # an index -- that off-by-one made p95/p99 both resolve to the max
        # for any sample of 20 or fewer values, and for the documented
        # 100-sample default).
        if not latencies:
            return None
        return percentile(latencies, p * 100)

    return {
        "n_workers": n_workers,
        "ops_per_worker": ops_per_worker,
        "expected_total_ops": n_workers * ops_per_worker,
        "completed_ops": total_ops,
        "crashed_workers": crashed,
        "crashed_worker_errors": crashed_worker_errors,
        "errors": len(errors),
        "error_types": err_types,
        "ops_window_s": round(ops_window, 3),
        "throughput_ops_per_s": round(total_ops / ops_window, 2) if ops_window > 0 else None,
        "latency_p50_ms": round(pct(0.50) * 1000, 3) if pct(0.50) is not None else None,
        "latency_p95_ms": round(pct(0.95) * 1000, 3) if pct(0.95) is not None else None,
        "latency_p99_ms": round(pct(0.99) * 1000, 3) if pct(0.99) is not None else None,
        "latency_max_ms": round(latencies[-1] * 1000, 3) if latencies else None,
    }


def summary_indicates_failure(summary: dict) -> bool:
    """True if this worker-count sweep's summary represents a broken run,
    not a real measurement:

    - a crashed worker, or fewer completed results than expected without a
      crash -- an all-crashed sweep still produces a well-formed-looking
      summary (crashed_workers: N, completed_ops: 0,
      throughput_ops_per_s: 0.0);
    - any failed op (errors > 0). This benchmark's conclusions rest on
      "0 errors on both backends"; a sweep where every op completed but
      raised (e.g. writes hitting OperationalError) has completed_ops ==
      expected and 0 crashes, so it would otherwise pass as a clean
      measurement. The error breakdown stays in the printed JSON either
      way -- this only stops the exit code from calling it clean."""
    return summary["crashed_workers"] > 0 or summary["completed_ops"] != summary["expected_total_ops"] or summary.get("errors", 0) > 0


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

    if args.backend == "postgres" and not args.pg_url:
        ap.error("--pg-url is required for --backend postgres")

    worker_counts = [int(x) for x in args.workers.split(",")]
    all_summaries = []
    # A sweep where every worker crashed still produces a well-formed
    # summary (crashed_workers, completed_ops: 0, throughput_ops_per_s:
    # 0.0) -- exiting 0 for that made a broken run indistinguishable from
    # a real (if uneventful) measurement to anything checking the exit
    # code, and let a garbage --out file sit next to a real one the same
    # way. Tracked across the whole worker-count sweep, not just the last
    # iteration, so one bad n_workers value in the middle doesn't get
    # masked by later ones succeeding.
    had_failure = False

    # One disposable schema for this ENTIRE invocation (reused across the
    # worker-count sweep below, dropped once at the very end) -- --pg-url
    # accepts an arbitrary database URL, so this must never touch "public"
    # or any namespace a real deployment might be using. Unset for sqlite;
    # seed_baseline/run_workers/worker.py ignore it on that backend.
    pg_schema = f"bench_{uuid4().hex[:12]}" if args.backend == "postgres" else ""

    try:
        for n_workers in worker_counts:
            print(f"--- seeding baseline ({args.backend}, {args.baseline_users} users{f', schema={pg_schema}' if pg_schema else ''}) ---", file=sys.stderr)
            emails = asyncio.run(seed_baseline(args.backend, args.pg_url, pg_schema, args.baseline_users))

            print(f"--- running {n_workers} workers ({args.backend}, {args.ops_per_worker} ops/worker) ---", file=sys.stderr)
            worker_outputs = run_workers(args.backend, n_workers, args.ops_per_worker, args.read_ratio, emails, args.pg_url, pg_schema)
            summary = summarize(worker_outputs, n_workers, args.ops_per_worker)
            summary["backend"] = args.backend
            all_summaries.append(summary)
            print(json.dumps(summary, indent=2), file=sys.stderr)
            if summary_indicates_failure(summary):
                had_failure = True
    finally:
        if pg_schema:
            print(f"--- dropping isolated schema {pg_schema} ---", file=sys.stderr)
            asyncio.run(drop_isolated_schema(args.pg_url, pg_schema))

    result = {"backend": args.backend, "read_ratio": args.read_ratio, "runs": all_summaries}
    output = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(output)
    # Printed unconditionally, failure or not -- a broken run's diagnostics
    # (crashed_worker_errors, the mismatched op counts) are exactly what's
    # needed to debug it, so the JSON goes out before the exit code below
    # can make anything piping/discarding stdout on a nonzero exit lose it.
    print(output)

    if had_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
