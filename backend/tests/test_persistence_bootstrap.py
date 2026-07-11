"""Tests for ``deerflow.persistence.bootstrap.bootstrap_schema``.

Covers the three-branch decision table:

| DB state                              | Action                                  |
|---------------------------------------|-----------------------------------------|
| empty                                 | create_all + stamp head                 |
| legacy (DeerFlow tables, no alembic_version) | create_all (baseline tables only, backfill) + stamp baseline + upgrade head |
| versioned                             | upgrade head                            |

Each test seeds a temp SQLite to the relevant pre-state, runs
``bootstrap_schema``, and asserts both the resulting schema and the
``alembic_version`` row.

The legacy branch is exercised across three scenarios: token-usage column
missing, token-usage column already present, and a baseline-era table
missing entirely (the ``channel_*`` backfill case). The first two prove the
column-level idempotent helpers handle both sub-cases; the third proves the
table-level backfill works.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# Pre-import models so Base.metadata is populated before bootstrap reads it.
import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import (
    _BASELINE_TABLE_NAMES,
    _decide_state,
    _get_alembic_config,
    _get_head_revision,
    _run_baseline_create_all_sync,
    _upgrade,
    bootstrap_schema,
)
from deerflow.persistence.migrations._helpers import _normalize_default

# Mark only async tests via the decorator below; module-level pytestmark would
# spuriously warn for the sync ``TestDecideState`` cases.
asyncio_test = pytest.mark.asyncio


HEAD = "0004_run_ownership"
BASELINE = "0001_baseline"


def _url(tmp_path: Path, name: str = "test.db") -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}"


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))


async def _runs_columns(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: {col["name"] for col in sa.inspect(c).get_columns("runs")})


async def _runs_column_meta(engine, column_name: str) -> dict:
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: sa.inspect(c).get_columns("runs"))
    for c in cols:
        if c["name"] == column_name:
            return c
    raise AssertionError(f"column {column_name!r} not found in runs")


async def _runs_index_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: {ix["name"] for ix in sa.inspect(c).get_indexes("runs")})


async def _alembic_version(engine) -> str | None:
    async with engine.connect() as conn:
        row = await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        return row.scalar()


async def _seed_legacy_without_column(engine) -> None:
    """Build the pre-#3658 schema: create_all, then drop the new column."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        # SQLite supports DROP COLUMN from 3.35.0; the test runner pins recent
        # Python which bundles a 3.40+ sqlite, so this is safe.
        await conn.execute(sa.text("ALTER TABLE runs DROP COLUMN token_usage_by_model"))


