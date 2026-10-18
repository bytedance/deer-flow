"""Real checkpointers and run-shaped checkpoint writers for thread-listing tests.

Each saver kind takes a different path through
``deerflow.runtime.checkpointer.thread_spans``: ``memory`` walks ``list(None)``
(one thread at a time), ``sqlite`` and ``postgres`` query the primary-key
index, and ``cached-sqlite`` must unwrap the delta-history cache first.
``postgres`` runs only with ``DEERFLOW_TEST_POSTGRES_URL`` (or
``TEST_POSTGRES_URI``) and the ``postgres`` extra installed, in a throwaway
schema.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint, uuid6

SAVER_KINDS = ("memory", "sqlite", "cached-sqlite", "postgres")
INDEXED_SAVER_KINDS = frozenset({"sqlite", "cached-sqlite", "postgres"})


@contextmanager
def make_saver(kind: str) -> Iterator[Any]:
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
    elif kind in ("sqlite", "cached-sqlite"):
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            if kind == "cached-sqlite":
                from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
                from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

                saver = CachedHistorySaver(saver, MemoryCheckpointHistoryCache(128), key_prefix="thread-list-test")
            yield saver
        finally:
            conn.close()
    elif kind == "postgres":
        url = os.getenv("DEERFLOW_TEST_POSTGRES_URL") or os.getenv("TEST_POSTGRES_URI")
        if not url:
            pytest.skip("set TEST_POSTGRES_URI or DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL tests")
        postgres = pytest.importorskip("langgraph.checkpoint.postgres")
        import psycopg

        url = url.replace("postgresql+asyncpg://", "postgresql://")
        schema = f"thread_list_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f'CREATE SCHEMA "{schema}"')
            try:
                with psycopg.connect(url, autocommit=True, options=f"-c search_path={schema}") as conn:
                    saver = postgres.PostgresSaver(conn)
                    saver.setup()
                    yield saver
            finally:
                admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    else:
        raise ValueError(kind)


def _put(saver: Any, config: dict, checkpoint: dict, metadata: dict, title: str | None, version: int) -> dict:
    new_versions: dict[str, Any] = {}
    if title is not None:
        # Channel values persist only for channels named in ``new_versions``,
        # and InMemorySaver keys their blobs by version.
        new_versions = {"title": version}
        checkpoint["channel_values"] = {"title": title}
        checkpoint["channel_versions"] = {"title": version}
    return saver.put(config, checkpoint, metadata, new_versions)


def put_thread(
    saver: Any,
    thread_id: str,
    timestamps: list[str],
    *,
    title: str | None = None,
    checkpoint_ns: str = "",
    first_step: int = -1,
    first_source: str = "input",
) -> list[str]:
    """Write one checkpoint per timestamp, chained like a run, and return their ids.

    The default first checkpoint is a run's input checkpoint (``step`` -1). A
    Gateway branch is seeded by ``update_state`` instead: pass
    ``first_step=0, first_source="branch"``.
    """
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
    checkpoint_ids = []
    for offset, ts in enumerate(timestamps):
        checkpoint = empty_checkpoint()
        checkpoint["ts"] = ts
        metadata = {"source": first_source if offset == 0 else "loop", "step": first_step + offset, "parents": {}}
        config = _put(saver, config, checkpoint, metadata, f"{title} #{offset}" if title else None, offset + 1)
        checkpoint_ids.append(config["configurable"]["checkpoint_id"])
    return checkpoint_ids


def put_goal_write(saver: Any, thread_id: str) -> str:
    """Mirror ``runtime.goal.write_thread_goal``: copy the latest checkpoint under a fresh id, keeping its ``ts``."""
    latest = saver.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    checkpoint = dict(latest.checkpoint)
    checkpoint["id"] = str(uuid6())
    metadata = {**latest.metadata, "source": "update", "step": latest.metadata.get("step", 0) + 1}
    config = saver.put(latest.config, checkpoint, metadata, {})
    return config["configurable"]["checkpoint_id"]
