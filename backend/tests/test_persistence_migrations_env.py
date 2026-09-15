"""Tests for the ``include_object`` filter used by ``migrations/env.py``.

LangGraph checkpointer tables (``checkpoints`` and friends) live alongside
DeerFlow's own tables in the same database. Alembic must NEVER emit DDL for
them or a future ``alembic revision --autogenerate`` would propose
``drop_table('checkpoints')`` whenever LangGraph's tables are reflected from
a live DB.

The filter is the only line of defence between an honest autogenerate run
and a destructive revision. It lives in ``_env_filters.py`` so it can be unit
tested without alembic's import-time machinery.
"""

from __future__ import annotations

import sqlalchemy as sa

from deerflow.persistence.migrations._env_filters import (
    LANGGRAPH_OWNED_TABLES,
    include_object,
)


def _table(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData())


def test_filter_excludes_langgraph_checkpoint_tables() -> None:
    for owned in (
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    ):
        assert include_object(_table(owned), owned, "table", True, None) is False


def test_filter_includes_deerflow_tables() -> None:
    for owned in ("runs", "threads_meta", "feedback", "users", "channel_connections"):
        assert include_object(_table(owned), owned, "table", True, None) is True


def test_filter_excludes_indexes_on_langgraph_tables() -> None:
    # An Index whose parent table is LangGraph-owned must also be filtered out;
    # otherwise autogenerate would emit drop_index against tables alembic does
    # not own.
    md = sa.MetaData()
    parent = sa.Table("checkpoints", md, sa.Column("id", sa.Integer, primary_key=True))
    idx = sa.Index("ix_checkpoints_anything", parent.c.id)
    assert include_object(idx, idx.name, "index", True, None) is False


def test_filter_includes_indexes_on_deerflow_tables() -> None:
    md = sa.MetaData()
    parent = sa.Table("runs", md, sa.Column("run_id", sa.String, primary_key=True))
    idx = sa.Index("ix_runs_something", parent.c.run_id)
    assert include_object(idx, idx.name, "index", True, None) is True


def test_langgraph_owned_tables_set_is_complete() -> None:
    # Pin the explicit set so an inadvertent removal -- e.g. someone simplifying
    # the filter -- requires a test diff that surfaces the change.
    assert LANGGRAPH_OWNED_TABLES == frozenset(
        {
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
            "checkpoint_migrations",
        }
    )


def test_env_module_wires_busy_timeout_for_sqlite() -> None:
    """Regression for the cross-process bootstrap pitfall: alembic spawns its
    own engine inside ``env.py::run_migrations_online`` and that engine does
    NOT inherit PRAGMAs from the production engine. Without an event listener
    here, its connections would use the default 5s busy_timeout and racy
    multi-process bootstrap would fail with ``database is locked`` instead of
    waiting for the file lock.

    We check the source rather than execute env.py (which would try to drive
    alembic on import) so this test stays a pure parity check.
    """
    from pathlib import Path  # noqa: PLC0415

    env_path = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/persistence/migrations/env.py"
    src = env_path.read_text(encoding="utf-8")
    assert "PRAGMA busy_timeout=30000" in src or "PRAGMA busy_timeout = 30000" in src, (
        "env.py must set busy_timeout on its alembic-spawned engine; without it, cross-process bootstrap on SQLite fails fast instead of waiting for the file lock"
    )
    assert 'listens_for(connectable.sync_engine, "connect")' in src, "busy_timeout must be wired via an event listener so EVERY connection alembic opens gets the PRAGMA, not just one initial probe"


class TestExtensionOwnedTables:
    """Extension tables share the database but not alembic's view of it.

    An extension owns its own MetaData and its own migration chain, so
    autogenerate reflecting them from a live database would find them absent
    from Base.metadata and propose dropping them.

    Note the scope: `make migrate-rev` is already safe, because
    `_autogen_revision.py` diffs against a throwaway SQLite built from the
    migration chain, where no extension table exists. The exposed path is a
    direct `alembic revision --autogenerate` from the migrations directory,
    whose `alembic.ini` points at a real `./data/deerflow.db` — the same path
    `LANGGRAPH_OWNED_TABLES` covers.
    """

    def setup_method(self):
        from deerflow.persistence.migrations import _env_filters

        self._saved = set(_env_filters.EXTENSION_TABLE_PREFIXES)

    def teardown_method(self):
        from deerflow.persistence.migrations import _env_filters

        _env_filters.EXTENSION_TABLE_PREFIXES.clear()
        _env_filters.EXTENSION_TABLE_PREFIXES.update(self._saved)

    def test_a_registered_prefix_is_excluded(self):
        from deerflow.persistence.migrations._env_filters import include_object, register_extension_table_prefix

        register_extension_table_prefix("ext_")
        assert include_object(None, "ext_events", "table", True, None) is False

    def test_an_unregistered_table_is_still_included(self):
        from deerflow.persistence.migrations._env_filters import include_object

        assert include_object(None, "runs", "table", True, None) is True

    def test_an_index_on_an_excluded_table_is_excluded_too(self):
        from types import SimpleNamespace

        from deerflow.persistence.migrations._env_filters import include_object, register_extension_table_prefix

        register_extension_table_prefix("ext_")
        index = SimpleNamespace(table=SimpleNamespace(name="ext_events"))
        assert include_object(index, "ix_ext_events_seq", "index", True, None) is False

    def test_a_constraint_on_an_excluded_table_is_excluded_too(self):
        # A filter that drops the table but keeps its constraints still emits
        # broken DDL (e.g. a dangling unique_constraint against a table
        # alembic no longer believes exists).
        from types import SimpleNamespace

        from deerflow.persistence.migrations._env_filters import include_object, register_extension_table_prefix

        register_extension_table_prefix("ext_")
        constraint = SimpleNamespace(table=SimpleNamespace(name="ext_events"))
        assert include_object(constraint, "uq_ext_events_seq", "unique_constraint", True, None) is False

    def test_registration_rejects_an_empty_prefix(self):
        import pytest

        from deerflow.persistence.migrations._env_filters import register_extension_table_prefix

        with pytest.raises(ValueError):
            register_extension_table_prefix("")

    def test_langgraph_exclusion_is_unaffected(self):
        from deerflow.persistence.migrations._env_filters import include_object

        assert include_object(None, "checkpoints", "table", True, None) is False

    def test_registration_rejects_a_prefix_that_would_hide_a_host_table(self):
        """A typo like table_prefix: "run" would silently stop alembic from
        managing the host's own `runs` / `run_events` tables. This must fail
        loudly at registration time rather than degrade autogenerate silently."""
        import pytest

        from deerflow.persistence.migrations._env_filters import register_extension_table_prefix

        with pytest.raises(ValueError, match="runs"):
            register_extension_table_prefix("run")

    def test_registration_accepts_a_prefix_that_matches_no_host_table(self):
        from deerflow.persistence.migrations._env_filters import EXTENSION_TABLE_PREFIXES, register_extension_table_prefix

        register_extension_table_prefix("acme_ext_")
        assert "acme_ext_" in EXTENSION_TABLE_PREFIXES