async def _seed_legacy_with_column(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_legacy_missing_channel_tables(engine) -> None:
    """Build a pre-#1930 schema: baseline tables exist but ``channel_*`` do not.

    Models the worst-case legacy DB the bootstrap layer has to repair -- a
    user who upgraded across multiple releases and never had the channel_*
    tables provisioned in the first place. We achieve it by running the full
    ``create_all`` and then dropping the channel_* tables in FK-dependency
    order (credentials/conversations reference channel_connections).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        for table in (
            "channel_credentials",
            "channel_conversations",
            "channel_oauth_states",
            "channel_connections",
        ):
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))


# ---------------------------------------------------------------------------
# Branch 1: empty DB
# ---------------------------------------------------------------------------


@asyncio_test
async def test_empty_branch_creates_all_and_stamps_head(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await bootstrap_schema(engine, backend="sqlite")
        tables = await _table_names(engine)
        for required in {
            "runs",
            "threads_meta",
            "feedback",
            "users",
            "run_events",
            "channel_connections",
            "channel_credentials",
            "channel_conversations",
            "channel_oauth_states",
            "alembic_version",
        }:
            assert required in tables, f"missing table: {required}"
        assert "token_usage_by_model" in await _runs_columns(engine)
        assert await _alembic_version(engine) == HEAD
        # The partial unique index on (thread_id WHERE status IN pending/running)
        # must exist on a fresh DB because the empty-branch stamps head without
        # running migrations, so the index has to come from ``Base.metadata``.
        indexes = await _runs_index_names(engine)
        assert "uq_runs_thread_active" in indexes, indexes
        assert "ix_runs_lease" in indexes, indexes
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Branch 2: legacy DB without token_usage_by_model
# ---------------------------------------------------------------------------


@asyncio_test
async def test_legacy_without_column_branch_upgrades(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await _seed_legacy_without_column(engine)
        assert "token_usage_by_model" not in await _runs_columns(engine)
        assert "alembic_version" not in await _table_names(engine)

        await bootstrap_schema(engine, backend="sqlite")

        assert "token_usage_by_model" in await _runs_columns(engine)
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Legacy backfill: a DB that pre-dates a later-added baseline table (e.g. the
# ``channel_*`` tables from PR #1930) must end up with all baseline tables
# after bootstrap, otherwise the channels API 500s with ``no such table``.
# The fix runs ``create_all`` (idempotent) before ``stamp 0001_baseline`` so
# missing baseline tables are backfilled with their current ORM schema.
# ---------------------------------------------------------------------------


@asyncio_test
async def test_legacy_missing_channel_tables_get_backfilled(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await _seed_legacy_missing_channel_tables(engine)
        tables = await _table_names(engine)
        # Sanity-check the seeded pre-state: ``runs`` triggers the legacy
        # branch (has_deerflow_tables=True, no alembic_version) while the
        # channel_* tables are absent.
        assert "runs" in tables
        assert "alembic_version" not in tables
        for missing in {
            "channel_connections",
            "channel_credentials",
            "channel_conversations",
            "channel_oauth_states",
        }:
            assert missing not in tables, f"seed should not have {missing}"

        await bootstrap_schema(engine, backend="sqlite")

        tables = await _table_names(engine)
        for required in {
            "channel_connections",
            "channel_credentials",
            "channel_conversations",
            "channel_oauth_states",
        }:
            assert required in tables, f"legacy backfill missed: {required}"
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Branch 3: legacy DB that ALREADY has the column (post-#3658 create_all,
# or user-applied manual ALTER). The branch is the same as the
# legacy-without-column case -- bootstrap stamps baseline and tries to
# upgrade. The idempotent revision helper (``safe_add_column``) silently
# skips when the column is present, so the schema does not change.
# ---------------------------------------------------------------------------


@asyncio_test
async def test_legacy_with_column_branch_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await _seed_legacy_with_column(engine)
        assert "token_usage_by_model" in await _runs_columns(engine)
        assert "alembic_version" not in await _table_names(engine)
        cols_before = await _runs_columns(engine)

        await bootstrap_schema(engine, backend="sqlite")

        cols_after = await _runs_columns(engine)
        assert cols_after == cols_before, "idempotent upgrade should not alter schema"
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Drift-warning guard: a column re-added by a manual ALTER (e.g. the #3682
# workaround) survives the legacy branch because ``safe_add_column`` is
# name-keyed, but the helper must ``logger.warning`` so the operator notices
# the residual nullability / server_default / type drift from the model.
# Two scenarios are pinned: (1) nullable JSON workaround -- nullability +
# server_default drift fire, type matches; (2) ``TEXT NOT NULL DEFAULT
# '{}'`` workaround -- only type drifts, must STILL fire thanks to the
# JSON/TEXT family check in ``_type_equivalent``.
# ---------------------------------------------------------------------------


@asyncio_test
async def test_legacy_with_manual_workaround_column_warns_on_drift(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        # Pre-#3658 schema with a workaround-style re-add: nullable JSON,
        # no server default -- diverges from the model's NOT NULL DEFAULT '{}'.
        # Type matches (JSON vs JSON) so the type-equivalence check stays quiet
        # and the warning fires purely on nullability + server_default.
        await _seed_legacy_without_column(engine)
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE runs ADD COLUMN token_usage_by_model JSON"))

        with caplog.at_level("WARNING", logger="deerflow.persistence.migrations._helpers"):
            await bootstrap_schema(engine, backend="sqlite")

        # Bootstrap still completes -- the helper does not block on drift.
        assert await _alembic_version(engine) == HEAD
        # And the manually-added column survives untouched (no auto-repair).
        col = await _runs_column_meta(engine, "token_usage_by_model")
        assert col["nullable"] is True

        drift_warnings = [r for r in caplog.records if r.levelname == "WARNING" and r.name == "deerflow.persistence.migrations._helpers" and "safe_add_column" in r.getMessage() and "token_usage_by_model" in r.getMessage()]
        assert drift_warnings, "expected safe_add_column to warn about the drifted column"
        msg = drift_warnings[0].getMessage()
        assert "nullable" in msg
        assert "server_default" in msg
        # Type info is always echoed in the payload for triage context.
        assert "actual_type=" in msg and "desired_type=" in msg, f"warning missing type info: {msg!r}"
        # JSON ≈ JSON, so the equivalence check must NOT produce a "type" diff
        # entry here -- that would be a false positive on the matching-type case.
        assert "type actual=" not in msg, f"unexpected type drift on matching JSON column: {msg!r}"
    finally:
        await engine.dispose()


@asyncio_test
async def test_legacy_with_wrong_type_workaround_warns_on_type_drift(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The precise reviewer scenario: nullability + server_default match the
    model, only the type is wrong. Pre-family-check, this returned zero
    warning (silent JSON-vs-TEXT drift). The family check in
    ``_type_equivalent`` must catch this while leaving JSON/JSONB pairs
    equivalent so Postgres dialect synonyms don't false-positive."""
    engine = create_async_engine(_url(tmp_path))
    try:
        # Reviewer's exact workaround: right nullability/default, wrong type.
        await _seed_legacy_without_column(engine)
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE runs ADD COLUMN token_usage_by_model TEXT NOT NULL DEFAULT '{}'"))

        with caplog.at_level("WARNING", logger="deerflow.persistence.migrations._helpers"):
            await bootstrap_schema(engine, backend="sqlite")

        assert await _alembic_version(engine) == HEAD
        # No auto-repair: the TEXT column survives unchanged so the operator
        # can decide whether to ALTER it themselves.
        col = await _runs_column_meta(engine, "token_usage_by_model")
        assert col["nullable"] is False

        drift_warnings = [r for r in caplog.records if r.levelname == "WARNING" and r.name == "deerflow.persistence.migrations._helpers" and "safe_add_column" in r.getMessage() and "token_usage_by_model" in r.getMessage()]
        assert drift_warnings, "expected safe_add_column to warn about pure type drift (was silent before the family check)"
        msg = drift_warnings[0].getMessage()
        # The drift entry must explicitly name the type mismatch -- this is
        # what was missing before the family check existed.
        assert "type actual=" in msg and "desired=" in msg, f"warning missing type drift entry: {msg!r}"
        assert "TEXT" in msg and "JSON" in msg, f"warning missing TEXT/JSON in payload: {msg!r}"
        # Nullability + server_default match the model -- no other diffs.
        assert "nullable" not in msg, f"unexpected nullability drift on matching column: {msg!r}"
        assert "server_default" not in msg, f"unexpected server_default drift on matching column: {msg!r}"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# _type_equivalent unit tests: pin the JSON/JSONB equivalence so Postgres
# dialect synonyms stay quiet, and pin the TEXT/JSON divergence so the
# reviewer's wrong-type scenario keeps firing.
# ---------------------------------------------------------------------------


def test_type_equivalent_matches_known_dialect_synonyms() -> None:
    from deerflow.persistence.migrations._helpers import _type_equivalent

    # JSON ↔ JSONB (Postgres dialect difference, operationally interchangeable
    # for our schema). Both directions, and via raw strings.
    assert _type_equivalent(sa.JSON(), "JSONB()") is True
    assert _type_equivalent("JSON", "JSONB") is True
    assert _type_equivalent("JSONB", "JSON") is True


def test_type_equivalent_catches_wholesale_type_mismatch() -> None:
    from deerflow.persistence.migrations._helpers import _type_equivalent

    # The reviewer scenario: TEXT NOT NULL DEFAULT '{}' workaround.
    assert _type_equivalent("TEXT", "JSON") is False
    assert _type_equivalent("TEXT", "JSONB") is False
    # Unrelated families also don't accidentally pair up.
    assert _type_equivalent("INTEGER", "JSON") is False


def test_type_equivalent_ignores_type_parameters() -> None:
    """Length / precision differences are out of scope for this helper --
    the goal is wholesale-type drift, not dialect-rendered size defaults."""
    from deerflow.persistence.migrations._helpers import _type_equivalent

    assert _type_equivalent("VARCHAR(255)", "VARCHAR(500)") is True
    assert _type_equivalent("NUMERIC(10,2)", "NUMERIC(20,4)") is True


def test_type_equivalent_returns_true_on_missing_info() -> None:
    """Missing reflected info must not false-positive into a noisy warning."""
    from deerflow.persistence.migrations._helpers import _type_equivalent

    assert _type_equivalent(None, sa.JSON()) is True
    assert _type_equivalent(sa.JSON(), None) is True
    assert _type_equivalent("", "JSON") is True


# ---------------------------------------------------------------------------
# Branch 4: versioned DB
# ---------------------------------------------------------------------------


@asyncio_test
async def test_versioned_branch_is_noop_at_head(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        # First bootstrap takes us through the empty branch.
        await bootstrap_schema(engine, backend="sqlite")
        cols_before = await _runs_columns(engine)
        # Second call hits the versioned branch.
        await bootstrap_schema(engine, backend="sqlite")
        cols_after = await _runs_columns(engine)
        assert cols_after == cols_before
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Schema-parity guard: legacy-upgraded DB must end up structurally identical
# to a fresh DB on the columns the migration touches. This is the property
# that catches drift between ``Base.metadata`` and ``0002``'s DDL -- exactly
# the failure mode of the original #3682 bug, just at a different layer.
# ---------------------------------------------------------------------------


@asyncio_test
async def test_token_usage_column_parity_between_fresh_and_upgraded(tmp_path: Path) -> None:
    fresh = create_async_engine(_url(tmp_path, "fresh.db"))
    upgraded = create_async_engine(_url(tmp_path, "upgraded.db"))
    try:
        # Fresh DB -> empty branch -> create_all
        await bootstrap_schema(fresh, backend="sqlite")
        fresh_col = await _runs_column_meta(fresh, "token_usage_by_model")

        # Legacy DB -> stamp baseline + 0002 upgrade
        await _seed_legacy_without_column(upgraded)
        await bootstrap_schema(upgraded, backend="sqlite")
        upgraded_col = await _runs_column_meta(upgraded, "token_usage_by_model")

        # Pin the contract: the column must have the same nullability AND
        # server_default after either bootstrap path. If 0002 ever drifts
        # from the model's ``Mapped[dict] = mapped_column(JSON, default=dict,
        # server_default=text("'{}'"))`` (i.e. ``nullable=False`` plus the
        # ``'{}'`` DB-side default), this fires.
        assert fresh_col["nullable"] == upgraded_col["nullable"], f"nullability drift: fresh={fresh_col['nullable']} upgraded={upgraded_col['nullable']}"
        # The model declares Mapped[dict] (non-optional) -> NOT NULL.
        assert fresh_col["nullable"] is False
        assert upgraded_col["nullable"] is False
        # Normalize through the same helper the drift warning uses so dialect
        # quirks (outer parens, ``::cast``) do not cause false negatives.
        assert _normalize_default(fresh_col.get("default")) == _normalize_default(upgraded_col.get("default")), f"server_default drift: fresh={fresh_col.get('default')!r} upgraded={upgraded_col.get('default')!r}"
    finally:
        await fresh.dispose()
        await upgraded.dispose()


# ---------------------------------------------------------------------------
# Full schema parity: ``Base.metadata.create_all`` and ``alembic upgrade
# base->head`` MUST produce structurally identical schemas. Both are
# independent sources of the same schema in this codebase -- fresh DBs are
# provisioned by the former (empty branch), historical/upgraded DBs by the
# latter (versioned branch and the alembic tail of the legacy branch). If
# they diverge, two users running the same app version end up with different
# DB structures: exactly the cross-deployment drift this PR exists to kill.
#
# The check is intentionally scoped to columns × (nullable, server_default)
# instead of full type/index/FK reflection. Those are the two highest-signal
# attributes for the drift modes seen so far (#3682 was a nullability
# mismatch; review todo #6 was a server_default mismatch). Type, index, and
# FK reflection differ enough across dialects to require careful
# normalization helpers that aren't worth introducing for this PR's scope;
# see review todo #7 for the wider plan.
# ---------------------------------------------------------------------------


def _reflect_columns_sync(sync_conn) -> dict[str, dict[str, dict]]:
    insp = sa.inspect(sync_conn)
    out: dict[str, dict[str, dict]] = {}
    for table in insp.get_table_names():
        # ``alembic_version`` is alembic's own bookkeeping table, not part of
        # our schema -- one path creates it (upgrade) and the other doesn't
        # (create_all), so comparing it would produce a guaranteed false
        # positive every run.
        if table == "alembic_version":
            continue
        out[table] = {c["name"]: c for c in insp.get_columns(table)}
    return out


async def _reflect_columns(engine) -> dict[str, dict[str, dict]]:
    async with engine.connect() as conn:
        return await conn.run_sync(_reflect_columns_sync)


@asyncio_test
async def test_create_all_and_alembic_upgrade_produce_same_schema(tmp_path: Path) -> None:
    fresh = create_async_engine(_url(tmp_path, "fresh.db"))
    upgraded = create_async_engine(_url(tmp_path, "upgraded.db"))
    try:
        # Path A: ``Base.metadata.create_all`` -- the empty-branch code path.
        async with fresh.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Path B: pure alembic ``upgrade base->head``. Note we deliberately
        # bypass ``bootstrap_schema`` on this side -- its empty branch uses
        # ``create_all``, not the alembic chain -- to exercise the path a
        # versioned-DB upgrade actually takes.
        cfg = _get_alembic_config(upgraded)
        await asyncio.to_thread(_upgrade, cfg, "head")

        fresh_tables = await _reflect_columns(fresh)
        upgraded_tables = await _reflect_columns(upgraded)

        # Same set of tables. A mismatch here means either ``Base.metadata``
        # has gained/lost a table without a matching revision, or a revision
        # creates/drops a table without a matching model change.
        assert set(fresh_tables) == set(upgraded_tables), f"table-set drift between create_all and alembic upgrade: only-in-create_all={set(fresh_tables) - set(upgraded_tables)} only-in-alembic={set(upgraded_tables) - set(fresh_tables)}"

        for table in sorted(fresh_tables):
            fresh_cols = fresh_tables[table]
            upgraded_cols = upgraded_tables[table]
            assert set(fresh_cols) == set(upgraded_cols), f"{table}: column-set drift only-in-create_all={set(fresh_cols) - set(upgraded_cols)} only-in-alembic={set(upgraded_cols) - set(fresh_cols)}"
            for col_name in sorted(fresh_cols):
                f_col = fresh_cols[col_name]
                u_col = upgraded_cols[col_name]
                assert f_col["nullable"] == u_col["nullable"], f"{table}.{col_name}: nullable drift create_all={f_col['nullable']} alembic={u_col['nullable']}"
                # Normalize through ``_normalize_default`` to absorb the
                # dialect-rendering quirks (outer parens, ``::cast``) that
                # would otherwise cause false positives.
                f_default = _normalize_default(f_col.get("default"))
                u_default = _normalize_default(u_col.get("default"))
                assert f_default == u_default, f"{table}.{col_name}: server_default drift create_all={f_col.get('default')!r} alembic={u_col.get('default')!r}"
    finally:
        await fresh.dispose()
        await upgraded.dispose()


# ---------------------------------------------------------------------------
# Baseline-table-restriction guards. The legacy branch's backfill must
# create *only* the baseline-era tables, not the full ``Base.metadata``.
# Otherwise it would pre-empt a future ``op.create_table`` revision for a
# newly-added model (the revision would crash with ``relation already
# exists``). Two tests cover this:
#
# 1. ``_BASELINE_TABLE_NAMES`` is pinned against what ``0001_baseline``
#    actually creates -- editing 0001 without updating the constant fires
#    here, forcing the developer to keep the two in sync.
# 2. Regression for the leak itself: a phantom table outside the constant
#    must NOT be created by the backfill helper.
# ---------------------------------------------------------------------------


@asyncio_test
async def test_baseline_table_names_constant_matches_0001(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        # Run only up to baseline (not head) and reflect what it produced.
        await asyncio.to_thread(_upgrade, cfg, BASELINE)

        async with engine.connect() as conn:
            reflected = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
        # ``alembic_version`` is alembic's bookkeeping table, not part of
        # our schema -- the constant is about DeerFlow-owned baseline tables.
        reflected.discard("alembic_version")

        assert reflected == _BASELINE_TABLE_NAMES, f"_BASELINE_TABLE_NAMES drifted from 0001_baseline.upgrade()'s output: only-in-0001={sorted(reflected - _BASELINE_TABLE_NAMES)} only-in-constant={sorted(_BASELINE_TABLE_NAMES - reflected)}"
    finally:
        await engine.dispose()


@asyncio_test
async def test_legacy_backfill_skips_non_baseline_tables(tmp_path: Path) -> None:
    """Regression: legacy backfill must not create tables outside the baseline
    set, because a later ``op.create_table`` revision for the same name would
    fail. We synthesise a phantom table on ``Base.metadata`` (modelling a
    future model addition), run the backfill helper, and assert the phantom
    is absent from the resulting DB.
    """
    phantom_name = "phantom_future_table_for_test"
    phantom = sa.Table(
        phantom_name,
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    try:
        engine = create_async_engine(_url(tmp_path))
        try:
            async with engine.begin() as conn:
                await conn.run_sync(_run_baseline_create_all_sync)

            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))

            assert phantom_name not in tables, f"legacy backfill leaked {phantom_name!r}; a future ``op.create_table({phantom_name!r})`` revision would now collide"
            # Sanity: baseline tables ARE created by the backfill helper.
            assert "runs" in tables
            assert "channel_connections" in tables
        finally:
            await engine.dispose()
    finally:
        Base.metadata.remove(phantom)


# ---------------------------------------------------------------------------
# _decide_state unit tests (pure function, no DB needed)
# ---------------------------------------------------------------------------


class TestDecideState:
    def test_empty(self):
        assert _decide_state({"has_alembic_version": False, "has_deerflow_tables": False}) == "empty"

    def test_empty_with_unrelated_tables(self):
        # LangGraph checkpointer tables present but DeerFlow has nothing yet.
        # ``has_deerflow_tables`` is derived from the metadata intersection in
        # production, so the only thing the decision function needs is the
        # bool itself.
        assert _decide_state({"has_alembic_version": False, "has_deerflow_tables": False}) == "empty"

    def test_legacy(self):
        assert _decide_state({"has_alembic_version": False, "has_deerflow_tables": True}) == "legacy"

    def test_versioned(self):
        assert _decide_state({"has_alembic_version": True, "has_deerflow_tables": True}) == "versioned"

    def test_versioned_takes_precedence_over_empty(self):
        # Pathological: alembic_version row exists but no managed tables yet
        # (e.g. someone restored only the alembic_version table from backup).
        # We still go versioned -> upgrade head, which is the right thing:
        # alembic will run every revision from base.
        assert _decide_state({"has_alembic_version": True, "has_deerflow_tables": False}) == "versioned"


# ---------------------------------------------------------------------------
# Sanity: head revision is the one this module expects
# ---------------------------------------------------------------------------


def test_head_revision_is_token_usage_revision() -> None:
    assert _get_head_revision() == HEAD


def test_baseline_revision_id_is_known() -> None:
    """Detect a baseline rename: the bootstrap code hardcodes ``0001_baseline``
    as the stamp target for the legacy branch, so a rename would silently
    break that branch unless caught here."""
    from pathlib import Path  # noqa: PLC0415

    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    migrations_dir = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/persistence/migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    script = ScriptDirectory.from_config(cfg)
    all_ids = {rev.revision for rev in script.walk_revisions()}
    assert BASELINE in all_ids, f"baseline revision id {BASELINE!r} not found in {all_ids}"
