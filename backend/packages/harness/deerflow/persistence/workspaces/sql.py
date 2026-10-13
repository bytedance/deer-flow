"""Durable workspace provisioning and live membership in native SQL storage.

No Gateway imports or alternate account authority. Caller authenticates actors;
HTTP permission scopes and recent reauthentication remain Gateway concerns.
Internal member activation is for reviewed onboarding/invite services, never a
public invitation substitute. Tenant mode has no ephemeral memory fallback.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4, uuid5

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.backfill import _PERSONAL_NAMESPACE
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceOperationOutboxRow, WorkspaceQuotaRow, WorkspaceRow


class WorkspaceAccessDenied(ValueError):
    """Missing/inactive membership, account or invalid ownership transition."""


def workspace_repository(session_factory, *, enabled):
    if not enabled:
        return None
    if session_factory is None:
        raise ValueError("tenant mode requires persistent SQL storage")
    return WorkspaceRepository(session_factory)


class WorkspaceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    @staticmethod
    async def _begin_write(session):
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    async def _user(session, user_id, *, lock=False):
        query = select(UserRow).where(UserRow.id == user_id)
        if lock:
            query = query.with_for_update()
        user = await session.scalar(query)
        if user is None or user.account_status != "active" or user.email_verified_at is None:
            raise WorkspaceAccessDenied("active verified account required")
        return user

    @staticmethod
    def _view(workspace, member=None):
        result = workspace.to_dict()
        if member is not None:
            result.update(role=member.role, membership_version=member.version)
        return result

    async def provision_personal(self, user_id):
        async with self._sf() as session:
            await self._begin_write(session)
            await self._user(session, user_id, lock=True)
            workspace = await session.scalar(select(WorkspaceRow).where(WorkspaceRow.personal_user_id == user_id))
            if workspace is not None:
                members = (await session.execute(select(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == workspace.id))).scalars().all()
                if workspace.kind != "personal" or workspace.status != "active" or len(members) != 1 or members[0].user_id != user_id or members[0].role != "owner" or members[0].status != "active":
                    raise WorkspaceAccessDenied("personal ownership is incompatible")
                return self._view(workspace)
            workspace = WorkspaceRow(id=str(uuid5(_PERSONAL_NAMESPACE, user_id)), kind="personal", name="Personal", personal_user_id=user_id, status="active", policy_version=1)
            session.add(workspace)
            await session.flush()
            session.add_all([WorkspaceMembershipRow(workspace_id=workspace.id, user_id=user_id, role="owner", status="active", version=1), WorkspaceQuotaRow(workspace_id=workspace.id)])
            await session.commit()
            return self._view(workspace)

    async def create_team(self, user_id, name, idempotency_key):
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("workspace name must contain 1-128 characters")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 64:
            raise ValueError("idempotency key must contain 1-64 characters")
        name = name.strip()
        operation_id = hashlib.sha256(json.dumps(["team_create", user_id, idempotency_key], separators=(",", ":")).encode()).hexdigest()
        async with self._sf() as session:
            await self._begin_write(session)
            await self._user(session, user_id, lock=True)
            operation = await session.get(WorkspaceOperationOutboxRow, operation_id)
            if operation is not None:
                if operation.kind != "team_create" or operation.user_id != user_id or operation.payload != {"name": name} or operation.state != "completed":
                    raise ValueError("idempotency key conflicts with earlier operation")
                workspace = await session.scalar(select(WorkspaceRow).where(WorkspaceRow.id == operation.workspace_id).with_for_update())
                if workspace is None or workspace.kind != "team" or workspace.status != "active":
                    raise WorkspaceAccessDenied("previous team is no longer active")
                member = await session.get(WorkspaceMembershipRow, (workspace.id, user_id))
                if member is None or member.status != "active":
                    raise WorkspaceAccessDenied("idempotent team retry requires current membership")
                return self._view(workspace)
            workspace = WorkspaceRow(id=str(uuid4()), kind="team", name=name, status="active", policy_version=1)
            session.add(workspace)
            await session.flush()
            session.add_all(
                [
                    WorkspaceMembershipRow(workspace_id=workspace.id, user_id=user_id, role="owner", status="active", version=1),
                    WorkspaceQuotaRow(workspace_id=workspace.id),
                    WorkspaceOperationOutboxRow(operation_id=operation_id, workspace_id=workspace.id, user_id=user_id, kind="team_create", payload={"name": name}, state="completed"),
                ]
            )
            await session.commit()
            return self._view(workspace)

    @staticmethod
    def _membership_query(user_id):
        return (
            select(WorkspaceRow, WorkspaceMembershipRow)
            .join(WorkspaceMembershipRow, WorkspaceMembershipRow.workspace_id == WorkspaceRow.id)
            .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
            .where(
                WorkspaceMembershipRow.user_id == user_id,
                WorkspaceMembershipRow.status == "active",
                WorkspaceRow.status == "active",
                UserRow.account_status == "active",
                UserRow.email_verified_at.is_not(None),
                or_(WorkspaceRow.kind == "team", and_(WorkspaceRow.kind == "personal", WorkspaceRow.personal_user_id == user_id, WorkspaceMembershipRow.role == "owner")),
            )
        )

    async def get_active_membership(self, workspace_id, user_id):
        async with self._sf() as session:
            pair = (await session.execute(self._membership_query(user_id).where(WorkspaceRow.id == workspace_id))).first()
            if pair is None:
                return None
            workspace, member = pair
            return {"workspace_id": workspace.id, "user_id": member.user_id, "role": member.role, "membership_version": member.version, "policy_version": workspace.policy_version}

    async def list_workspaces(self, user_id):
        async with self._sf() as session:
            rows = (await session.execute(self._membership_query(user_id).order_by(WorkspaceRow.created_at, WorkspaceRow.id))).all()
            return [self._view(workspace, member) for workspace, member in rows]

    async def _locked_team(self, session, workspace_id, actor_user_id):
        await self._begin_write(session)
        workspace = await session.scalar(select(WorkspaceRow).where(WorkspaceRow.id == workspace_id).with_for_update())
        if workspace is None or workspace.kind != "team" or workspace.status != "active":
            raise WorkspaceAccessDenied("active team required")
        await self._user(session, actor_user_id)
        actor = await session.get(WorkspaceMembershipRow, (workspace_id, actor_user_id))
        if actor is None or actor.status != "active":
            raise WorkspaceAccessDenied("active team membership required")
        return workspace, actor

    async def add_member(self, workspace_id, actor_user_id, user_id, *, role):
        if role not in ("admin", "member"):
            raise ValueError("member role must be admin or member")
        async with self._sf() as session:
            _, actor = await self._locked_team(session, workspace_id, actor_user_id)
            if actor.role != "owner" and not (actor.role == "admin" and role == "member"):
                raise WorkspaceAccessDenied("member activation is not permitted")
            await self._user(session, user_id)
            member = await session.get(WorkspaceMembershipRow, (workspace_id, user_id))
            if member is not None and member.status == "active":
                if member.role != role:
                    raise WorkspaceAccessDenied("activation cannot alter an active role")
                return member.to_dict()
            if member is None:
                member = WorkspaceMembershipRow(workspace_id=workspace_id, user_id=user_id, role=role, status="active", version=1)
                session.add(member)
            else:
                member.role, member.status, member.version = role, "active", member.version + 1
            await session.commit()
            return member.to_dict()

    async def change_role(self, workspace_id, actor_user_id, user_id, *, role):
        if role not in ("admin", "member"):
            raise ValueError("member role must be admin or member")
        async with self._sf() as session:
            _, actor = await self._locked_team(session, workspace_id, actor_user_id)
            member = await session.get(WorkspaceMembershipRow, (workspace_id, user_id))
            if actor.role != "owner" or member is None or member.status != "active" or member.role == "owner":
                raise WorkspaceAccessDenied("role transition is not permitted")
            if member.role != role:
                member.role, member.version = role, member.version + 1
            await session.commit()
            return member.to_dict()

    async def remove_member(self, workspace_id, actor_user_id, user_id):
        async with self._sf() as session:
            _, actor = await self._locked_team(session, workspace_id, actor_user_id)
            member = await session.get(WorkspaceMembershipRow, (workspace_id, user_id))
            if member is None or member.status != "active":
                raise WorkspaceAccessDenied("active target membership required")
            allowed = actor.user_id == user_id or actor.role == "owner" or (actor.role == "admin" and member.role == "member")
            if member.role == "owner" or not allowed:
                raise WorkspaceAccessDenied("last owner or protected membership cannot be removed")
            member.status, member.version = "removed", member.version + 1
            await session.commit()
            return member.to_dict()

    async def transfer_owner(self, workspace_id, actor_user_id, user_id):
        async with self._sf() as session:
            _, actor = await self._locked_team(session, workspace_id, actor_user_id)
            await self._user(session, user_id)
            target = await session.get(WorkspaceMembershipRow, (workspace_id, user_id))
            if actor.role != "owner" or user_id == actor_user_id or target is None or target.status != "active":
                raise WorkspaceAccessDenied("ownership transfer requires current owner and active target")
            actor.role, actor.version = "admin", actor.version + 1
            # Avoid the unique active-owner index while keeping both changes in
            # one transaction; readers never observe a committed ownerless team.
            await session.flush()
            target.role, target.version = "owner", target.version + 1
            await session.commit()
            return target.to_dict()
