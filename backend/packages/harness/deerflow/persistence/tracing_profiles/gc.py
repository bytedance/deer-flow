"""Conservative record cleanup using authoritative non-secret references."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import JSON, LargeBinary, MetaData, Table, Text, cast, delete, exists, func, inspect, or_, select

from deerflow.persistence.agents.sql import get_sync_sessionmaker
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow, TracingProfileRow, TracingProfileVersionRow
from deerflow.persistence.tracing_profiles.sql import _lock_admission_fence

_HEX_ID = re.compile(r"[0-9a-f]{32}")
_CARRIERS = {"runs": ("metadata_json", "kwargs_json"), "scheduled_task_runs": ("tracing_snapshot_refs",), "subagent_batches": ("execution_spec",), "checkpoints": ("metadata",)}


def _authority(session, config):
    if getattr(config, "checkpointer", None) is not None:
        return None, "legacy_or_separate_checkpointer"
    connection = session.connection()
    inspector = inspect(connection)
    tables = {}
    for name, columns in _CARRIERS.items():
        if not inspector.has_table(name):
            return None, "missing_reference_table"
        table = Table(name, MetaData(), autoload_with=connection)
        required = set(columns) | ({"thread_id", "checkpoint_ns", "checkpoint_id", "parent_checkpoint_id", "checkpoint", "type"} if name == "checkpoints" else set())
        if not required <= set(table.c.keys()):
            return None, "unsupported_reference_schema"
        if name == "checkpoints" and set(inspector.get_pk_constraint(name).get("constrained_columns") or ()) != {"thread_id", "checkpoint_ns", "checkpoint_id"}:
            return None, "unsupported_reference_schema"
        for column in columns:
            field = table.c[column]
            if connection.dialect.name == "sqlite":
                expected = (LargeBinary, Text) if name == "checkpoints" else (JSON,)
                if not isinstance(field.type, expected):
                    return None, "unsupported_reference_metadata"
                if session.scalar(select(field).where(field.is_not(None), func.json_valid(field) == 0).limit(1)) is not None:
                    return None, "invalid_reference_metadata"
            elif not isinstance(field.type, JSON):
                return None, "unsupported_reference_metadata"
        tables[name] = table
    return tables, None


def _lock_run_clock(session):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(RunChangeClockRow).values(id=1, value=0).on_conflict_do_nothing(index_elements=[RunChangeClockRow.id]))
    session.execute(select(RunChangeClockRow.id).where(RunChangeClockRow.id == 1).with_for_update())


def _reference_exists(table, column, snapshot_id, dialect):
    field = table.c[column]
    pattern = "%" + snapshot_id + "%"
    if dialect == "sqlite":
        values = func.json_tree(field).table_valued("value", "type", joins_implicitly=True)
        return exists(select(1).select_from(table, values).where(values.c.type == "text", cast(values.c.value, Text).like(pattern)))
    from sqlalchemy.dialects.postgresql import JSONB

    # JSONB normalizes legal Unicode escapes before the conservative match.
    # Inputs that cannot normalize abort the transaction and retain all rows.
    return exists(select(1).select_from(table).where(cast(cast(field, JSONB), Text).like(pattern)))


def cleanup_tracing_records(app_config, *, older_than_days: int = 7, limit: int = 100, apply: bool = False) -> dict:
    """Preview by default; delete only proven unreachable, explicitly released/published rows.

    The shared tracing fence orders run/queue admission; the change-clock lock
    excludes new branch/checkpoint/delete reservations. Existing active operations
    defer snapshot cleanup. Legacy and embedded snapshots remain unmanaged.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    if isinstance(older_than_days, bool) or not isinstance(older_than_days, int) or not 1 <= older_than_days <= 36500:
        raise ValueError("older_than_days must be an integer between 1 and 36500")
    result = {"dry_run": not apply, "snapshot_candidates": 0, "profile_version_candidates": 0, "snapshots_deleted": 0, "profile_versions_deleted": 0, "snapshot_skip_reason": None}
    config = app_config.database
    if config.backend not in {"sqlite", "postgres"}:
        return {**result, "snapshot_skip_reason": "non_durable_backend"}
    if config.backend == "sqlite" and not Path(config.sqlite_path).is_file():
        return {**result, "snapshot_skip_reason": "database_missing"}
    factory = get_sync_sessionmaker(config.app_sync_sqlalchemy_url)
    with factory() as session:
        try:
            _lock_admission_fence(session)
            _lock_run_clock(session)
            live_lease = RunRow.lease_expires_at > func.clock_timestamp() if session.bind.dialect.name == "postgresql" else func.julianday(RunRow.lease_expires_at) > func.julianday("now")
            active = or_(RunRow.status.in_(("pending", "running")), RunRow.owner_worker_id.is_not(None) & live_lease)
            if session.scalar(select(RunRow.run_id).where(active).limit(1)) is not None:
                tables, reason = None, "active_thread_operations"
            else:
                tables, reason = _authority(session, app_config)
            result["snapshot_skip_reason"] = reason
            snapshots = []
            if reason is None:
                candidate = RunTracingSnapshotRow
                predicates = []
                for name, columns in _CARRIERS.items():
                    for column in columns:
                        # Decode JSON escapes before matching; broad string matches
                        # retain false positives without decoding any secret payload.
                        predicates.append(~_reference_exists(tables[name], column, candidate.snapshot_id, session.bind.dialect.name))
                snapshots = list(
                    session.scalars(
                        select(candidate.snapshot_id)
                        .where(candidate.retention_state.in_(("published", "released")), candidate.created_at < datetime.now(UTC) - timedelta(days=older_than_days), *predicates)
                        .order_by(candidate.created_at, candidate.snapshot_id)
                        .limit(limit)
                    )
                )
                snapshots = [snapshot for snapshot in snapshots if _HEX_ID.fullmatch(snapshot)]
                result["snapshot_candidates"] = len(snapshots)
                if apply and snapshots:
                    session.execute(delete(candidate).where(candidate.snapshot_id.in_(snapshots)))
                    session.flush()
                    result["snapshots_deleted"] = len(snapshots)
            version = TracingProfileVersionRow
            retained_snapshot = select(1).where(RunTracingSnapshotRow.profile_id == version.profile_id, RunTracingSnapshotRow.profile_revision == version.revision)
            if snapshots:
                retained_snapshot = retained_snapshot.where(RunTracingSnapshotRow.snapshot_id.not_in(snapshots))
            versions = list(
                session.execute(
                    select(version.profile_id, version.revision)
                    .where(~exists(select(1).where(TracingProfileRow.id == version.profile_id, TracingProfileRow.revision == version.revision)), ~exists(retained_snapshot))
                    .order_by(version.profile_id, version.revision)
                    .limit(limit - len(snapshots))
                )
            )
            result["profile_version_candidates"] = len(versions)
            if apply:
                for profile_id, revision in versions:
                    session.execute(delete(version).where(version.profile_id == profile_id, version.revision == revision))
                result["profile_versions_deleted"] = len(versions)
                session.commit()
            else:
                session.rollback()
        except Exception:
            session.rollback()
            return {**result, "snapshot_candidates": 0, "profile_version_candidates": 0, "snapshots_deleted": 0, "profile_versions_deleted": 0, "snapshot_skip_reason": "authority_validation_failed"}
    return result
