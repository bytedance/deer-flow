"""Host-owned recovery, deletion fencing and retention independent of plugins."""

from __future__ import annotations

import time

from deerflow_extension_api.host_capabilities import HostCapabilityError
from sqlalchemy import and_, delete, exists, literal, or_, select, update

from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOperationRow, SkillOwnerRow, SkillProposalRow, SkillScanAttemptRow
from deerflow.skills.mutations.codec import operation_view
from deerflow.skills.mutations.publication import resolve_prepared
from deerflow.skills.mutations.repository import supersede_views
from deerflow.skills.projection import skill_projection_read_lock


class SkillMutationRecovery:
    def __init__(self, runtime, storage_factory, *, rebuild_views=None):
        self.runtime, self.storage_factory = runtime, storage_factory
        self.repository = runtime.repository
        if rebuild_views is None:
            from deerflow.skills.projection import rebuild_skill_projections

            def rebuild_views(storage):
                return rebuild_skill_projections(storage, include_public=False)

        self.rebuild_views = rebuild_views
        runtime.recover_locked = self.recover_locked

    def get_operation(self, operation_id):
        with self.repository.sessions() as session:
            row = session.get(SkillOperationRow, operation_id)
            if row is None:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            return operation_view(row)

    def list_operations(self, *, limit=50, after_id=None):
        if type(limit) is not int or not 1 <= limit <= 101 or (after_id is not None and (not isinstance(after_id, str) or len(after_id) > 32)):
            raise HostCapabilityError("INVALID_REQUEST")
        with self.repository.sessions() as session:
            cursor = session.get(SkillOperationRow, after_id) if after_id else None
            if after_id and cursor is None:
                return ()
            after = or_(SkillOperationRow.created_at > cursor.created_at, and_(SkillOperationRow.created_at == cursor.created_at, SkillOperationRow.operation_id > cursor.operation_id)) if cursor is not None else True
            rows = session.scalars(
                select(SkillOperationRow)
                .where(
                    or_(SkillOperationRow.publication.in_(("PREPARED", "NEEDS_REPAIR")), (SkillOperationRow.publication == "APPLIED") & SkillOperationRow.views.in_(("PENDING", "ERROR"))),
                    after,
                )
                .order_by(SkillOperationRow.created_at, SkillOperationRow.operation_id)
                .limit(limit)
            ).all()
            return tuple(operation_view(row) for row in rows)

    def recover_locked(self, storage):
        """Caller owns owner lock. No projection rebuild or plugin callbacks."""
        with self.repository.sessions() as session:
            pending = session.scalars(select(SkillOperationRow.operation_id).where(SkillOperationRow.owner_id == storage.user_id, SkillOperationRow.publication.in_(("PREPARED", "NEEDS_REPAIR")))).all()
        for operation_id in pending:
            resolve_prepared(self.repository, storage, operation_id)
        with self.repository.sessions() as session:
            uncertain = session.scalars(select(SkillAssetRow.name).where(SkillAssetRow.owner_id == storage.user_id, SkillAssetRow.mutating.is_(True))).all()
        for name in uncertain:
            digest, enabled, exists = self.runtime.state(storage, name)
            self.repository.observe(storage.user_id, name, digest, enabled, exists=exists)

    def refresh_views(self, owner_id):
        storage = self.storage_factory(owner_id)
        with skill_projection_read_lock(storage):
            with self.repository.sessions.begin() as session:
                owner = session.get(SkillOwnerRow, owner_id)
                if owner is None or owner.deleting:
                    return
                from deerflow.skills.mutations.history import mirror_operations

                recent = session.scalars(
                    select(SkillOperationRow).where(SkillOperationRow.owner_id == owner_id, SkillOperationRow.publication == "APPLIED").order_by(SkillOperationRow.created_at.desc(), SkillOperationRow.operation_id).limit(100)
                ).all()
                try:
                    mirror_operations(storage, [operation_view(row) for row in recent])
                except Exception:
                    # Mirror availability never changes publication/view status.
                    pass
                generation = owner.generation
                supersede_views(session, owner_id, generation)
                operations = session.scalars(select(SkillOperationRow.operation_id).where(SkillOperationRow.owner_id == owner_id, SkillOperationRow.publication == "APPLIED", SkillOperationRow.views.in_(("PENDING", "ERROR")))).all()
        if not operations:
            return
        try:
            self.rebuild_views(storage)
            state = "READY"
        except Exception:
            state = "ERROR"
        with skill_projection_read_lock(storage), self.repository.sessions.begin() as session:
            owner = session.get(SkillOwnerRow, owner_id)
            for operation_id in operations:
                row = session.get(SkillOperationRow, operation_id)
                if row is not None:
                    row.views = state if owner and owner.generation == row.generation == generation else "SUPERSEDED"
                    if row.views == "SUPERSEDED" and owner:
                        row.superseded_by_generation = owner.generation

    def recover_owner(self, owner_id):
        storage = self.storage_factory(owner_id)
        with skill_projection_read_lock(storage):
            self.recover_locked(storage)
            self.repository.check_readable(owner_id)
        self.refresh_views(owner_id)

    def recover_operation(self, operation_id):
        operation = self.get_operation(operation_id)
        try:
            self.recover_owner(operation.owner_id)
        except HostCapabilityError as exc:
            if exc.code != "NEEDS_REPAIR":
                raise
        return self.get_operation(operation_id)

    def recover_all(self):
        for owner_id in self._owners():
            try:
                self.recover_owner(owner_id)
            except (HostCapabilityError, OSError, TimeoutError):
                # Owner readiness remains closed; admin recovery stays reachable.
                continue

    def _owners(self):
        after = ""
        while True:
            with self.repository.sessions() as session:
                owners = session.scalars(select(SkillOwnerRow.owner_id).where(SkillOwnerRow.owner_id > after).order_by(SkillOwnerRow.owner_id).limit(100)).all()
            if not owners:
                return
            yield from owners
            after = owners[-1]

    def quiesce_owner(self, owner_id):
        # Accepted workers own this same lock through finalization. Taking it
        # drains them before admission is fenced. Deletion need not keep blobs.
        storage = self.storage_factory(owner_id)
        with skill_projection_read_lock(storage):
            self.recover_locked(storage)
            with self.repository.sessions.begin() as session:
                owner = session.get(SkillOwnerRow, owner_id)
                if owner is None:
                    owner = self.repository.owner(session, owner_id)
                owner.deleting = True

    def collect_garbage(self):
        now = time.time()
        for owner_id in self._owners():
            try:
                self._collect_owner_garbage(owner_id, now)
            except (HostCapabilityError, OSError, TimeoutError):
                # Keep inaccessible owners' blobs intact for a later retry,
                # without blocking startup or cleanup for unrelated owners.
                continue

    def _collect_owner_garbage(self, owner_id, now):
        with skill_projection_read_lock(self.storage_factory(owner_id)), self.repository.sessions.begin() as session:
            # Clear columns in SQL: retained idempotency history never causes
            # unbounded blob hydration. Owner guard serializes new references.
            live_operation = exists(select(SkillOperationRow.operation_id).where(SkillOperationRow.operation_id == SkillProposalRow.operation_id, SkillOperationRow.publication.in_(("PREPARED", "NEEDS_REPAIR"))))
            live_scan = exists(select(SkillScanAttemptRow.token).where(SkillScanAttemptRow.subject == literal("check:") + SkillProposalRow.proposal_id, SkillScanAttemptRow.lease_until > now))
            eligible = (SkillProposalRow.owner_id == owner_id, ~live_operation, ~live_scan)
            session.execute(update(SkillProposalRow).where(*eligible, or_(SkillProposalRow.expires_at <= now, SkillProposalRow.state.in_(("DISCARDED", "PUBLISHED")))).values(package_blob=None, candidate_blob=None))
            session.execute(update(SkillProposalRow).where(*eligible, SkillProposalRow.expires_at <= now, SkillProposalRow.state == "PENDING").values(state="EXPIRED"))
            session.execute(
                update(SkillOperationRow)
                .where(SkillOperationRow.owner_id == owner_id, SkillOperationRow.rollback_expires_at <= now, SkillOperationRow.publication.not_in(("PREPARED", "NEEDS_REPAIR")))
                .values(before_blob=None, after_blob=None)
            )
            session.execute(delete(SkillScanAttemptRow).where(SkillScanAttemptRow.owner_id == owner_id, SkillScanAttemptRow.started_at < now - 3600, SkillScanAttemptRow.lease_until <= now))
