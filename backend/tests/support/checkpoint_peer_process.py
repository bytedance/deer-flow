"""Write one checkpoint from an independent PostgreSQL client process."""

import asyncio
import os
import sys
from typing import TypedDict

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.postgres_schema import dsn_with_search_path
from deerflow.persistence.postgres_url import normalize_asyncpg_url
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus


class State(TypedDict):
    value: str


async def node(state: State) -> State:
    return {"value": "new"}


async def main(thread_id: str, schema: str) -> None:
    uri = os.environ["TEST_POSTGRES_URI"]
    engine = create_async_engine(
        normalize_asyncpg_url(uri),
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        repo = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        ownership = RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True)
        manager = RunManager(store=repo, worker_id="worker-b", run_ownership_config=ownership)
        await manager.reconcile_orphaned_inflight_runs(
            error="reclaimed",
            stop_reason=ORPHAN_RECOVERY_STOP_REASON,
        )
        new_run = await manager.create_or_reject(thread_id, user_id="alice")
        await manager.set_status(new_run.run_id, RunStatus.running)

        builder = StateGraph(State)
        builder.add_node("node", node)
        builder.add_edge(START, "node")
        builder.add_edge("node", END)
        async with AsyncPostgresSaver.from_conn_string(dsn_with_search_path(uri, schema)) as saver:
            await builder.compile(checkpointer=saver).ainvoke(
                {"value": "new"},
                config={"configurable": {"thread_id": thread_id}},
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
