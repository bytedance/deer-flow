"""Explicit private schema upgrades and non-mutating production admission."""

import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

SCHEMA_REVISION = "e0001_execution_ledger"
VERSION_TABLE = "ecs_executor_alembic_version"
# Frozen deployed contract, independent of the evolving runtime metadata.
_SHAPES = {
    "ecs_execution_jobs": {"id": ("string", 64), "namespace": ("string", 64), "request_key": ("string", 128), "version": ("integer", None), "state": ("string", 32), "record": ("json", None)},
    "ecs_execution_nodes": {"id": ("string", 64), "record": ("json", None)},
    "ecs_native_affinities": {"user_id": ("string", 255), "thread_id": ("string", 255), "incarnation": ("string", 255), "node_id": ("string", 64)},
}
_PRIMARY_KEYS = {"ecs_execution_jobs": ["id"], "ecs_execution_nodes": ["id"], "ecs_native_affinities": ["user_id", "thread_id", "incarnation"]}


class SchemaCompatibilityError(RuntimeError):
    pass


def _validate(connection, *, complete):
    from sqlalchemy import JSON, Integer, String

    inspector = inspect(connection)
    if connection.dialect.name == "postgresql" and set(inspector.get_schema_names()) - {"public", "information_schema"}:
        raise SchemaCompatibilityError("Executor requires an independent database without other application schemas")
    tables = set(inspector.get_table_names())
    if tables - (set(_SHAPES) | {VERSION_TABLE}):
        raise SchemaCompatibilityError("Executor requires an independent database containing only its private ledger")
    if complete and not set(_SHAPES) <= tables:
        raise SchemaCompatibilityError("Executor schema is incomplete; run the explicit offline upgrade")
    validation_shapes = {**_SHAPES, VERSION_TABLE: {"version_num": ("string", 32)}}
    for name in set(validation_shapes) & tables:
        if connection.dialect.name == "sqlite":
            # Native generated DDL has no explicit collation. Conservatively
            # refuse any override; reflection alone omits column collations.
            ddl = connection.execute(text("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = :name"), {"name": name}).scalar_one()
            if re.search(r"\bCOLLATE\b", ddl, re.IGNORECASE):
                raise SchemaCompatibilityError("Executor column collation is incompatible")
            for index_name in connection.execute(text("SELECT name FROM pragma_index_list(:name)"), {"name": name}).scalars():
                collations = connection.execute(text("SELECT coll FROM pragma_index_xinfo(:name)"), {"name": index_name}).scalars()
                if any(collation not in (None, "BINARY") for collation in collations):
                    raise SchemaCompatibilityError("Executor index collation is incompatible")
        elif connection.dialect.name == "postgresql":
            # Require each column's native type-default collation; SQLAlchemy
            # column reflection does not expose PostgreSQL collation overrides.
            override = connection.execute(
                text("SELECT 1 FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid WHERE a.attrelid = to_regclass(:name) AND a.attnum > 0 AND NOT a.attisdropped AND a.attcollation <> t.typcollation LIMIT 1"),
                {"name": name},
            ).scalar()
            if override is not None:
                raise SchemaCompatibilityError("Executor column collation is incompatible")
        columns = {column["name"]: column for column in inspector.get_columns(name)}
        if set(columns) != set(validation_shapes[name]):
            raise SchemaCompatibilityError("Executor column shape is incompatible")
        for key, (kind, length) in validation_shapes[name].items():
            column = columns[key]
            expected_type = {"string": String, "integer": Integer, "json": JSON}[kind]
            expected_sql_type = {"string": f"VARCHAR({length})", "integer": "INTEGER", "json": "JSON"}[kind]
            if not isinstance(column["type"], expected_type) or str(column["type"]).upper() != expected_sql_type or column["nullable"]:
                raise SchemaCompatibilityError("Executor column type/nullability is incompatible")
            if any(column.get(field) is not None for field in ("default", "computed", "identity")):
                raise SchemaCompatibilityError("Executor generated/default column semantics are incompatible")
        primary_key = ["version_num"] if name == VERSION_TABLE else _PRIMARY_KEYS[name]
        if inspector.get_pk_constraint(name)["constrained_columns"] != primary_key:
            raise SchemaCompatibilityError("Executor primary key is incompatible")
        if inspector.get_check_constraints(name) or inspector.get_foreign_keys(name):
            raise SchemaCompatibilityError("Executor CHECK/foreign key semantics are incompatible")
        unique = inspector.get_unique_constraints(name)
        expected_unique = [["namespace", "request_key"]] if name == "ecs_execution_jobs" else []
        if [item["column_names"] for item in unique] != expected_unique:
            raise SchemaCompatibilityError("Executor uniqueness semantics are incompatible")
        for item in unique:
            options = item.get("dialect_options") or {}
            # These are reflected PostgreSQL defaults, not new constraints.
            neutral = {"postgresql_include": (None, []), "postgresql_nulls_not_distinct": (None, False)}
            if any(key not in neutral or value not in neutral[key] for key, value in options.items()):
                raise SchemaCompatibilityError("Executor uniqueness semantics are incompatible")
        indexes = []
        for item in inspector.get_indexes(name):
            # PostgreSQL reports the index backing a UNIQUE constraint twice.
            # It is not an independent index and must match that same constraint.
            duplicate = item.get("duplicates_constraint")
            if duplicate is not None:
                if not any(constraint.get("name") == duplicate and constraint["column_names"] == item["column_names"] for constraint in unique):
                    raise SchemaCompatibilityError("Executor backing index is incompatible")
                continue
            indexes.append(item)
        expected_indexes = [["state"]] if name == "ecs_execution_jobs" else []
        if [item["column_names"] for item in indexes] != expected_indexes:
            raise SchemaCompatibilityError("Executor index shape is incompatible")
        for item in indexes:
            options = item.get("dialect_options") or {}
            if item.get("unique") or item.get("column_sorting") or item.get("include_columns") or any(value not in (None, [], "btree") for value in options.values()):
                raise SchemaCompatibilityError("Executor index semantics are incompatible")
    if VERSION_TABLE in tables:
        versions = connection.execute(text("SELECT version_num FROM ecs_executor_alembic_version")).scalars().all()
        if versions != [SCHEMA_REVISION]:
            raise SchemaCompatibilityError("Executor revision is unknown or incompatible")
    elif complete:
        raise SchemaCompatibilityError("Executor schema is unversioned; run the explicit offline upgrade")


def require_schema(engine):
    """Read-only production guard, never bootstraps or adopts a database."""
    with engine.connect() as connection:
        _validate(connection, complete=True)
    return SCHEMA_REVISION


def upgrade_schema(engine):
    """Operator-only offline transaction; adopts only the exact known ledger shape."""
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(731908242)"))
        _validate(connection, complete=False)
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        _validate(connection, complete=True)


def main():
    import argparse
    import os

    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description="Offline private executor schema management (stop all dispatchers first)")
    parser.add_argument("operation", choices=["check", "upgrade"])
    parser.add_argument("--database-url-env", default="ECS_EXECUTOR_DATABASE_URL")
    args = parser.parse_args()
    engine = None
    try:
        engine = create_engine(os.environ[args.database_url_env])
        (upgrade_schema if args.operation == "upgrade" else require_schema)(engine)
        print("Executor schema compatible: " + SCHEMA_REVISION)
    except Exception:
        raise SystemExit("Executor schema check/upgrade refused; inspect compatibility and stopped-writer prerequisites (database URL withheld)") from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
