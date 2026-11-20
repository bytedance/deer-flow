"""Fail closed when an embedded process lacks the enrolled owner's runtime.

Enrollment belongs to the application database, not the current plugin list or
process. Do not cache negative lookups: a Gateway can enroll an owner after an
SDK client has already been constructed. Probes never create/migrate a database.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from deerflow_extension_api.host_capabilities import HostCapabilityError
from sqlalchemy import create_engine, inspect, select, union_all
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOwnerRow


def require_unenrolled(storage, *, global_scope: bool = False) -> None:
    config = getattr(storage, "_app_config", None)
    database = getattr(config, "database", None)
    if database is None or database.backend == "memory":
        return
    owner_id = getattr(storage, "user_id", None)
    if owner_id is None and not global_scope:
        return
    engine = None
    try:
        url = make_url(database.app_sync_sqlalchemy_url)
        if database.backend == "sqlite":
            path = Path(database.sqlite_path)
            if not path.exists():
                return
            # URI read-only mode closes the exists/connect creation race and
            # avoids journal/schema changes in an uninitialized SDK process.
            url = url.set(database="file:" + quote(str(path), safe="/"), query={"mode": "ro", "uri": "true"})
            args = {"timeout": 5}
        else:
            from deerflow.persistence.postgres_schema import build_psycopg_options

            options = build_psycopg_options(database.postgres_schema) or ""
            args = {"connect_timeout": 5, "options": f"{options} -c lock_timeout=5000 -c statement_timeout=5000".strip()}
        # A short-lived connection has no process-wide SDK teardown requirement
        # and cannot retain an enrollment snapshot across later skill calls.
        engine = create_engine(url, connect_args=args, poolclass=NullPool)
        with engine.connect() as connection:
            schema = inspect(connection)
            queries = []
            for model in (SkillOwnerRow, SkillAssetRow):
                if schema.has_table(model.__tablename__):
                    query = select(model.owner_id)
                    queries.append(query if global_scope else query.where(model.owner_id == owner_id))
            enrolled = bool(queries) and connection.execute(union_all(*queries).limit(1)).first() is not None
        if enrolled:
            raise HostCapabilityError("MUTATION_RUNTIME_REQUIRED", "Use the Gateway for enrolled skill access; this process has no durable mutation runtime")
    except (SQLAlchemyError, OSError) as exc:
        # Unavailable enrollment is not proof that a write is unmanaged. Do not
        # expose a DB URL or driver diagnostics in the public exception.
        raise HostCapabilityError("UNAVAILABLE", "Cannot verify durable skill enrollment") from exc
    finally:
        if engine is not None:
            engine.dispose()
