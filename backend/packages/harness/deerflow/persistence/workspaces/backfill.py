"""Explicit offline personal-space attribution; never invoked by startup.

Caller owns maintenance fencing, coherent backups and the transaction. This
module only handles native DB metadata; executor and NAS receipt verification
remain separate prerequisites for tenant activation. Plans contain identifiers
and must be retained in the operator's private migration receipt directory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import MetaData, Table, insert, select, text, update
from sqlalchemy.engine import Connection

from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceQuotaRow, WorkspaceRow

BACKFILL_REVISION = "0036_tenant_workspaces"
_PERSONAL_NAMESPACE = UUID("d8d9bd22-337d-46db-91c5-b5bb8d04f5b6")
# Topological order: references can only acquire a scope after their parents.
_RESOURCE_KEYS = (
    ("projects", "id"),
    ("threads_meta", "thread_id"),
    ("runs", "run_id"),
    ("project_documents", "id"),
    ("mcp_tasks", "id"),
    ("scheduled_tasks", "id"),
    ("scheduled_task_runs", "id"),
    ("scheduled_task_events", "id"),
    ("run_events", "id"),
)


def plan_personal_backfill(connection: Connection) -> dict:
    """Read-only ownership plan; uncertain or conflicting rows stay unscoped."""
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if revision != [BACKFILL_REVISION]:
        raise RuntimeError("personal backfill requires the reviewed native tenant revision")
    if connection.execute(select(WorkspaceRow.id).where(WorkspaceRow.kind == "team").limit(1)).first():
        raise RuntimeError("legacy personal backfill is forbidden after team provisioning")
    users = sorted(connection.execute(text("SELECT id FROM users")).scalars())
    personal = dict(connection.execute(select(WorkspaceRow.personal_user_id, WorkspaceRow.id).where(WorkspaceRow.kind == "personal")).tuples().all())
    scopes = {user: personal.get(user, str(uuid5(_PERSONAL_NAMESPACE, user))) for user in users}
    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=connection) for name, _ in _RESOURCE_KEYS}
    rows = {}
    for name, key in _RESOURCE_KEYS:
        table = tables[name]
        # Ownership and parent references only; never load transcript/content.
        columns = [table.c[column] for column in (key, "user_id", "workspace_id", "thread_id", "project_id", "run_id", "task_id", "origin_thread_id", "source_thread_id") if column in table.c]
        # run_id/thread_id can also be the primary key: avoid duplicate labels.
        columns = list(dict.fromkeys(columns))
        rows[name] = {row[key]: dict(row) for row in connection.execute(select(*columns)).mappings()}
    attributable: dict[tuple[str, object], str] = {}
    candidates = []
    quarantined = []
    for name, key in _RESOURCE_KEYS:
        for identity, row in sorted(rows[name].items(), key=lambda item: str(item[0])):
            owner = row.get("user_id")
            references = []
            if name == "scheduled_task_runs":
                parent = rows["scheduled_tasks"].get(row["task_id"])
                owner = parent.get("user_id") if parent else None
                references.append(("scheduled_tasks", row["task_id"]))
            if name == "threads_meta" and row.get("project_id"):
                references.append(("projects", row["project_id"]))
            if name == "project_documents":
                references.append(("projects", row["project_id"]))
                if row.get("source_thread_id"):
                    references.append(("threads_meta", row["source_thread_id"]))
            if name in ("runs", "mcp_tasks", "scheduled_task_runs", "scheduled_task_events", "run_events"):
                references.append(("threads_meta", row["thread_id"]))
            if name in ("mcp_tasks", "scheduled_task_runs", "run_events") and row.get("run_id"):
                references.append(("runs", row["run_id"]))
            if name == "scheduled_tasks":
                for field in ("thread_id", "origin_thread_id"):
                    if row.get(field):
                        references.append(("threads_meta", row[field]))
            expected = scopes.get(owner)
            valid = expected is not None and all(attributable.get(reference) == expected for reference in references)
            if row["workspace_id"] is not None and row["workspace_id"] != expected:
                valid = False
            if not valid:
                quarantined.append({"table": name, "id": identity, "reason": "unknown_or_conflicting_owner"})
                continue
            attributable[(name, identity)] = expected
            if row["workspace_id"] is None:
                candidates.append({"table": name, "key": key, "id": identity, "user_id": owner, "workspace_id": expected})
    return {"revision": BACKFILL_REVISION, "users": [{"user_id": user, "workspace_id": scopes[user], "existing": user in personal} for user in users], "resources": candidates, "quarantined": quarantined}


def apply_personal_backfill(connection: Connection) -> dict:
    """Apply within an operator-owned, stopped-writer maintenance transaction.

    Never enables multi-tenancy, changes account verification, deletes source
    records or repairs contradictory ownership. Private receipts retain the
    quarantine list; only counts belong in public deployment logs.
    """
    if not connection.in_transaction():
        raise RuntimeError("personal backfill requires an explicit maintenance transaction")
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(731908243)"))
        connection.execute(text("SELECT id FROM users ORDER BY id FOR UPDATE")).all()
    elif connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise RuntimeError("unsupported tenant maintenance database")
    plan = plan_personal_backfill(connection)
    now = datetime.now(UTC)
    created = 0
    for user in plan["users"]:
        workspace = user["workspace_id"]
        owner = user["user_id"]
        if not user["existing"]:
            connection.execute(insert(WorkspaceRow).values(id=workspace, kind="personal", name="Personal", status="active", personal_user_id=owner, policy_version=1, created_at=now))
            connection.execute(insert(WorkspaceMembershipRow).values(workspace_id=workspace, user_id=owner, role="owner", status="active", version=1, created_at=now))
            connection.execute(insert(WorkspaceQuotaRow).values(workspace_id=workspace, updated_at=now))
            created += 1
        else:
            members = connection.execute(select(WorkspaceMembershipRow.user_id, WorkspaceMembershipRow.role, WorkspaceMembershipRow.status).where(WorkspaceMembershipRow.workspace_id == workspace)).tuples().all()
            if members != [(owner, "owner", "active")]:
                raise RuntimeError("existing personal workspace has incompatible membership")
    metadata = MetaData()
    assigned = 0
    for resource in plan["resources"]:
        table = metadata.tables.get(resource["table"])
        if table is None:
            table = Table(resource["table"], metadata, autoload_with=connection)
        predicate = (table.c[resource["key"]] == resource["id"]) & table.c.workspace_id.is_(None)
        if "user_id" in table.c:
            predicate &= table.c.user_id == resource["user_id"]
        result = connection.execute(update(table).where(predicate).values(workspace_id=resource["workspace_id"]))
        if result.rowcount != 1:
            raise RuntimeError("ownership changed during personal backfill; stop writers and retry from backup receipt")
        assigned += 1
    return {"revision": BACKFILL_REVISION, "created_workspaces": created, "assigned_resources": assigned, "quarantined": plan["quarantined"]}
