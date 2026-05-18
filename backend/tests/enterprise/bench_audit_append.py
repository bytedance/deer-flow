"""Microbenchmark: AuditMiddleware/append hot path latency (plan §4.3 SLA).

Acceptance: single ``SqliteAuditStorage.append`` P99 < 1 ms on a local
SQLite file. We run 1000 writes against ``sqlite+aiosqlite`` on a tmp
file and report min/avg/P50/P95/P99/max.

This isn't a pytest test (no assertion) — run manually:

    PYTHONPATH=. uv run --active python tests/enterprise/bench_audit_append.py
"""

from __future__ import annotations

import asyncio
import statistics
import tempfile
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import SqliteAuditStorage
from deerflow.persistence.base import Base


async def _setup(db_path: Path):
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)
    # Apply the same pragmas the real EnterpriseDatabase uses for WAL mode.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    return SqliteAuditStorage(sf), engine


async def _run(n: int = 1000) -> list[float]:
    signer = AuditSigner("bench-key")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "bench.db"
        storage, engine = await _setup(db_path)
        # warm-up so the engine's connection pool and SQLite WAL header
        # are paid before we sample latency.
        for _ in range(20):
            ev = AuditEvent(
                event_type=AuditEventType.AGENT_TASK_STARTED,
                user_id="bench",
                resource="thread:bench",
                action="bench",
                details={},
            )
            ev.signature = signer.sign(ev)
            await storage.append(ev)

        latencies_ms: list[float] = []
        for _ in range(n):
            ev = AuditEvent(
                event_type=AuditEventType.AGENT_TASK_STARTED,
                user_id="bench",
                resource="thread:bench",
                action="bench",
                details={"k": "v"},
            )
            ev.signature = signer.sign(ev)
            t0 = time.perf_counter()
            await storage.append(ev)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        await engine.dispose()
        return latencies_ms


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


def main() -> None:
    latencies = asyncio.run(_run())
    print(f"N           = {len(latencies)}")
    print(f"min  (ms)   = {min(latencies):.3f}")
    print(f"avg  (ms)   = {statistics.mean(latencies):.3f}")
    print(f"P50  (ms)   = {_percentile(latencies, 50):.3f}")
    print(f"P95  (ms)   = {_percentile(latencies, 95):.3f}")
    print(f"P99  (ms)   = {_percentile(latencies, 99):.3f}")
    print(f"max  (ms)   = {max(latencies):.3f}")
    p99 = _percentile(latencies, 99)
    target = 1.0
    print(f"SLA (P99<{target}ms): {'PASS' if p99 < target else 'FAIL'}")


if __name__ == "__main__":
    main()
