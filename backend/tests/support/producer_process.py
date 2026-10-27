"""OS-process actors for the production producer-fencing protocol."""

from __future__ import annotations

import asyncio
import multiprocessing
import time
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

CONTEXT = multiprocessing.get_context("spawn")


async def receive(pipe, timeout=12):
    def bounded():
        assert pipe.poll(timeout), "Producer actor failed to reach its barrier"
        return pipe.recv()

    return await asyncio.to_thread(bounded)


async def proceed(pipe):
    assert await receive(pipe) == "go"


async def actor(uri, schema, job, identity, pipe):
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.events.producer import producer_authority, producer_scope
    from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.terminal import RecoveryTerminalPublisher
    from deerflow.runtime.journal import RunJournal

    engine = create_async_engine(uri, pool_size=1, max_overflow=0, pool_timeout=1, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000", "lock_timeout": "8000"}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        pipe.send({"stage": "started", "pid": pid})
        await proceed(pipe)
        runs = RunRepository(sf)
        events = DbRunEventStore(sf, producer_fencing="strict")
        authority = producer_authority(SimpleNamespace(**identity))
        if job in ("writer_locked", "writer_late", "writer"):
            original = events._admit_events

            async def barrier(session, batch):
                if job == "writer_late":
                    pipe.send({"stage": "before_admission"})
                    await proceed(pipe)
                await original(session, batch)
                if job == "writer_locked":
                    pipe.send({"stage": "admitted"})
                    await proceed(pipe)

            events._admit_events = barrier
            with producer_scope(authority):
                journal = RunJournal(identity["run_id"], identity["thread_id"], events, user_id=identity["user_id"], flush_threshold=100)
                journal.record_middleware("race", name="race", hook="process", action="accepted", changes={})
                try:
                    await journal.flush()
                    pipe.send({"stage": "done", "written": True})
                except RunEventStoreNotCommittedError:
                    pipe.send({"stage": "done", "written": False})
                finally:
                    await journal.close(flush=False)
        elif job in ("takeover", "takeover_locked"):
            if job == "takeover_locked":
                original_commit = AsyncSession.commit

                async def held(session):
                    pipe.send({"stage": "revoked_uncommitted"})
                    await proceed(pipe)
                    return await original_commit(session)

                AsyncSession.commit = held
            claimed = await runs.claim_for_takeover(identity["run_id"], grace_seconds=0, error="crashed worker")
            if job == "takeover_locked":
                AsyncSession.commit = original_commit
            assert claimed
            publisher = RecoveryTerminalPublisher(events, runs)
            target = publisher.authorize_takeover(
                claimed=claimed,
                thread_id=identity["thread_id"],
                run_id=identity["run_id"],
                user_id=identity["user_id"],
                operation_kind="run",
                run_incarnation=identity["run_incarnation"],
                retention_revision=identity["evidence_retention_revision"],
            )
            assert (await publisher.publish(target)).confirmed
            pipe.send({"stage": "done", "taken": True})
        elif job in ("delete_locked", "delete_waiting"):
            if job == "delete_waiting":
                original_thread_fence = events._acquire_thread_mutation_fence

                async def after_clock(session, thread_id):
                    pipe.send({"stage": "clock_held"})
                    await proceed(pipe)
                    await original_thread_fence(session, thread_id)

                DbRunEventStore._acquire_thread_mutation_fence = staticmethod(after_clock)
            original_invalidate = events._invalidate_evidence

            async def held(*args, **kwargs):
                await original_invalidate(*args, **kwargs)
                if job == "delete_locked":
                    pipe.send({"stage": "deleted_uncommitted"})
                    await proceed(pipe)

            events._invalidate_evidence = held
            await events.delete_by_run(identity["thread_id"], identity["run_id"], user_id=identity["user_id"])
            pipe.send({"stage": "done", "deleted": True})
        else:
            raise AssertionError(job)
    except BaseException as exc:
        pipe.send({"stage": "error", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        await engine.dispose()
        pipe.close()


def process_entry(*args):
    asyncio.run(actor(*args))


class ProducerActors:
    def __init__(self, uri, schema, identity, observer):
        self.uri, self.schema, self.identity, self.observer = uri, schema, identity, observer
        self.processes = []

    async def start(self, job):
        parent, child = CONTEXT.Pipe()
        process = CONTEXT.Process(target=process_entry, args=(self.uri, self.schema, job, self.identity, child))
        process.start()
        child.close()
        self.processes.append((process, parent))
        message = await receive(parent)
        assert message["stage"] == "started", message
        return parent, message["pid"]

    async def blocked(self, waiter, holder):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            async with self.observer.connect() as connection:
                blockers = await connection.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
            if holder in blockers:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("Expected PostgreSQL lock wait was not observed")

    async def close(self):
        for process, pipe in self.processes:
            if process.is_alive():
                try:
                    for _ in range(3):
                        pipe.send("go")
                except (BrokenPipeError, EOFError):
                    pass
        for process, pipe in self.processes:
            await asyncio.to_thread(process.join, 3)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 3)
            pipe.close()
