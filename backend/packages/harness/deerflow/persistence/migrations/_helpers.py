"""Idempotent helpers for alembic column revisions.

Column revisions in ``versions/`` should use these helpers instead of raw
``op.add_column`` / ``op.drop_column`` so re-running a column change against a
DB that already has (or has already removed) the column is a safe no-op.

Two reasons we need idempotency:

1. **Defence-in-depth on top of bootstrap locking.** ``bootstrap_schema()``
   serialises Postgres with an advisory lock and SQLite within one process
   with an ``asyncio.Lock``. If a retry happens anyway (manual ALTER,
   misconfiguration, SQLite cross-process contention), the revision must still
   be safe to re-run.

2. **Same posture that made ``Base.metadata.create_all`` forgiving.**
   ``create_all`` skips existing tables. Column migrations should mirror that
   forgiving behavior by skipping columns already in the desired state.

Drift warning
-------------

Name-match alone can hide a column that a manual ``ALTER`` (for example the
#3682 workaround that ran ``ALTER TABLE runs ADD COLUMN token_usage_by_model
JSON`` without ``NOT NULL DEFAULT '{}'``, or the wrong-type variant
``ALTER TABLE runs ADD COLUMN token_usage_by_model TEXT NOT NULL DEFAULT
'{}'``) left in a shape that diverges from what ``Base.metadata.create_all``
would produce on a fresh DB. To surface that silent drift, ``safe_add_column``
compares the existing column's ``nullable`` / ``server_default`` / ``type``
against the desired ``sa.Column`` and emits ``logger.warning`` on mismatch.
Both sides are rendered through the migration connection's dialect before
they are compared: the model says ``sa.String`` / ``sa.BigInteger`` /
``server_default="0"`` while reflection reports ``VARCHAR`` / ``BIGINT`` /
``'0'``, so comparing the raw Python objects would warn on every column a
revision finds already present. Type comparison goes through
``_type_equivalent``, which treats known dialect-synonym pairs (e.g. ``JSON``
vs ``JSONB``) as equivalent to avoid false positives while still catching
wholesale type mismatches like ``TEXT`` vs ``JSON``. We do not auto-repair --
a warning is enough for operators to notice and decide.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _normalize_default(value: object, dialect: sa.engine.Dialect | None = None) -> str | None:
    """Normalize a server-default value for cross-source comparison.

    The desired value comes from ``sa.Column.server_default`` (a
    ``DefaultClause`` wrapping a string, ``TextClause`` or SQL expression such
    as ``sa.false()``; ``None``; or a Python literal); the reflected value
    comes from ``Inspector.get_columns()['default']`` as a dialect-rendered
    string. Expressions are compiled with *dialect* (``sa.false()`` is ``0``
    on SQLite and ``false`` on Postgres), then outer parens / whitespace /
    Postgres-style type casts / one layer of single quotes are stripped so
    ``server_default="0"`` (DDL ``DEFAULT '0'``), SQLite's reflected ``'0'``
    and Postgres's reflected ``0`` or ``'0'::bigint`` all compare equal.
    Returns ``None`` only when there is no default: a quoted empty literal
    (``server_default=""``, reflected ``''``) stays ``""``.
    """
    if value is None:
        return None
    if isinstance(value, sa.schema.DefaultClause):
        value = value.arg
        if isinstance(value, str):
            # DDL renders a plain-string default as a quoted literal.
            value = "'" + value.replace("'", "''") + "'"
    if isinstance(value, sa.sql.elements.TextClause):
        text = value.text
    elif isinstance(value, sa.sql.elements.ClauseElement):
        text = str(value.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    else:
        text = str(value)
    text = text.strip()
    # Strip a single layer of outer parens that some dialects wrap defaults in.
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    # Strip Postgres-style type casts like ``'{}'::jsonb``.
    if "::" in text:
        text = text.split("::", 1)[0].strip()
    # Strip one layer of SQL string quoting: a plain-string ``server_default``
    # renders as a quoted literal, and dialects disagree on whether a numeric
    # column reflects it back quoted. The unquoted value is returned even
    # when empty: ``DEFAULT ''`` is a default, unlike no default at all.
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text or None


def _strip_type_parameters(rendered: str) -> str:
    """Drop every parenthesized group, keeping words around it.

    ``TIMESTAMP(3) WITH TIME ZONE`` keeps its ``WITH TIME ZONE`` suffix, and
    nested reprs such as ``JSONB(astext_type=Text())`` lose the whole group.
    """
    out: list[str] = []
    depth = 0
    for char in rendered:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(char)
    return " ".join("".join(out).split())


def _normalize_type(value: object, dialect: sa.engine.Dialect | None = None) -> str:
    """Normalize a SQLAlchemy ``TypeEngine`` (or reflected type) for comparison.

    A ``TypeEngine`` is rendered as the DDL *dialect* would emit for it, so
    the model's generic ``String(128)`` / ``BigInteger()`` /
    ``DateTime(timezone=True)`` and the reflected ``VARCHAR(128)`` /
    ``BIGINT`` / Postgres ``TIMESTAMP(timezone=True)`` land on the same name.
    Strings are taken as already-rendered type names. Returns the upper-cased
    name with any parameters stripped (e.g. ``VARCHAR(255)`` → ``"VARCHAR"``,
    Postgres ``TIMESTAMP WITH TIME ZONE`` stays whole). Length parameters are
    dropped on purpose: drift warnings target wholesale type
    misconfigurations (the JSON-vs-TEXT review case), not dialect-rendered
    size defaults. An empty string signals "missing info" (no type, or one
    the dialect cannot render, such as SQLite's ``NullType`` for an
    unrecognized declared type) -- callers should not equality-check empty
    strings.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        rendered = value
    elif isinstance(value, sa.types.TypeEngine):
        try:
            rendered = str(value.compile(dialect=dialect))
        except sa.exc.CompileError:
            return ""
    else:
        rendered = repr(value)
    return _strip_type_parameters(rendered.upper())


