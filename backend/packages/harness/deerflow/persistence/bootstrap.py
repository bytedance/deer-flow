"""Hybrid schema bootstrap for DeerFlow's application tables.

Replaces the unconditional ``Base.metadata.create_all`` at Gateway startup.
Combines two ideas:

1. ``create_all`` stays the empty-DB fast path -- it renders ``Base.metadata``
   faithfully across SQLite and Postgres dialects (JSON vs JSONB, server
   defaults, index/FK names, type affinity) without anyone having to hand-keep
   a mirror baseline in sync with the models.
2. **Alembic owns every change from baseline onward.** Any new ORM column /
   table / index must ship as a revision under ``migrations/versions/``.

Three-branch decision (see ``_decide_state``)
---------------------------------------------

| DB state                              | Action                                  |
|---------------------------------------|-----------------------------------------|
| empty (no DeerFlow tables)            | ``create_all`` + ``alembic stamp head`` |
| legacy (DeerFlow tables, no alembic)  | ``create_all`` (baseline tables only, as backfill) + ``stamp 0001_baseline`` + ``upgrade head`` |
| versioned (``alembic_version`` row)   | ``alembic upgrade head``                |

The legacy branch handles pre-alembic databases that already have at least one
DeerFlow-owned table. ``create_all`` runs first because stamping at
``0001_baseline`` makes alembic skip the baseline's own ``create_table`` DDL on
the subsequent upgrade -- so any baseline table introduced into
``Base.metadata`` after the user's DB was first provisioned (e.g. the
``channel_*`` tables from PR #1930 for users upgrading across multiple
releases) would otherwise never be created, and the first request hitting that
table would 500 with ``no such table``. The backfill is **restricted to
``_BASELINE_TABLE_NAMES``** so it does not also create tables that future
revisions introduce -- those revisions' own ``op.create_table`` would then
fail with ``relation already exists``. A guard test pins the restriction
set against ``0001_baseline.upgrade()``'s actual output.

Column-level shape (the pre-#3658 vs post-#3658 vs manual-ALTER cases for
``token_usage_by_model``) is answered by each ``versions/*.py`` revision via
the idempotent helpers in ``migrations/_helpers.py`` (``safe_add_column``
no-ops when the column is already present and ``logger.warning``s on
shape drift). Future schema additions therefore plug in by writing a new
revision file -- **no edit to this module is required** *unless* the new
revision creates a new baseline table, in which case ``_BASELINE_TABLE_NAMES``
must be updated to match (the guard test fires otherwise).

Concurrency safety
------------------

Layered, with different guarantees per backend. Postgres has true
cross-process serialisation. SQLite is single-process safe and cross-process
best-effort; multi-instance deployments should use Postgres.

* **Postgres -- true cross-process serialisation.** ``pg_advisory_lock`` runs
  the whole reflect-and-act sequence under an exclusive lock that survives
  cross-process. Concurrent Gateway instances queue cleanly and the second
  one observes head as a no-op.

* **SQLite -- single-process serialisation, best-effort cross-process.**
  SQLite is single-node by deployment, so the realistic concurrency case is
  multiple async tasks inside one Gateway process (tests, lifespan re-entry).
  A per-engine ``asyncio.Lock`` serialises those. For the rare cross-process
  case (e.g. two ``make dev`` workers on the same DB file), we rely on
  SQLite's own file-level write lock plus a 30s ``PRAGMA busy_timeout`` --
  the latter is set on **both** the production engine
  (``persistence/engine.py``) and the alembic-spawned engine
  (``migrations/env.py``) so any writer waits up to 30s for the file lock
  instead of failing fast. This is best-effort, not a true mutex: under
  pathological overlap a process can still see ``database is locked`` after
  30s. The fallback line of defence -- idempotent revisions -- guarantees
  correctness anyway.

* **Idempotent revisions -- retry fallback.** Column revisions use the helpers
  in ``migrations/_helpers.py`` so repeated post-baseline changes, manual
  ALTERs, or retries after SQLite lock contention do not duplicate work.

``alembic upgrade head`` on a DB already at head is a no-op by alembic's own
semantics, so the second-N-th actor simply observes head and exits.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


# Where the alembic environment lives, relative to this file.
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Cached migration head, computed once per process from the disk script tree.
_HEAD_REVISION: str | None = None

# Baseline (stamp target for legacy DBs). Pinned here so the bootstrap layer
# fails loudly if the baseline revision is ever renamed without updating the
# stamp call. ``tests/test_persistence_bootstrap.py`` asserts this string is a
# real revision id in the script tree.
_BASELINE_REVISION = "0001_baseline"

# Stable advisory-lock key for Postgres. Two random 32-bit halves picked once
# so we never collide with any other application's advisory locks. Do not
# change without coordinating a one-time migration (a key change effectively
# releases the prior lock).
_PG_LOCK_KEY = 0x0DEE_12F1_0BEE_3682


# Tables created by ``0001_baseline.upgrade()``. The legacy branch restricts
# its ``create_all`` backfill to this set so it does NOT pre-empt later
# ``op.create_table`` revisions for models added after baseline -- those
# revisions would otherwise fail with ``relation already exists`` if
# ``create_all`` had created their table first. (Column revisions are
# already safe via the idempotent helpers in ``migrations/_helpers.py``;
# there is no analogous ``safe_create_table`` yet, so we keep table-level
# safety at this layer instead of pushing it onto every future revision.)
#
# ``test_baseline_table_names_constant_matches_0001`` pins this set against
# what 0001 actually creates -- editing 0001 without updating this constant
# (or vice versa) fires that test.
_BASELINE_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "channel_connections",
        "channel_conversations",
        "channel_credentials",
        "channel_oauth_states",
        "feedback",
        "run_events",
        "runs",
        "threads_meta",
        "users",
    }
)


# Per-engine SQLite bootstrap locks. Per-engine (not module-global) so each
# engine instance pairs with a lock bound to the event loop that uses that
# engine -- necessary because ``asyncio.Lock`` binds to the first loop it sees,
# and pytest gives each async test its own loop. Production uses one engine
# per process so this dict collapses to a single entry in practice.
#
# Keyed by the engine object itself via ``WeakKeyDictionary`` rather than
# ``id(engine)``: CPython recycles addresses after GC, so a stale ``id`` →
# ``Lock`` entry from a dead engine could be returned to a new engine that
# happened to land on the same address. The returned lock would still be bound
# to the dead engine's event loop and ``async with`` would raise
# ``RuntimeError: ... bound to a different event loop``. Hashing the engine
# itself also drops entries automatically when the engine is collected, so this
# dict never grows past the live engine count.
_SQLITE_LOCKS: weakref.WeakKeyDictionary[AsyncEngine, asyncio.Lock] = weakref.WeakKeyDictionary()


def _get_sqlite_local_lock(engine: AsyncEngine) -> asyncio.Lock:
    lock = _SQLITE_LOCKS.get(engine)
    if lock is None:
        lock = asyncio.Lock()
        _SQLITE_LOCKS[engine] = lock
    return lock


def _escape_url_for_alembic(url: str) -> str:
    """Double literal ``%`` so ``ConfigParser`` interpolation leaves the URL intact.

    ``alembic.config.Config.set_main_option`` forwards to ``ConfigParser.set``,
    which performs ``%(name)s``-style interpolation on the value. A URL-encoded
    password like ``p%40ss`` (``@`` escaped to ``%40``) would otherwise raise
    ``InterpolationSyntaxError``. Doubling every literal ``%`` makes
    ConfigParser unescape it back to one. Shared with
    ``scripts/_autogen_revision.py`` so the round-trip rule lives in one place.
    """
    return url.replace("%", "%%")


def _alembic_safe_url(engine: AsyncEngine) -> str:
    """Render *engine*'s URL in a form alembic ``set_main_option`` accepts.

    Two pitfalls handled:

    1. ``str(engine.url)`` (and ``URL.render_as_string()`` without args) masks
       the password as ``***`` -- so alembic's stamp/upgrade would open its own
       connection with garbage credentials and fail at runtime, even though
       the live engine connects fine. Fix: ``render_as_string(hide_password=False)``.
    2. ConfigParser interpolation on ``%`` -- delegated to
       ``_escape_url_for_alembic`` so the rule is shared with the autogen
       script.
    """
    rendered = engine.url.render_as_string(hide_password=False)
    return _escape_url_for_alembic(rendered)


def _get_alembic_config(engine: AsyncEngine) -> AlembicConfig:
    """Build an in-process alembic config pointing at our migrations dir.

    Avoids reading ``alembic.ini`` from disk so the production runtime doesn't
    depend on a working-directory-relative file lookup. The ``script_location``
    is anchored at the package path on disk.
    """
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _alembic_safe_url(engine))
    return cfg


def _get_head_revision() -> str:
    """Return the head revision id from ``versions/``, cached per process."""
    global _HEAD_REVISION
    if _HEAD_REVISION is None:
        cfg = AlembicConfig()
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        if head is None:
            raise RuntimeError("alembic has no head revision -- versions/ directory is empty")
        _HEAD_REVISION = head
    return _HEAD_REVISION


def _reflect_state(sync_conn: Any) -> dict[str, bool]:
    """Inspect *sync_conn* (sync connection inside ``run_sync``) and return:

    - ``has_alembic_version``: bool
    - ``has_deerflow_tables``: True iff at least one table that ``Base.metadata``
      knows about is present in the DB. Computed as ``reflected ∩ metadata`` so
      the bootstrap layer never hardcodes a specific table or column name --
      adding a new ORM model only changes ``Base.metadata``, not this module.
    """
    from deerflow.persistence.base import Base

    # Make sure every ORM model is imported, otherwise ``Base.metadata.tables``
    # may miss tables registered by submodules that haven't been imported yet.
    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; metadata may be incomplete")

    insp = sa_inspect(sync_conn)
    reflected = set(insp.get_table_names())
    metadata_tables = set(Base.metadata.tables)
    return {
        "has_alembic_version": "alembic_version" in reflected,
        "has_deerflow_tables": bool(reflected & metadata_tables),
    }


def _decide_state(state: dict[str, bool]) -> str:
    """Map a reflected DB state to one of three branch labels.

    The legacy branch covers every pre-alembic DB uniformly -- whether the
    columns added by later revisions are present or not is a question each
    revision answers for itself via the idempotent helpers in
    ``migrations/_helpers.py``.
    """
    if state["has_alembic_version"]:
        return "versioned"
    if not state["has_deerflow_tables"]:
        # Either a brand-new DB or a DB containing only tables we don't own
        # (e.g. LangGraph's checkpointer tables on a fresh deployment). The
        # empty branch provisions the tables alembic owns, then stamps head.
        return "empty"
    return "legacy"


def _run_create_all_sync(sync_conn: Any) -> None:
    """Create all DeerFlow-owned tables on *sync_conn*."""
    # Import here to ensure all model classes are registered with Base.metadata.
    from deerflow.persistence.base import Base

    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; bootstrap will create empty schema")

    Base.metadata.create_all(sync_conn)


def _run_baseline_create_all_sync(sync_conn: Any) -> None:
    """Create only the baseline tables on *sync_conn* (idempotent via checkfirst).

    Used by the legacy branch to backfill baseline-era tables missing from
    the user's DB. Restricting the table list to ``_BASELINE_TABLE_NAMES``
    is the safety property: an unrestricted ``create_all`` would also create
    tables introduced by later revisions, which would then collide with
    those revisions' ``op.create_table`` calls when alembic ran upgrade.
    """
    from deerflow.persistence.base import Base

    try:
        import deerflow.persistence.models  # noqa: F401
    except ImportError:
        logger.debug("deerflow.persistence.models not found; baseline backfill may be incomplete")

    baseline_tables = [Base.metadata.tables[name] for name in _BASELINE_TABLE_NAMES if name in Base.metadata.tables]
    Base.metadata.create_all(sync_conn, tables=baseline_tables, checkfirst=True)


def _stamp(cfg: AlembicConfig, revision: str) -> None:
    """Synchronous alembic stamp; callers must wrap in ``asyncio.to_thread``."""
    alembic_command.stamp(cfg, revision)


def _upgrade(cfg: AlembicConfig, revision: str) -> None:
    """Synchronous alembic upgrade; callers must wrap in ``asyncio.to_thread``."""
    alembic_command.upgrade(cfg, revision)


# ---------------------------------------------------------------------------
# Cross-process locking
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _postgres_lock(engine: AsyncEngine):
    """Hold a Postgres session-level advisory lock for the body of the block.

    Session-level (not transaction-level) so the lock outlives implicit
    transactions opened by alembic during ``stamp`` / ``upgrade``. The lock
    is released explicitly on the way out and -- as a safety net -- when the
    backing session disconnects (process crash, kill -9).

    Idle-in-transaction protection
    ------------------------------

    ``engine.connect()`` auto-begins a transaction on the first ``execute``,
    and this connection then sits idle while ``asyncio.to_thread(_upgrade,
    ...)`` runs alembic on a *different* pooled connection. Managed Postgres
    (RDS, Cloud SQL, Supabase) ships with ``idle_in_transaction_session_
    timeout`` set to 1-10 minutes by default; if alembic takes longer than
    that, the host kills this idle-in-transaction session, and because
    advisory locks are session-scoped, the lock is **silently released**.
    A second Gateway then acquires it and runs DDL concurrently with the
    first -- defeating the whole purpose of the lock.

    Defence: ``SET LOCAL idle_in_transaction_session_timeout = 0`` disables
    the kill **for this transaction only** (no global / role-level effect).
    Self-hosted Postgres usually ships with the timeout off, so this is a
    no-op there; on managed PG it is what keeps the lock alive while DDL
    runs. Must execute *before* ``pg_advisory_lock`` so a slow lock acquire
    on a heavily-contended cluster is itself protected.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _PG_LOCK_KEY})
        try:
            logger.info("bootstrap: acquired postgres advisory lock key=0x%x", _PG_LOCK_KEY)
            yield
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PG_LOCK_KEY})
            except Exception:  # noqa: BLE001
                logger.warning("bootstrap: pg_advisory_unlock raised; session close will release", exc_info=True)


