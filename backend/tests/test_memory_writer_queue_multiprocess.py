"""Cross-process integration test for the single-writer memory queue.

RFC #2283 is specifically about multi-worker correctness: the per-process
writer lease must ensure that even when two independent OS processes each
call ``schedule_memory_update`` concurrently on the same SQLite file, every
task is executed exactly once and the underlying ``agent_memory.seq``
counter advances monotonically without any lost updates.

The in-process tests in :mod:`test_memory_writer_queue` exercise the
lease / queue state machine with mocks, but they cannot detect issues
that only manifest across process boundaries (for example, schema-init
races or ``BEGIN EXCLUSIVE`` semantics inside WAL mode).  This test
closes that gap by spawning real worker processes.
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import sys
import time
from pathlib import Path

import pytest

# ``fork`` carries the already-imported deerflow package into children and is
# significantly faster than ``spawn`` on CI.  We deliberately avoid any
# SQLite connections in the parent prior to forking so no open handles leak.
_CTX = mp.get_context("fork") if sys.platform != "win32" else mp.get_context("spawn")


def _worker_entry(db_path_str: str, label: str, num_tasks: int) -> None:
    """Child-process entry point.

    Replaces ``update_memory_from_conversation`` with a real storage write
    (``load → mutate → save``) so the seq-guard code path is exercised
    end-to-end, then enqueues *num_tasks* tasks via
    ``schedule_memory_update``.  Waits briefly for the writer thread (if
    this process won the lease) to drain the queue before returning.
    """
    # Local imports — keep the module importable even without the dev deps.
    from deerflow.agents.memory import updater as updater_mod
    from deerflow.agents.memory.sqlite_storage import SQLiteMemoryStorage
    from deerflow.agents.memory.writer_queue import schedule_memory_update

    db_path = Path(db_path_str)
    storage = SQLiteMemoryStorage(db_path)

    def fake_update(
        messages,
        thread_id=None,
        agent_name=None,
        correction_detected=False,
        reinforcement_detected=False,
    ):
        # Real load/save so the monotonic ``seq`` guard in SQLiteMemoryStorage
        # actually runs — that's the invariant this test is verifying.
        data = storage.load(agent_name=agent_name)
        facts = list(data.get("facts", []))
        facts.append({"content": f"{label}:{thread_id}"})
        data["facts"] = facts
        return storage.save(data, agent_name=agent_name)

    updater_mod.update_memory_from_conversation = fake_update

    for i in range(num_tasks):
        schedule_memory_update(
            db_path,
            agent_name=None,
            messages=[],
            thread_id=f"{label}-{i}",
        )

    # Give any writer thread spawned in this process time to drain.
    # run_writer_loop is a daemon thread, so we must wait explicitly before
    # the process exits.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            pending = conn.execute(
                "SELECT COUNT(*) FROM memory_update_queue "
                "WHERE status IN ('pending', 'processing')"
            ).fetchone()[0]
            held = conn.execute(
                "SELECT COUNT(*) FROM memory_writer_lock"
            ).fetchone()[0]
        finally:
            conn.close()
        if pending == 0 and held == 0:
            return
        time.sleep(0.1)


def _drain_remaining(db_path: Path) -> None:
    """Parent-side drain: run a writer loop until the queue is empty.

    The test spawns two processes; only one of them can hold the writer
    lease at any given moment, so the losing process may exit with pending
    work still in the queue (processed by the winner).  Once both children
    have joined, we run a final writer loop from the parent to mop up any
    stragglers — this is exactly how a long-lived deployment behaves when
    the writer process is restarted.
    """
    from deerflow.agents.memory import updater as updater_mod
    from deerflow.agents.memory import writer_queue
    from deerflow.agents.memory.sqlite_storage import SQLiteMemoryStorage

    storage = SQLiteMemoryStorage(db_path)

    def fake_update(
        messages,
        thread_id=None,
        agent_name=None,
        correction_detected=False,
        reinforcement_detected=False,
    ):
        data = storage.load(agent_name=agent_name)
        facts = list(data.get("facts", []))
        facts.append({"content": f"parent:{thread_id}"})
        data["facts"] = facts
        return storage.save(data, agent_name=agent_name)

    updater_mod.update_memory_from_conversation = fake_update

    worker_id = f"parent-drainer-{id(db_path)}"
    # Force-acquire (children have exited, so any stale lease is safe to take).
    # Age out whatever lease might remain so try_acquire_writer always wins.
    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        conn.execute("DELETE FROM memory_writer_lock")
        conn.commit()
    finally:
        conn.close()

    assert writer_queue.try_acquire_writer(db_path, worker_id) is True
    if not writer_queue._writer_running.acquire(blocking=False):
        # Another thread inside the parent claims to be running; release it.
        writer_queue._writer_running.release()
        writer_queue._writer_running.acquire()
    try:
        writer_queue.run_writer_loop(db_path, worker_id)
    finally:
        if writer_queue._writer_running.locked():
            try:
                writer_queue._writer_running.release()
            except RuntimeError:
                pass


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="fork-based multiprocessing is Linux/macOS only; spawn mode is too slow for CI",
)
def test_two_processes_do_not_lose_writes(tmp_path: Path) -> None:
    """Two concurrent processes enqueueing on the same DB must not drop writes."""
    db_path = tmp_path / "memory.db"
    # Bootstrap the schema before forking so children don't race on CREATE TABLE.
    from deerflow.agents.memory.writer_queue import init_queue_schema

    init_queue_schema(db_path)

    tasks_per_worker = 5
    p1 = _CTX.Process(
        target=_worker_entry,
        args=(str(db_path), "w1", tasks_per_worker),
    )
    p2 = _CTX.Process(
        target=_worker_entry,
        args=(str(db_path), "w2", tasks_per_worker),
    )
    p1.start()
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)

    assert p1.exitcode == 0, f"worker 1 failed (exitcode={p1.exitcode})"
    assert p2.exitcode == 0, f"worker 2 failed (exitcode={p2.exitcode})"

    # Drain any tasks the losing process left behind.
    _drain_remaining(db_path)

    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM memory_update_queue GROUP BY status"
        ).fetchall()
        status_counts = {r["status"]: r["n"] for r in rows}
        seq_row = conn.execute(
            "SELECT seq, data FROM agent_memory WHERE agent_name = '__global__'"
        ).fetchone()
    finally:
        conn.close()

    total = 2 * tasks_per_worker
    # Every enqueued task must be in a terminal state.
    assert status_counts.get("pending", 0) == 0
    assert status_counts.get("processing", 0) == 0
    # Every task must have produced a successful LLM update; any 'failed'
    # here would indicate a seq-guard violation (concurrent load/save race).
    assert status_counts.get("done", 0) == total, status_counts

    # The storage seq counter must equal the number of successful writes
    # exactly — proving no last-writer-wins collision swallowed an update.
    assert seq_row is not None
    assert int(seq_row["seq"]) == total

    import json

    data = json.loads(seq_row["data"])
    assert len(data["facts"]) == total
    # All worker-labelled thread ids must appear in the final memory.
    contents = {fact["content"] for fact in data["facts"]}
    expected = {
        f"{processor}:{task_label}-{i}"
        for processor in ("w1", "w2", "parent")
        for task_label in ("w1", "w2")
        for i in range(tasks_per_worker)
    }
    # Each enqueued task appears exactly once; its content prefix is whichever
    # worker (w1/w2/parent) ended up processing it.  So each ``label-i`` key
    # must contribute exactly one of the three possible prefixes.
    seen_keys = {c.split(":", 1)[1] for c in contents}
    assert seen_keys == {f"{label}-{i}" for label in ("w1", "w2") for i in range(tasks_per_worker)}
    assert contents.issubset(expected)
