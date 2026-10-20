"""Short synchronous transactions, always acquired after the owner file guard."""

from __future__ import annotations

import uuid

from deerflow_extension_api.host_capabilities import HostCapabilityError
from deerflow_extension_api.skill_mutations import AssetRevision
from sqlalchemy import select, update

from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOperationRow, SkillOwnerRow
from deerflow.persistence.user.model import UserRow


def revision(row: SkillAssetRow) -> AssetRevision:
    return AssetRevision(row.incarnation_id, row.mutation_seq, row.content_digest)


def supersede_views(session, owner_id, generation):
    session.execute(
        update(SkillOperationRow)
        .where(SkillOperationRow.owner_id == owner_id, SkillOperationRow.publication.in_(("APPLIED", "NO_CHANGE")), SkillOperationRow.generation < generation, SkillOperationRow.views != "SUPERSEDED")
        .values(views="SUPERSEDED", superseded_by_generation=generation)
    )


class SkillMutationRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    def owner(self, session, owner_id: str) -> SkillOwnerRow:
        user = session.get(UserRow, owner_id)
        if user is None:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        row = session.get(SkillOwnerRow, owner_id, with_for_update=True)
        if row is None:
            row = SkillOwnerRow(owner_id=owner_id, generation=0, deleting=False)
            session.add(row)
            session.flush()
        if row.deleting:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        return row

    @staticmethod
    def asset(session, owner_id: str, name: str) -> SkillAssetRow | None:
        return session.scalar(select(SkillAssetRow).where(SkillAssetRow.owner_id == owner_id, SkillAssetRow.name == name))

    def observe(self, owner_id: str, name: str, digest: str, enabled: bool, *, exists: bool, mark_mutating: bool = False) -> SkillAssetRow:
        with self.sessions.begin() as session:
            owner = self.owner(session, owner_id)
            row = self.asset(session, owner_id, name)
            if row is not None and row.operation_id is not None:
                operation = session.get(SkillOperationRow, row.operation_id)
                if operation is not None and operation.publication in {"PREPARED", "NEEDS_REPAIR"}:
                    raise HostCapabilityError("NEEDS_REPAIR")
            if row is None:
                row = SkillAssetRow(
                    target_ref=uuid.uuid4().hex,
                    owner_id=owner_id,
                    name=name,
                    incarnation_id=uuid.uuid4().hex,
                    mutation_seq=1,
                    content_digest=digest,
                    enabled=enabled,
                    deleted=not exists,
                    mutating=False,
                )
                session.add(row)
                owner.generation += 1
            elif row.mutating or (row.content_digest, row.enabled, row.deleted) != (digest, enabled, not exists):
                if row.deleted and exists:
                    row.incarnation_id = uuid.uuid4().hex
                row.mutation_seq += 1
                row.content_digest, row.enabled, row.deleted = digest, enabled, not exists
                row.operation_id = None
                owner.generation += 1
            row.mutating = mark_mutating
            supersede_views(session, owner_id, owner.generation)
            session.flush()
            return row

    def finish_writer(self, owner_id: str, name: str, digest: str, enabled: bool, *, exists: bool) -> None:
        with self.sessions.begin() as session:
            owner = self.owner(session, owner_id)
            row = self.asset(session, owner_id, name)
            if row is None or not row.mutating:
                raise HostCapabilityError("NEEDS_REPAIR")
            if (row.content_digest, row.enabled, row.deleted) != (digest, enabled, not exists):
                if row.deleted and exists:
                    row.incarnation_id = uuid.uuid4().hex
                row.mutation_seq += 1
                row.content_digest, row.enabled, row.deleted = digest, enabled, not exists
                row.operation_id = None
                owner.generation += 1
            row.mutating = False
            supersede_views(session, owner_id, owner.generation)

    def generation(self, owner_id: str) -> int:
        with self.sessions() as session:
            row = session.get(SkillOwnerRow, owner_id)
            return row.generation if row else 0

    def check_readable(self, owner_id: str) -> None:
        with self.sessions() as session:
            if session.get(UserRow, owner_id) is None:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            owner = session.get(SkillOwnerRow, owner_id)
            if owner is not None and owner.deleting:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            blocked = session.scalar(
                select(SkillOperationRow.operation_id)
                .where(
                    SkillOperationRow.owner_id == owner_id,
                    SkillOperationRow.publication.in_(("PREPARED", "NEEDS_REPAIR")),
                )
                .limit(1)
            )
            uncertain = session.scalar(
                select(SkillAssetRow.target_ref)
                .where(
                    SkillAssetRow.owner_id == owner_id,
                    SkillAssetRow.mutating.is_(True),
                )
                .limit(1)
            )
            if blocked is not None or uncertain is not None:
                raise HostCapabilityError("NEEDS_REPAIR")