@asynccontextmanager
async def _sqlite_lock(engine: AsyncEngine):
    """Serialise SQLite bootstrap inside one process; cross-process is
    best-effort via SQLite's own file lock + ``PRAGMA busy_timeout``.

    Why not ``BEGIN IMMEDIATE`` on a sentinel connection? SQLite is
    single-writer per file. If we held a write lock on one connection,
    alembic's own connection (opened inside ``stamp`` / ``upgrade``) would
    deadlock against us.

    Why not a cross-process OS file lock? It would work, but it adds a hard
    dependency on platform-specific ``fcntl`` / ``msvcrt`` calls for a
    deployment shape (multi-process SQLite) that's already discouraged for
    DeerFlow. The 30s ``busy_timeout`` plus idempotent revisions cover the
    realistic case; truly multi-instance deployments should use Postgres.

    Note: the 30s ``busy_timeout`` is set by the engine event hooks in
    ``persistence/engine.py`` (production) and ``migrations/env.py``
    (alembic-spawned). This function relies on those PRAGMAs being in place
    rather than setting one on a probe connection that wouldn't propagate.
    """
    async with _get_sqlite_local_lock(engine):
        logger.info("bootstrap: acquired sqlite in-process lock")
        yield


def _bootstrap_lock(engine: AsyncEngine, *, backend: str):
    if backend == "postgres":
        return _postgres_lock(engine)
    if backend == "sqlite":
        return _sqlite_lock(engine)
    raise ValueError(f"bootstrap: unsupported backend {backend!r}")


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def bootstrap_schema(engine: AsyncEngine, *, backend: str) -> None:
    """Bring the DB schema to head.

    Postgres calls are serialised across processes with an advisory lock.
    SQLite calls are serialised inside one process and are best-effort across
    processes via SQLite's file lock and ``busy_timeout``.

    Branch dispatch is documented at module top. ``alembic.command.stamp`` and
    ``alembic.command.upgrade`` are synchronous and would block the event
    loop; both are wrapped in ``asyncio.to_thread``.
    """
    head = _get_head_revision()
    cfg = _get_alembic_config(engine)

    async with _bootstrap_lock(engine, backend=backend):
        async with engine.connect() as conn:
            state = await conn.run_sync(_reflect_state)
        decision = _decide_state(state)

        if decision == "empty":
            logger.info("bootstrap: branch=empty -> create_all + stamp head (%s)", head)
            async with engine.begin() as conn:
                await conn.run_sync(_run_create_all_sync)
            await asyncio.to_thread(_stamp, cfg, head)

        elif decision == "legacy":
            logger.info(
                "bootstrap: branch=legacy -> create_all (backfill missing baseline tables) + stamp %s + upgrade head (%s)",
                _BASELINE_REVISION,
                head,
            )
            # ``_run_baseline_create_all_sync`` is restricted to
            # ``_BASELINE_TABLE_NAMES`` -- a plain ``Base.metadata.create_all``
            # would also create tables introduced by later revisions and
            # collide with their ``op.create_table`` on the subsequent
            # upgrade. With the restriction, missing baseline tables are
            # backfilled and post-baseline ``create_table`` revisions run
            # against a DB where their tables genuinely do not yet exist.
            # The post-create_all column-add revisions still no-op via
            # ``safe_add_column`` because baseline-era tables now have the
            # columns those revisions would add.
            async with engine.begin() as conn:
                await conn.run_sync(_run_baseline_create_all_sync)
            await asyncio.to_thread(_stamp, cfg, _BASELINE_REVISION)
            await asyncio.to_thread(_upgrade, cfg, "head")

        elif decision == "versioned":
            logger.info("bootstrap: branch=versioned -> upgrade head (%s)", head)
            await asyncio.to_thread(_upgrade, cfg, "head")

        else:  # pragma: no cover -- defensive
            raise RuntimeError(f"bootstrap: unhandled decision {decision!r}")

    logger.info("bootstrap: complete (backend=%s)", backend)
