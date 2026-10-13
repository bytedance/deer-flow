"""Offline attribution from a pinned native ownership export, never runtime auth.

Only the operator's paired migration flow may provide bindings. It must fence
writers and retain coherent backups plus both database receipts. This module
has no native database access and imports no Gateway or harness authority.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import MetaData, Table, select, text, update

from ecs_executor.job_store import _JOBS
from ecs_executor.schema import SCHEMA_REVISION, _validate

NATIVE_REVISION = "0037_project_visibility"
_IDENTITY_FIELDS = ("user_id", "thread_id", "incarnation")


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _binding_maps(bindings):
    if not isinstance(bindings, dict) or set(bindings) != {"native_revision", "threads", "runs"} or bindings["native_revision"] != NATIVE_REVISION:
        raise ValueError("native ownership export revision/shape is incompatible")
    maps = []
    for name, fields in (("threads", _IDENTITY_FIELDS), ("runs", (*_IDENTITY_FIELDS, "run_id"))):
        if not isinstance(bindings[name], list):
            raise ValueError("native ownership export must contain explicit bindings")
        values = {}
        for row in bindings[name]:
            if not isinstance(row, dict) or set(row) != {*fields, "workspace_id"}:
                raise ValueError("native ownership binding shape is incompatible")
            for field in fields:
                value = row[field]
                if field == "incarnation" and value is None:
                    continue
                if not isinstance(value, str) or not value or len(value) > (32 if field == "incarnation" else 64):
                    raise ValueError("native ownership identity is invalid")
            workspace = row["workspace_id"]
            if not isinstance(workspace, str) or str(UUID(workspace)) != workspace:
                raise ValueError("native ownership workspace must be a canonical UUID")
            key = tuple(row[field] for field in fields)
            if key in values:
                raise ValueError("duplicate native ownership binding")
            if name == "runs" and maps[0].get(key[:3]) != workspace:
                raise ValueError("native run/thread ownership conflicts")
            values[key] = workspace
        maps.append(values)
    return maps


def plan_workspace_attribution(connection, bindings, *, _lock=False):
    """Read-only private plan; no payload, result or secret appears in the plan."""
    threads, runs = _binding_maps(bindings)
    _validate(connection, complete=True)
    affinities = Table("ecs_native_affinities", MetaData(), autoload_with=connection)
    job_query = select(_JOBS).order_by(_JOBS.c.id)
    affinity_query = select(affinities).order_by(affinities.c.user_id, affinities.c.thread_id, affinities.c.incarnation)
    if _lock:
        job_query = job_query.with_for_update()
        affinity_query = affinity_query.with_for_update()
    jobs = []
    affinity_rows = []
    quarantined = []
    for row in connection.execute(job_query):
        record = row.record
        kind = record.get("kind", "B") if isinstance(record, dict) else None
        identity = record.get("native") if kind == "C" else record if kind == "B" else None
        if not isinstance(identity, dict):
            expected = None
        else:
            key = tuple(identity.get(field) for field in (*_IDENTITY_FIELDS, "run_id"))
            # Malformed JSON identity values cannot become dictionary keys.
            expected = runs.get(key) if all(value is None or isinstance(value, str) for value in key) else None
        if expected is None or row.workspace_id not in (None, expected) or record.get("workspace_id") not in (None, expected) or identity.get("workspace_id") not in (None, expected):
            quarantined.append({"table": "ecs_execution_jobs", "id": row.id, "reason": "unknown_or_conflicting_native_owner"})
            continue
        if row.workspace_id is None or record.get("workspace_id") is None:
            jobs.append({"id": row.id, "version": row.version, "workspace_id": expected, "record_sha256": _digest(record)})
    for row in connection.execute(affinity_query):
        identity = {field: getattr(row, field) for field in _IDENTITY_FIELDS}
        expected = threads.get(tuple(identity.values()))
        if expected is None or row.workspace_id not in (None, expected):
            quarantined.append({"table": "ecs_native_affinities", "id": _digest(identity), "reason": "unknown_or_conflicting_native_owner"})
        elif row.workspace_id is None:
            affinity_rows.append({**identity, "node_id": row.node_id, "workspace_id": expected})
    return {"native_revision": NATIVE_REVISION, "executor_revision": SCHEMA_REVISION, "bindings_sha256": _digest(bindings), "jobs": jobs, "affinities": affinity_rows, "quarantined": quarantined}


def apply_workspace_attribution(connection, bindings):
    """Apply scope only; never mutate versions, physical state or native snapshot."""
    if not connection.in_transaction():
        raise RuntimeError("executor attribution requires an explicit maintenance transaction")
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(731908244)"))
    elif connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise RuntimeError("unsupported executor maintenance database")
    plan = plan_workspace_attribution(connection, bindings, _lock=True)
    for entry in plan["jobs"]:
        row = connection.execute(select(_JOBS).where(_JOBS.c.id == entry["id"])).one()
        if row.version != entry["version"] or _digest(row.record) != entry["record_sha256"]:
            raise RuntimeError("execution changed during workspace attribution")
        record = {**row.record, "workspace_id": entry["workspace_id"]}
        result = connection.execute(update(_JOBS).where(_JOBS.c.id == row.id, _JOBS.c.version == row.version).values(workspace_id=entry["workspace_id"], record=record))
        if result.rowcount != 1:
            raise RuntimeError("execution attribution lost its maintenance fence")
    affinities = Table("ecs_native_affinities", MetaData(), autoload_with=connection)
    for entry in plan["affinities"]:
        predicates = [affinities.c[field] == entry[field] for field in (*_IDENTITY_FIELDS, "node_id")]
        result = connection.execute(update(affinities).where(*predicates, affinities.c.workspace_id.is_(None)).values(workspace_id=entry["workspace_id"]))
        if result.rowcount != 1:
            raise RuntimeError("affinity changed during workspace attribution")
    return {
        "native_revision": NATIVE_REVISION,
        "executor_revision": SCHEMA_REVISION,
        "bindings_sha256": plan["bindings_sha256"],
        "assigned_jobs": len(plan["jobs"]),
        "assigned_affinities": len(plan["affinities"]),
        "quarantined": plan["quarantined"],
    }
