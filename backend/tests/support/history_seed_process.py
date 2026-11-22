"""Independent-process actors for history-seed commit/deletion ordering."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from support.producer_process import CONTEXT, ProducerActors, proceed, receive


async def actor(uri, schema, job, identity, pipe):
    from deerflow.runtime.events.producer import HistorySeedAuthority, RunEventProducerRejected, producer_scope
    from deerflow.runtime.events.store.db import DbRunEventStore

    engine = create_async_engine(uri, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000", "lock_timeout": "8000"}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pg_backend_pid()"))
        pipe.send({"stage": "started", "pid": pid})
        await proceed(pipe)
        events = DbRunEventStore(sf, producer_fencing="strict")
        if job == "delete_locked":
            original = events._invalidate_evidence

            async def held(*args):
                await original(*args)
                pipe.send({"stage": "revoked_uncommitted"})
                await proceed(pipe)

            events._invalidate_evidence = held
            if identity.get("delete_run"):
                await events.delete_by_run("thread", "checkpoint-seed-thread-1", user_id="alice")
            else:
                await events.delete_by_thread("thread", user_id="alice")
            pipe.send({"stage": "done", "deleted": True})
        elif job == "metadata_locked":
            from sqlalchemy import select

            from deerflow.persistence.thread_meta.model import ThreadMetaRow

            async with sf() as session, session.begin():
                await session.scalar(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread").with_for_update())
                pipe.send({"stage": "metadata_held"})
                await proceed(pipe)
            pipe.send({"stage": "done", "released": True})
        elif job == "admission":
            from deerflow.persistence.run.sql import RunRepository
            from deerflow.runtime import ConflictError, RunManager

            manager = RunManager(store=RunRepository(sf), worker_id="other-host")
            try:
                await manager.create_or_reject("thread", user_id="alice")
            except ConflictError:
                pipe.send({"stage": "done", "admitted": False})
            else:
                pipe.send({"stage": "done", "admitted": True})
        else:
            authority = HistorySeedAuthority(**identity["authority"])
            original = events._admit_events

            async def held(session, batch):
                await original(session, batch)
                if job == "seed_locked":
                    pipe.send({"stage": "admitted"})
                    await proceed(pipe)

            events._admit_events = held
            try:
                with producer_scope(authority):
                    await events.put_batch(identity["events"])
            except RunEventProducerRejected:
                pipe.send({"stage": "done", "written": False})
            else:
                pipe.send({"stage": "done", "written": True})
    except BaseException as exc:
        pipe.send({"stage": "error", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        await engine.dispose()
        pipe.close()


def process_entry(*args):
    asyncio.run(actor(*args))


class HistorySeedActors(ProducerActors):
    async def start(self, job):
        parent, child = CONTEXT.Pipe()
        process = CONTEXT.Process(target=process_entry, args=(self.uri, self.schema, job, self.identity, child))
        process.start()
        child.close()
        self.processes.append((process, parent))
        message = await receive(parent)
        assert message["stage"] == "started", message
        return parent, message["pid"]