# Known dialect-synonym pairs that must NOT fire a type-drift warning.
# Postgres reflects ``JSON`` as ``JSONB`` (and vice versa depending on how
# the column was provisioned); the model's ``sa.JSON`` plus this allowlist
# keeps a Postgres deployment quiet while still catching genuine type errors
# like ``TEXT NOT NULL DEFAULT '{}'`` re-adds.
#
# Add a new pair here ONLY when a real reflection-vs-model mismatch is
# proven to be a false positive in a deployment -- not pre-emptively, since
# overly broad equivalence would re-open the silent-drift hole this helper
# exists to close.
_EQUIVALENT_TYPE_FAMILIES: tuple[frozenset[str], ...] = (frozenset({"JSON", "JSONB"}),)


def _type_equivalent(actual: object, desired: object, dialect: sa.engine.Dialect | None = None) -> bool:
    """True if *actual* and *desired* are the same type or a known equivalent.

    Both sides are rendered with *dialect* (see ``_normalize_type``). Returns
    True when either side is missing reflected info so missing-data cases
    never false-positive into a noisy warning.
    """
    a = _normalize_type(actual, dialect)
    d = _normalize_type(desired, dialect)
    if not a or not d:
        return True
    if a == d:
        return True
    pair = frozenset({a, d})
    return any(pair <= fam for fam in _EQUIVALENT_TYPE_FAMILIES)


def _check_column_drift(table: str, desired: sa.Column, actual: dict, dialect: sa.engine.Dialect | None = None) -> None:
    """Warn if an existing column's attributes diverge from the desired model.

    Equality is checked on ``nullable`` and ``server_default`` directly, and
    on ``type`` via ``_type_equivalent`` (which treats known dialect-synonym
    pairs like ``JSON`` vs ``JSONB`` as equivalent). The reflected and
    desired type reprs are also echoed in the warning payload regardless of
    whether type was the failing dimension, so an operator triaging the log
    line sees the type context at a glance. *dialect* is the migration
    connection's, so both sides are rendered the way that database spells
    them.
    """
    diffs: list[str] = []

    desired_nullable = True if desired.nullable is None else bool(desired.nullable)
    actual_nullable = bool(actual.get("nullable", True))
    if desired_nullable != actual_nullable:
        diffs.append(f"nullable actual={actual_nullable} desired={desired_nullable}")

    desired_default = _normalize_default(desired.server_default, dialect)
    actual_default = _normalize_default(actual.get("default"), dialect)
    if desired_default != actual_default:
        diffs.append(f"server_default actual={actual_default!r} desired={desired_default!r}")

    if not _type_equivalent(actual.get("type"), desired.type, dialect):
        diffs.append(f"type actual={_normalize_type(actual.get('type'), dialect)!r} desired={_normalize_type(desired.type, dialect)!r}")

    if diffs:
        logger.warning(
            "safe_add_column: %s.%s already exists but drifts from the model definition (%s); actual_type=%r desired_type=%r; leaving as-is -- a manual ALTER may be needed to match the model.",
            table,
            desired.name,
            "; ".join(diffs),
            actual.get("type"),
            desired.type,
        )


def safe_add_column(table: str, column: sa.Column) -> None:
    """``op.add_column`` that no-ops when the table or column is missing/present.

    - Missing table => nothing to add to. Skip silently because bootstrap only
      supports legacy DBs that already have the baseline table set.
    - Column already exists => no-op. Before returning, ``_check_column_drift``
      compares the existing column's nullability / server_default / type
      against the desired ``column`` and ``logger.warning``\\ s on mismatch so
      manually-applied workarounds do not silently survive as latent drift.
    """
    insp = _inspector()
    if table not in insp.get_table_names():
        return
    existing = {c["name"]: c for c in insp.get_columns(table)}
    if column.name in existing:
        _check_column_drift(table, column, existing[column.name], insp.dialect)
        return
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)


def safe_drop_column(table: str, column_name: str) -> None:
    """``op.drop_column`` that no-ops when the table or column is already gone."""
    insp = _inspector()
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    if column_name not in existing:
        return
    with op.batch_alter_table(table) as batch:
        batch.drop_column(column_name)
