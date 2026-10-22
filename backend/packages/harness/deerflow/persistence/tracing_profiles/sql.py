"""SQL authority for tracing configuration. Each method uses a fresh transaction."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from deerflow.persistence.tracing_profiles.model import AgentTracingBindingRow, RunTracingSnapshotRow, TracingAdmissionFenceRow, TracingProfileRow, TracingProfileVersionRow
from deerflow.persistence.user.model import UserRow


class ProfileRevisionConflict(Exception):
    """The expected revision lost a concurrent compare-and-swap."""


def _lock_admission_fence(session: Session) -> None:
    result = session.execute(update(TracingAdmissionFenceRow).where(TracingAdmissionFenceRow.id == 1).values(version=TracingAdmissionFenceRow.version + 1))
    if result.rowcount != 1:
        raise RuntimeError("Tracing admission authority is unavailable")


def _profile(row: TracingProfileRow) -> dict:
    return {"id": row.id, "name": row.name, "revision": row.revision, "providers_ciphertext": row.providers_ciphertext, "allowed_user_ids": list(row.allowed_user_ids)}


def _binding(row: AgentTracingBindingRow | None) -> dict:
    return {"mode": row.mode, "profile_id": row.profile_id, "revision": row.revision, "agent_incarnation": row.agent_incarnation} if row else {"mode": "inherit", "profile_id": None, "revision": 0, "agent_incarnation": None}


def reset_deleted_agent_binding(session: Session, owner_user_id: str, agent_name: str) -> None:
    """Caller owns the admission fence; retain a revision tombstone against late setters."""
    binding = session.get(AgentTracingBindingRow, (owner_user_id, agent_name))
    if binding is None:
        session.add(AgentTracingBindingRow(owner_user_id=owner_user_id, agent_name=agent_name, mode="inherit", profile_id=None, revision=1, agent_incarnation=None))
    else:
        binding.mode, binding.profile_id, binding.agent_incarnation = "inherit", None, None
        binding.revision += 1


class SqlTracingProfileRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_profiles(self) -> list[dict]:
        with self._sf() as session:
            return [_profile(row) for row in session.scalars(select(TracingProfileRow).order_by(TracingProfileRow.name, TracingProfileRow.id))]

    def get_profile(self, profile_id: str) -> dict | None:
        with self._sf() as session:
            row = session.get(TracingProfileRow, profile_id)
            return _profile(row) if row else None

    def save_profile(self, profile_id: str, *, name: str, providers_ciphertext: str, allowed_user_ids: list[str], expected_revision: int) -> int:
        revision = expected_revision + 1
        values = {"name": name, "providers_ciphertext": providers_ciphertext, "allowed_user_ids": allowed_user_ids, "revision": revision}
        try:
            with self._sf.begin() as session:
                _lock_admission_fence(session)
                if expected_revision == 0:
                    session.add(TracingProfileRow(id=profile_id, **values))
                    session.flush()
                else:
                    result = session.execute(update(TracingProfileRow).where(TracingProfileRow.id == profile_id, TracingProfileRow.revision == expected_revision).values(**values))
                    if result.rowcount != 1:
                        raise ProfileRevisionConflict()
                session.add(TracingProfileVersionRow(profile_id=profile_id, **values))
        except IntegrityError:
            raise ProfileRevisionConflict() from None
        return revision

    def read_state(self, owner_user_id: str, agent_name: str) -> tuple[dict, dict | None]:
        # One statement observes the binding and its current profile together.
        with self._sf() as session:
            stmt = (
                select(AgentTracingBindingRow, TracingProfileRow)
                .outerjoin(TracingProfileRow, AgentTracingBindingRow.profile_id == TracingProfileRow.id)
                .where(AgentTracingBindingRow.owner_user_id == owner_user_id, AgentTracingBindingRow.agent_name == agent_name)
            )
            result = session.execute(stmt).first()
            if result is None:
                return _binding(None), None
            binding, profile = result
            return _binding(binding), _profile(profile) if profile else None

    def read_live_state(self, owner_user_id: str, agent_name: str, identity_resolver) -> tuple[dict, dict | None]:
        incarnation = identity_resolver(agent_name, owner_user_id)
        binding, profile = self.read_state(owner_user_id, agent_name)
        if binding["agent_incarnation"] == incarnation:
            return binding, profile
        with self._sf.begin() as session:
            _lock_admission_fence(session)
            incarnation = identity_resolver(agent_name, owner_user_id)
            row = session.get(AgentTracingBindingRow, (owner_user_id, agent_name))
            if row is None:
                row = AgentTracingBindingRow(owner_user_id=owner_user_id, agent_name=agent_name, mode="inherit", profile_id=None, revision=0, agent_incarnation=incarnation)
                session.add(row)
            elif row.agent_incarnation != incarnation:
                row.mode, row.profile_id, row.agent_incarnation = "inherit", None, incarnation
                row.revision += 1
            session.flush()
            profile_row = session.get(TracingProfileRow, row.profile_id) if row.profile_id else None
            return _binding(row), _profile(profile_row) if profile_row else None

    def save_binding(self, owner_user_id: str, agent_name: str, *, mode: str, profile_id: str | None, expected_revision: int, agent_incarnation: str, identity_resolver) -> int:
        revision = expected_revision + 1
        values = {"mode": mode, "profile_id": profile_id, "revision": revision, "agent_incarnation": agent_incarnation}
        try:
            with self._sf.begin() as session:
                _lock_admission_fence(session)
                if identity_resolver(agent_name, owner_user_id) != agent_incarnation:
                    raise ProfileRevisionConflict()
                current = session.get(AgentTracingBindingRow, (owner_user_id, agent_name))
                if expected_revision == 0 and current is None:
                    session.add(AgentTracingBindingRow(owner_user_id=owner_user_id, agent_name=agent_name, **values))
                else:
                    result = session.execute(
                        update(AgentTracingBindingRow).where(AgentTracingBindingRow.owner_user_id == owner_user_id, AgentTracingBindingRow.agent_name == agent_name, AgentTracingBindingRow.revision == expected_revision).values(**values)
                    )
                    if result.rowcount != 1:
                        raise ProfileRevisionConflict()
        except IntegrityError:
            raise ProfileRevisionConflict() from None
        return revision

    def is_admin(self, user_id: str) -> bool:
        with self._sf() as session:
            return session.scalar(select(UserRow.system_role).where(UserRow.id == user_id, UserRow.disabled.is_(False))) == "admin"

    def save_snapshot(
        self,
        snapshot_id: str,
        owner_user_id: str,
        agent_name: str,
        payload_ciphertext: str,
        *,
        mode: str,
        binding_revision: int,
        profile_id: str | None,
        profile_revision: int | None,
        agent_incarnation: str,
        retention_state: str = "unmanaged",
    ) -> None:
        with self._sf.begin() as session:
            session.add(
                RunTracingSnapshotRow(
                    snapshot_id=snapshot_id,
                    owner_user_id=owner_user_id,
                    agent_name=agent_name,
                    payload_ciphertext=payload_ciphertext,
                    mode=mode,
                    binding_revision=binding_revision,
                    profile_id=profile_id,
                    profile_revision=profile_revision,
                    agent_incarnation=agent_incarnation,
                    retention_state=retention_state,
                )
            )

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        with self._sf() as session:
            row = session.get(RunTracingSnapshotRow, snapshot_id)
            if row is None:
                return None
            return {"owner_user_id": row.owner_user_id, "agent_name": row.agent_name, "payload_ciphertext": row.payload_ciphertext, "retention_state": row.retention_state}

    def release_snapshot(self, snapshot_id: str, owner_user_id: str) -> bool:
        with self._sf.begin() as session:
            _lock_admission_fence(session)
            result = session.execute(
                update(RunTracingSnapshotRow)
                .where(RunTracingSnapshotRow.snapshot_id == snapshot_id, RunTracingSnapshotRow.owner_user_id == owner_user_id, RunTracingSnapshotRow.retention_state == "pending")
                .values(retention_state="released")
            )
            return result.rowcount == 1

    def protect_snapshot(self, snapshot_id: str, owner_user_id: str) -> bool:
        from deerflow.tracing.profiles import TracingAuthorizationError, TracingUnavailableError

        with self._sf.begin() as session:
            _lock_admission_fence(session)
            snapshot = session.execute(select(RunTracingSnapshotRow.owner_user_id, RunTracingSnapshotRow.retention_state).where(RunTracingSnapshotRow.snapshot_id == snapshot_id)).first()
            if snapshot is None or snapshot.retention_state not in {"pending", "published", "unmanaged"}:
                raise TracingUnavailableError("The run tracing snapshot is unavailable")
            if snapshot.owner_user_id != owner_user_id:
                raise TracingAuthorizationError("The tracing snapshot belongs to another execution scope")
            if snapshot.retention_state != "unmanaged":
                result = session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot_id, RunTracingSnapshotRow.owner_user_id == owner_user_id).values(retention_state="unmanaged"))
                if result.rowcount != 1:
                    raise TracingUnavailableError("The run tracing snapshot is unavailable")
            return True

    def protect_history(self) -> int:
        with self._sf.begin() as session:
            _lock_admission_fence(session)
            result = session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.retention_state.in_(("pending", "published"))).values(retention_state="unmanaged"))
            return result.rowcount


async def _read_admission_fence(session: AsyncSession) -> None:
    """Admissions share the authority; configuration edits retain its writer lock."""
    connection = await session.connection()
    if connection.dialect.name == "sqlite":
        raw = await connection.get_raw_connection()
        if raw.driver_connection.in_transaction:
            # A caller may already own a writer, or an explicit deferred read
            # transaction. Reserve its writer without nesting BEGIN; a stale
            # SQLite read snapshot cannot upgrade and must fail closed.
            result = await session.execute(update(TracingAdmissionFenceRow).where(TracingAdmissionFenceRow.id == 1).values(version=TracingAdmissionFenceRow.version + 1))
            available = result.rowcount == 1
        else:
            # SQLAlchemy autobegin alone does not start a SQLite transaction.
            await session.execute(text("BEGIN IMMEDIATE"))
            available = await session.scalar(select(TracingAdmissionFenceRow.id).where(TracingAdmissionFenceRow.id == 1)) == 1
    else:
        available = await session.scalar(select(TracingAdmissionFenceRow.id).where(TracingAdmissionFenceRow.id == 1).with_for_update(read=True)) == 1
    if not available:
        from deerflow.tracing.profiles import TracingUnavailableError

        raise TracingUnavailableError("Tracing admission authority is unavailable")


async def validate_tracing_admission(session: AsyncSession, metadata: Mapping[str, Any] | None, *, owner_user_id: str | None = None, agent_name: str | None = None) -> None:
    """Fence activation until the caller's run INSERT transaction commits.

    The caller must scrub ``deerflow_tracing_pinned`` from every external input.
    Only an already-admitted queue occurrence or resumed run may set it. This
    method intentionally reads safe revision columns, never decrypting credentials.
    """
    from deerflow.runtime.user_context import get_effective_user_id
    from deerflow.tracing.profiles import TracingAuthorizationError, TracingConflictError, TracingUnavailableError, canonical_agent_name

    metadata = metadata or {}
    snapshot_id = metadata.get("deerflow_tracing_snapshot_id")
    recorded_agent = metadata.get("deerflow_tracing_agent_name")
    if snapshot_id is None and recorded_agent is None:
        if metadata.get("deerflow_tracing_managed") is True:
            raise TracingUnavailableError("Managed run tracing references are unavailable")
        return
    if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(recorded_agent, str):
        raise TracingUnavailableError("The run tracing snapshot is unavailable")
    # Acquire authority before run/change-clock/task locks and retain to commit.
    await _read_admission_fence(session)
    snapshot = (
        await session.execute(
            select(
                RunTracingSnapshotRow.owner_user_id,
                RunTracingSnapshotRow.agent_name,
                RunTracingSnapshotRow.mode,
                RunTracingSnapshotRow.binding_revision,
                RunTracingSnapshotRow.profile_id,
                RunTracingSnapshotRow.profile_revision,
                RunTracingSnapshotRow.agent_incarnation,
                RunTracingSnapshotRow.retention_state,
            ).where(RunTracingSnapshotRow.snapshot_id == snapshot_id)
        )
    ).first()
    if snapshot is None or snapshot.retention_state == "released":
        raise TracingUnavailableError("The run tracing snapshot is unavailable")
    owner = owner_user_id if owner_user_id is not None else get_effective_user_id()
    if snapshot.owner_user_id != owner or snapshot.agent_name != canonical_agent_name(recorded_agent) or (agent_name is not None and snapshot.agent_name != canonical_agent_name(agent_name)):
        raise TracingAuthorizationError("The tracing snapshot belongs to another execution scope")
    binding = await session.get(AgentTracingBindingRow, (snapshot.owner_user_id, snapshot.agent_name), populate_existing=True)
    current = _binding(binding)
    if current["agent_incarnation"] != snapshot.agent_incarnation:
        raise TracingConflictError("The Agent was replaced; retry with the current Agent")
    # Verify the live definition too: a filesystem deletion can survive a
    # crashed DB transaction, leaving its binding tombstone uncommitted.
    if snapshot.agent_incarnation.startswith("db:"):
        from deerflow.persistence.agents.model import AgentRow

        identity = await session.scalar(select(AgentRow.id).where(AgentRow.user_id == snapshot.owner_user_id, AgentRow.name == snapshot.agent_name))
        if identity is None or f"db:{identity}" != snapshot.agent_incarnation:
            raise TracingConflictError("The Agent was replaced; retry with the current Agent")
    elif snapshot.agent_incarnation.startswith("file:"):
        import asyncio

        from deerflow.persistence.tracing_profiles.identity import resolve_file_agent_incarnation

        try:
            identity = await asyncio.to_thread(resolve_file_agent_incarnation, snapshot.agent_name, snapshot.owner_user_id)
        except (OSError, ValueError):
            raise TracingConflictError("The Agent is unavailable; reload its configuration") from None
        if identity != snapshot.agent_incarnation:
            raise TracingConflictError("The Agent was replaced; retry with the current Agent")
    if metadata.get("deerflow_tracing_pinned") is not True:
        if (current["revision"], current["mode"], current["profile_id"]) != (snapshot.binding_revision, snapshot.mode, snapshot.profile_id):
            raise TracingConflictError("Tracing configuration changed; retry the run")
        if snapshot.profile_id is not None:
            profile_revision = await session.scalar(select(TracingProfileRow.revision).where(TracingProfileRow.id == snapshot.profile_id))
            if profile_revision is None or profile_revision != snapshot.profile_revision:
                raise TracingConflictError("Tracing configuration changed; retry the run")
    if snapshot.retention_state == "pending":
        await session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot_id, RunTracingSnapshotRow.retention_state == "pending").values(retention_state="published"))