_PREFIX_PROBE = """
import json, sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

import deerflow.persistence.models  # noqa: F401 - populate Base.metadata
from deerflow.persistence.base import Base
from deerflow.persistence.migrations._env_filters import (
    include_object,
    register_configured_extension_table_prefixes,
)

db_path = sys.argv[1]

# An extension-owned table in the shape an extension's own chain leaves it:
# present in the database, absent from the host's Base.metadata.
foreign = MetaData()
Table("acme_events", foreign, Column("id", Integer, primary_key=True), Column("body", String(16)))
engine = create_engine("sqlite:///" + db_path)
foreign.create_all(engine)

registered = register_configured_extension_table_prefixes()

with engine.connect() as conn:
    ctx = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": False})
    diffs = compare_metadata(ctx, Base.metadata)

dropped = [op[1].name for op in diffs if isinstance(op, tuple) and op and op[0] == "remove_table"]
print(json.dumps({"registered": list(registered), "dropped": dropped}))
"""


class TestPrefixesReachTheAlembicProcess:
    """The filter is only as good as whatever populates it.

    Every other test here registers a prefix in-process and then asserts
    ``include_object``. Those pass for a real reason — the filter works — and
    still missed that the sole caller of ``register_extension_table_prefix``
    was ``load_extensions()``, which runs in the Gateway and never in the
    alembic process, leaving the set empty exactly where alembic reads it.
    These cover the wiring rather than the filter.
    """

    def _probe(self, tmp_path, config_yaml: str) -> dict:
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        (tmp_path / "config.yaml").write_text(config_yaml, encoding="utf-8")
        script = tmp_path / "probe.py"
        script.write_text(_PREFIX_PROBE, encoding="utf-8")

        backend = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, str(script), str(tmp_path / "probe.db")],
            cwd=str(backend),
            env={**os.environ, "DEER_FLOW_CONFIG_PATH": str(tmp_path / "config.yaml"), "PYTHONPATH": str(backend)},
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_a_declared_prefix_survives_into_a_fresh_process(self, tmp_path):
        """No Gateway has run here, so nothing called load_extensions()."""
        result = self._probe(tmp_path, "plugins:\n  - use: acme_ext:install\n    table_prefix: acme_\n")

        assert result["registered"] == ["acme_"]
        assert "acme_events" not in result["dropped"], "autogenerate proposed dropping an extension-owned table"

    def test_an_undeclared_table_is_still_proposed_for_dropping(self, tmp_path):
        """The control. Without it the test above could pass on a filter that excludes everything."""
        result = self._probe(tmp_path, "plugins: []\n")

        assert result["registered"] == []
        assert "acme_events" in result["dropped"], "expected an undeclared foreign table to be reflected and dropped"

    def test_an_empty_prefix_does_not_take_the_alembic_process_down(self, tmp_path):
        """One declaration must not mean two different things in two processes.

        This reader parses raw YAML so it never imports the extension, which
        also means ``ExtensionSpec`` never validates what it sees. Rejecting an
        empty prefix here would surface a config-schema error from the wrong
        process twice over: an operator does not expect to hear about a
        malformed ``config.yaml`` from alembic, and Gateway startup runs this
        same module through ``bootstrap_schema`` — so a raise would take the
        Gateway down with a message about migrations. ``ExtensionSpec`` owns
        that verdict (see the paired test below).
        """
        result = self._probe(tmp_path, 'plugins:\n  - use: acme_ext:install\n    table_prefix: ""\n')

        assert result["registered"] == []
        # And it degrades to the no-prefix behaviour rather than to
        # "" matching every table name.
        assert "acme_events" in result["dropped"]

    def test_a_non_string_prefix_does_not_take_the_alembic_process_down(self, tmp_path):
        result = self._probe(tmp_path, "plugins:\n  - use: acme_ext:install\n    table_prefix: 7\n")

        assert result["registered"] == []

    def test_env_module_registers_configured_prefixes(self):
        """``env.py`` cannot be imported outside alembic, so pin the call in its source."""
        import ast
        from pathlib import Path

        env_py = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/persistence/migrations/env.py"
        called = {node.func.id for node in ast.walk(ast.parse(env_py.read_text(encoding="utf-8"))) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        assert "register_configured_extension_table_prefixes" in called, "env.py must populate the prefix set; include_object reads it in that process"
