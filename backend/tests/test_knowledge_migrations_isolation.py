"""The extension's migration chain beside the host's (Task 4).

Pins the two-chain contract: the extension's revisions produce exactly the schema its
models declare; the host's chain leaves the ``kb_`` tables and their rows alone; each
chain keeps its own version table; and the ``kb_`` prefix registers cleanly with the
host's autogenerate filter.
"""

from __future__ import annotations

from pathlib import Path

import deerflow_knowledge.models  # noqa: F401 - registers the extension's tables
import sqlalchemy as sa
from deerflow_knowledge.db import Base as KnowledgeBase
from deerflow_knowledge.migrations.runner import run_knowledge_migrations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_KB_TABLES = {"kb_knowledge_bases", "kb_documents", "kb_chunks", "kb_eval_runs"}
#: alembic's own bookkeeping tables are not part of either schema (one path creates them,
#: the other does not), so comparing them would be a guaranteed false positive.
_BOOKKEEPING = {"alembic_version", "kb_alembic_version"}


def _url(tmp_path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / name}"


def _reflect_columns_sync(sync_conn) -> dict[str, dict[str, dict]]:
    insp = sa.inspect(sync_conn)
    out: dict[str, dict[str, dict]] = {}
    for table in insp.get_table_names():
        if table in _BOOKKEEPING:
            continue
        out[table] = {c["name"]: c for c in insp.get_columns(table)}
    return out


async def _reflect_columns(engine) -> dict[str, dict[str, dict]]:
    async with engine.connect() as conn:
        return await conn.run_sync(_reflect_columns_sync)


async def test_the_chain_produces_exactly_the_models_schema(tmp_path: Path) -> None:
    """create_all and the chain must agree column by column (the host's own drift guard,
    replayed for the extension's private metadata)."""
    fresh = create_async_engine(_url(tmp_path, "fresh.db"))
    upgraded = create_async_engine(_url(tmp_path, "upgraded.db"))
    try:
        async with fresh.begin() as conn:
            await conn.run_sync(KnowledgeBase.metadata.create_all)

        await run_knowledge_migrations(async_sessionmaker(upgraded, expire_on_commit=False))

        fresh_tables = await _reflect_columns(fresh)
        upgraded_tables = await _reflect_columns(upgraded)
        assert set(fresh_tables) == set(upgraded_tables) == _KB_TABLES
        for table in sorted(fresh_tables):
            fresh_cols, upgraded_cols = fresh_tables[table], upgraded_tables[table]
            assert set(fresh_cols) == set(upgraded_cols), f"{table}: column-set drift"
            for name in sorted(fresh_cols):
                assert fresh_cols[name]["nullable"] == upgraded_cols[name]["nullable"], f"{table}.{name}: nullable drift"
        # The two server-defaulted eval_runs columns and the partial unique index travel
        # through both paths identically.
        for name in ("is_baseline", "environment"):
            assert fresh_tables["kb_eval_runs"][name]["default"] is not None
            assert upgraded_tables["kb_eval_runs"][name]["default"] is not None
        async with upgraded.connect() as conn:
            indexes = (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='kb_eval_runs'"))).scalars().all()
        assert "uq_eval_runs_kb_baseline" in indexes
    finally:
        await fresh.dispose()
        await upgraded.dispose()


async def test_a_host_upgrade_leaves_the_extension_tables_and_rows_alone(tmp_path: Path) -> None:
    """The host's own bootstrap re-run (its ``upgrade head`` path) must not touch kb_."""
    from deerflow_knowledge.store import KnowledgeStore

    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.bootstrap import bootstrap_schema
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        await run_knowledge_migrations(sf)
        await KnowledgeStore(sf).create_kb(kb_id="kb-1", owner_id="u-1", name="库")

        engine = sf.kw["bind"]
        await bootstrap_schema(engine, backend="sqlite")

        async with sf() as session:
            kb_tables = (await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kb_%' ORDER BY name"))).scalars().all()
            survivors = (await session.execute(text("SELECT count(*) FROM kb_knowledge_bases"))).scalar_one()
            host_version = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
            extension_version = (await session.execute(text("SELECT version_num FROM kb_alembic_version"))).scalar_one()
        assert kb_tables == ["kb_alembic_version", "kb_chunks", "kb_documents", "kb_eval_runs", "kb_knowledge_bases"]
        assert survivors == 1
        # Independent bookkeeping: the host chain's head and the extension's own head.
        assert host_version and host_version != extension_version
        assert extension_version == "0002_eval_runs"
    finally:
        await close_engine()


class TestTheKbPrefixRegistersWithTheHostFilter:
    """The declared ``table_prefix: kb_`` end of the contract (the loader registers it)."""

    def setup_method(self):
        from deerflow.persistence.migrations import _env_filters

        self._saved = set(_env_filters.EXTENSION_TABLE_PREFIXES)

    def teardown_method(self):
        from deerflow.persistence.migrations import _env_filters

        _env_filters.EXTENSION_TABLE_PREFIXES.clear()
        _env_filters.EXTENSION_TABLE_PREFIXES.update(self._saved)

    def test_the_kb_prefix_collides_with_no_host_table(self):
        from deerflow.persistence.migrations._env_filters import register_extension_table_prefix

        register_extension_table_prefix("kb_")  # raises ValueError on any host-table collision

    def test_registered_kb_tables_are_hidden_from_host_autogenerate(self):
        from deerflow.persistence.migrations._env_filters import include_object, register_extension_table_prefix

        register_extension_table_prefix("kb_")
        for name in ("kb_knowledge_bases", "kb_documents", "kb_chunks", "kb_eval_runs"):
            assert include_object(None, name, "table", True, None) is False, name
        assert include_object(None, "runs", "table", True, None) is True
