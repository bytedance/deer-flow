"""Bound P0 host service: exact proposals, fail-closed checks and durable CAS."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict

from deerflow_extension_api.host_capabilities import HostCapabilityError
from deerflow_extension_api.skill_mutations import AssetRevision, BundleFile, MutationCapabilities, ProposalBundle, SkillRevisionView
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunRow
from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOperationRow, SkillOwnerRow, SkillProposalRow
from deerflow.persistence.user.model import UserRow
from deerflow.skills.mutations.assets import MAX_PACKAGE_BYTES, capture_package
from deerflow.skills.mutations.codec import check_view, decode_package, encode_package, fingerprint, operation_packages, operation_view, proposal_view
from deerflow.skills.mutations.publication import assert_temporary_absent, publish_prepared
from deerflow.skills.mutations.recovery import SkillMutationRecovery
from deerflow.skills.mutations.repository import revision
from deerflow.skills.mutations.scan_budget import release_scan, reserve_scan
from deerflow.skills.mutations.validation import MAX_MAIN_BYTES, validate_candidate
from deerflow.skills.mutations.workers import MutationWorkers
from deerflow.skills.projection import skill_projection_read_lock


class HostSkillMutationService:
    def __init__(self, binding, *, runtime, evidence, storage_factory, scanner, workers=None, recovery=None):
        self.binding, self.runtime, self.evidence = binding, runtime, evidence
        self.storage_factory, self.scanner = storage_factory, scanner
        self.repository = runtime.repository
        self._owns_workers = workers is None
        self.workers = workers or MutationWorkers()
        self.recovery = recovery or SkillMutationRecovery(runtime, storage_factory)
        self._checks = {}
        self._reverts = set()
        self._closed = False
        self._closing = False

    @property
    def capabilities(self):
        return MutationCapabilities(operations=self.binding.access.skill_mutations.operations)

    async def close(self):
        self._closing = True
        if self._checks or self._reverts:
            from deerflow.utils.file_io import await_drained

            await await_drained(asyncio.gather(*tuple(self._checks.values()), *tuple(self._reverts), return_exceptions=True))
        self._closed = True
        if self._owns_workers:
            await self.workers.close()

    def _authorize(self, owner_id, name, operation=None):
        grant = self.binding.access.skill_mutations
        allowed = self.binding.allows(operation, owner_id, name) if operation else bool(grant.operations) and owner_id in grant.owners and name in grant.target_skills
        if not allowed or owner_id not in self.runtime.owners:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        if os.name != "posix" or grant.topology != "single_host_local":
            raise HostCapabilityError("UNSUPPORTED_TOPOLOGY")

    def _owner_exists(self, session, owner_id):
        owner = session.get(SkillOwnerRow, owner_id)
        if session.get(UserRow, owner_id) is None or (owner is not None and owner.deleting):
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")

    def _row(self, session, model, identifier, operation=None):
        row = session.get(model, identifier)
        if row is None or row.plugin_id != self.binding.plugin_id:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        self._authorize(row.owner_id, row.name, operation)
        self._owner_exists(session, row.owner_id)
        return row

    async def _work(self, work):
        if self._closed:
            raise HostCapabilityError("UNAVAILABLE")

        def invoke(check):
            try:
                return work(check)
            except TimeoutError as exc:
                raise HostCapabilityError("BUSY", retry_after=1) from exc
            except (OperationalError, IntegrityError) as exc:
                raise HostCapabilityError("BUSY", retry_after=1) from exc
            except ValueError as exc:
                code = str(exc)
                raise HostCapabilityError(code if code in {"UNSUPPORTED_ASSET", "REVISION_CONFLICT", "QUOTA_EXCEEDED", "INVALID_FRONTMATTER", "FRONTMATTER_CHANGED"} else "INVALID_REQUEST") from exc

        return await self.workers.run(invoke)

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise HostCapabilityError("INVALID_REQUEST")

    @contextmanager
    def _guard(self, owner_id, check):
        storage = self.storage_factory(owner_id)
        with skill_projection_read_lock(storage, check=check):
            check()
            self.recovery.recover_locked(storage)
            self.repository.check_readable(owner_id)
            yield storage

    def _capture(self, storage, name):
        package = capture_package(storage.get_custom_skill_dir(name))
        _, enabled, exists = self.runtime.state(storage, name)
        row = self.repository.observe(storage.user_id, name, package.digest, enabled, exists=exists)
        if not exists:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        return row, package

    async def _source(self, source_ref):
        try:
            snap = await self.evidence.resolve_snapshot(source_ref)
        except HostCapabilityError as exc:
            raise HostCapabilityError("SOURCE_STALE_OR_GONE") from exc
        grant = self.binding.access.skill_mutations
        if snap.owner_id not in grant.owners or snap.agent_id not in grant.trigger_agents or snap.seal_state != "sealed" or snap.origin not in {"interactive", "scheduled"} or snap.coverage != "lead-journal-v1":
            raise HostCapabilityError("SOURCE_STALE_OR_GONE")
        return asdict(snap)

    def _sources_locked(self, session, sources, owner_id):
        """Retain run share locks until PREPARED commits; deletion takes UPDATE."""
        for source in sorted(sources, key=lambda item: item["run_id"]):
            stored = session.get(CompletedRunSnapshotRow, source["snapshot_ref"])
            run = session.scalar(select(RunRow).where(RunRow.run_id == source["run_id"]).with_for_update(read=True))
            if (
                stored is None
                or stored.scope_digest != self.evidence._scope
                or fingerprint(stored.snapshot_json) != fingerprint(source)
                or run is None
                or run.user_id != owner_id
                or run.thread_id != source["thread_id"]
                or run.operation_kind != "run"
                or run.evidence_seal_state != "sealed"
                or run.evidence_origin not in {"interactive", "scheduled"}
                or run.evidence_agent_id not in self.binding.access.skill_mutations.trigger_agents
                or run.evidence_origin != source["origin"]
                or run.evidence_agent_id != source["agent_id"]
                or source["owner_id"] != owner_id
                or source.get("coverage") != "lead-journal-v1"
                or run.evidence_retention_revision != source["retention_revision"]
                or HostCompletedRunEvidenceReader._revision(run) != source["evidence_revision"]
            ):
                raise HostCapabilityError("SOURCE_STALE_OR_GONE")

    @staticmethod
    def _begin_fence(session):
        if session.bind.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))

    async def read_skill(self, *, source_ref, name):
        source = await self._source(source_ref)
        self._authorize(source["owner_id"], name)

        def read(check):
            with self._guard(source["owner_id"], check) as storage:
                with self.repository.sessions() as session:
                    self._sources_locked(session, [source], source["owner_id"])
                asset, package = self._capture(storage, name)
                return SkillRevisionView(asset.target_ref, asset.owner_id, name, revision(asset), package.main_content, asset.enabled)

        return await self._work(read)

    async def stage(self, *, source_refs, target_ref, expected_revision, content, idempotency_key):
        self._key(idempotency_key)
        if not isinstance(source_refs, (tuple, list)) or not 1 <= len(source_refs) <= 20 or len(set(source_refs)) != len(source_refs):
            raise HostCapabilityError("QUOTA_EXCEEDED")
        if not isinstance(expected_revision, AssetRevision) or not isinstance(content, str):
            raise HostCapabilityError("INVALID_REQUEST")
        if len(content.encode("utf-8")) > MAX_MAIN_BYTES:
            raise HostCapabilityError("QUOTA_EXCEEDED")
        request = fingerprint([list(source_refs), target_ref, asdict(expected_revision), content])

        def existing(_):
            with self.repository.sessions() as session:
                row = session.scalar(select(SkillProposalRow).where(SkillProposalRow.plugin_id == self.binding.plugin_id, SkillProposalRow.idempotency_key == idempotency_key))
                if row is None:
                    return None
                self._row(session, SkillProposalRow, row.proposal_id, "stage")
                if row.request_hash != request:
                    raise HostCapabilityError("IDEMPOTENCY_CONFLICT")
                return proposal_view(row)

        cached = await self._work(existing)
        if cached is not None:
            return cached
        sources = [await self._source(ref) for ref in source_refs]
        owner_id = sources[0]["owner_id"]
        if any(source["owner_id"] != owner_id for source in sources):
            raise HostCapabilityError("SOURCE_STALE_OR_GONE")

        def create(check):
            with self.repository.sessions() as session:
                asset = session.get(SkillAssetRow, target_ref)
                if asset is None or asset.owner_id != owner_id:
                    raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
                name = asset.name
            self._authorize(owner_id, name, "stage")
            with self._guard(owner_id, check) as storage:
                cached = existing(check)
                if cached:
                    return cached
                asset, baseline = self._capture(storage, name)
                if asset.target_ref != target_ref or revision(asset) != expected_revision:
                    raise HostCapabilityError("REVISION_CONFLICT")
                if not asset.enabled:
                    raise HostCapabilityError("ASSET_DISABLED")
                validate_candidate(baseline.main_content, content, name)
                candidate = baseline.with_main(content)
                if sum(len(item.content) for item in candidate.files) > MAX_PACKAGE_BYTES:
                    raise HostCapabilityError("QUOTA_EXCEEDED")
                with self.repository.sessions.begin() as session:
                    self._begin_fence(session)
                    self.repository.owner(session, owner_id)
                    self._sources_locked(session, sources, owner_id)
                    count = session.scalar(
                        select(func.count())
                        .select_from(SkillProposalRow)
                        .where(SkillProposalRow.owner_id == owner_id, SkillProposalRow.plugin_id == self.binding.plugin_id, SkillProposalRow.state == "PENDING", SkillProposalRow.expires_at > time.time())
                    )
                    if count >= 20:
                        raise HostCapabilityError("QUOTA_EXCEEDED")
                    check()
                    row = SkillProposalRow(
                        proposal_id=uuid.uuid4().hex,
                        plugin_id=self.binding.plugin_id,
                        owner_id=owner_id,
                        target_ref=target_ref,
                        name=name,
                        base_revision=asdict(expected_revision),
                        sources=sources,
                        candidate_hash=candidate.digest,
                        package_blob=encode_package(baseline),
                        candidate_blob=encode_package(candidate),
                        state="PENDING",
                        expires_at=time.time() + 86400,
                        idempotency_key=idempotency_key,
                        request_hash=request,
                    )
                    session.add(row)
                    session.flush()
                    result = proposal_view(row)
                return result

        return await self._work(create)

    async def get_proposal(self, *, proposal_id):
        def read(_):
            with self.repository.sessions() as session:
                return proposal_view(self._row(session, SkillProposalRow, proposal_id))

        return await self._work(read)

    @staticmethod
    def _pending(row):
        if row.state != "PENDING" or row.expires_at <= time.time() or row.package_blob is None or row.candidate_blob is None:
            raise HostCapabilityError("PROPOSAL_UNAVAILABLE")

    async def read_proposal_bundle(self, *, proposal_id, max_bytes=33554432):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 33554432:
            raise HostCapabilityError("INVALID_REQUEST")

        def read(_):
            with self.repository.sessions() as session:
                row = self._row(session, SkillProposalRow, proposal_id)
                if row.package_blob is None or row.candidate_blob is None or row.state == "DISCARDED" or row.expires_at <= time.time():
                    raise HostCapabilityError("PROPOSAL_UNAVAILABLE")
                baseline, candidate = decode_package(row.package_blob), decode_package(row.candidate_blob)
                if sum(len(item.content) for package in (baseline, candidate) for item in package.files) > max_bytes:
                    raise HostCapabilityError("QUOTA_EXCEEDED")
                bundles = [tuple(BundleFile(item.path, item.content, item.digest, item.executable) for item in package.files) for package in (baseline, candidate)]
                return ProposalBundle(row.proposal_id, *bundles, AssetRevision(**row.base_revision), row.candidate_hash)

        return await self._work(read)

    async def discard(self, *, proposal_id):
        owner_id = (await self.get_proposal(proposal_id=proposal_id)).owner_id

        def discard(check):
            with skill_projection_read_lock(self.storage_factory(owner_id), check=check), self.repository.sessions.begin() as session:
                row = self._row(session, SkillProposalRow, proposal_id, "stage")
                if row.operation_id:
                    raise HostCapabilityError("ALREADY_PUBLISHED")
                row.state = "DISCARDED"
                return proposal_view(row)

        return await self._work(discard)

    async def check(self, *, proposal_id):
        if self._closed or self._closing:
            raise HostCapabilityError("UNAVAILABLE")
        task = self._checks.get(proposal_id)
        if task is None:
            task = asyncio.create_task(self._check(proposal_id))
            self._checks[proposal_id] = task

            def finished(done):
                self._checks.pop(proposal_id, None)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _check(self, proposal_id):
        proposal = await self.get_proposal(proposal_id=proposal_id)
        policy = await self.scanner.policy_version()
        token = uuid.uuid4().hex

        def reserve(check):
            with self._guard(proposal.owner_id, check) as storage:
                asset, _ = self._capture(storage, proposal.name)
                with self.repository.sessions.begin() as session:
                    row = self._row(session, SkillProposalRow, proposal_id, "check")
                    self._pending(row)
                    if revision(asset) != AssetRevision(**row.base_revision):
                        raise HostCapabilityError("REVISION_CONFLICT")
                    if not asset.enabled:
                        raise HostCapabilityError("ASSET_DISABLED")
                    now = time.time()
                    previous = row.check_result or {}
                    if previous.get("policy_version") == policy and previous.get("expires_at", 0) > now:
                        return check_view(row), None
                    if previous.get("lease_until", 0) > now:
                        raise HostCapabilityError("BUSY", retry_after=1)
                    reserve_scan(session, plugin_id=self.binding.plugin_id, owner_id=row.owner_id, subject="check:" + proposal_id, token=token)
                    row.check_result = {"token": token, "lease_until": now + 130}
                    return None, decode_package(row.candidate_blob)

        cached, package = await self._work(reserve)
        if cached:
            return cached
        try:
            async with asyncio.timeout(120):
                verdict = await self.scanner.scan(package, proposal.name)
        except (Exception, asyncio.CancelledError):
            from deerflow.skills.mutations.scanner import ScanVerdict

            verdict = ScanVerdict("unavailable", "SCANNER_UNAVAILABLE", policy)

        def finish(check):
            with skill_projection_read_lock(self.storage_factory(proposal.owner_id), check=check), self.repository.sessions.begin() as session:
                row = self._row(session, SkillProposalRow, proposal_id, "check")
                self._pending(row)
                if (row.check_result or {}).get("token") != token:
                    raise HostCapabilityError("CHECK_REQUIRED")
                row.check_result = {"decision": verdict.decision, "reason_code": verdict.reason_code, "policy_version": verdict.policy_version, "expires_at": time.time() + 900}
                return check_view(row)

        try:
            return await self._work(finish)
        finally:
            await self.workers.run(lambda _: release_scan(self.repository, token))

    def _existing_operation(self, session, method, key, request):
        row = session.scalar(select(SkillOperationRow).where(SkillOperationRow.plugin_id == self.binding.plugin_id, SkillOperationRow.method == method, SkillOperationRow.idempotency_key == key))
        if row is not None:
            self._row(session, SkillOperationRow, row.operation_id, method)
            if row.request_hash != request:
                raise HostCapabilityError("IDEMPOTENCY_CONFLICT")
        return row

    def _prepare(self, session, *, owner_id, asset, before, after, method, key, request, proposal=None, reverts=None, assessment=None):
        owner = self.repository.owner(session, owner_id)
        changed = before.digest != after.digest
        before_revision = revision(asset)
        after_revision = AssetRevision(before_revision.incarnation_id, before_revision.mutation_seq + int(changed), after.digest)
        operation = SkillOperationRow(
            operation_id=uuid.uuid4().hex,
            plugin_id=self.binding.plugin_id,
            owner_id=owner_id,
            target_ref=asset.target_ref,
            name=asset.name,
            method=method,
            idempotency_key=key,
            request_hash=request,
            proposal_id=proposal.proposal_id if proposal else None,
            reverts_operation_id=reverts,
            before_operation_id=asset.operation_id,
            before_revision=asdict(before_revision),
            after_revision=asdict(after_revision),
            before_blob=encode_package(before),
            after_blob=encode_package(after),
            generation=owner.generation + int(changed),
            publication="PREPARED" if changed else "NO_CHANGE",
            views="PENDING" if changed else "READY",
            created_at=time.time(),
            rollback_expires_at=time.time() + 2592000,
            assessment=assessment,
        )
        if changed:
            assert_temporary_absent(self.storage_factory(owner_id).get_custom_skill_dir(asset.name), operation.operation_id)
        session.add(operation)
        if changed:
            canonical = session.get(SkillAssetRow, asset.target_ref)
            canonical.operation_id = operation.operation_id
            canonical.mutating = True
        if proposal:
            proposal.operation_id, proposal.state = operation.operation_id, "PUBLISHED"
        session.flush()
        return operation.operation_id, changed, operation_view(operation)

    def _publish_result(self, storage, operation_id, changed, prepared):
        try:
            if changed:
                publish_prepared(self.repository, storage, operation_id)
            return self.recovery.get_operation(operation_id)
        except Exception:
            # Admission is already durable. Even an unavailable database must
            # return the accepted ID, never a refusal that invites republication.
            return prepared

    def _refresh_result(self, owner_id, operation):
        try:
            self.recovery.refresh_views(owner_id)
            return self.recovery.get_operation(operation.operation_id)
        except Exception:
            return operation

    async def commit(self, *, proposal_id, idempotency_key, assessment_ref=None):
        self._key(idempotency_key)
        assessment = asdict(assessment_ref) if assessment_ref else None
        if assessment is not None and (len(str(assessment).encode()) > 4096 or any(not isinstance(assessment[field], str) or not 1 <= len(assessment[field]) <= 512 for field in ("evaluator", "evaluator_version", "report_id"))):
            raise HostCapabilityError("INVALID_ASSESSMENT")
        request = fingerprint([proposal_id, assessment])
        proposal = await self.get_proposal(proposal_id=proposal_id)

        def commit(check):
            with skill_projection_read_lock(self.storage_factory(proposal.owner_id), check=check):
                storage = self.storage_factory(proposal.owner_id)
                self.recovery.recover_locked(storage)
                with self.repository.sessions() as session:
                    row = self._row(session, SkillProposalRow, proposal_id, "commit")
                    existing = self._existing_operation(session, "commit", idempotency_key, request)
                    if existing is not None:
                        return operation_view(existing)
                    if row.operation_id:
                        raise HostCapabilityError("PROPOSAL_ALREADY_COMMITTED")
                self.repository.check_readable(proposal.owner_id)
                asset, baseline = self._capture(storage, proposal.name)
                with self.repository.sessions.begin() as session:
                    self._begin_fence(session)
                    row = self._row(session, SkillProposalRow, proposal_id, "commit")
                    self._pending(row)
                    self.repository.owner(session, row.owner_id)
                    self._sources_locked(session, row.sources, row.owner_id)
                    if asset.target_ref != row.target_ref or revision(asset) != AssetRevision(**row.base_revision):
                        raise HostCapabilityError("REVISION_CONFLICT")
                    if not asset.enabled:
                        raise HostCapabilityError("ASSET_DISABLED")
                    checked = row.check_result or {}
                    try:
                        policy = self.scanner.policy_version_sync()
                    except Exception as exc:
                        raise HostCapabilityError("CHECK_REQUIRED") from exc
                    if checked.get("decision") != "allow" or checked.get("expires_at", 0) <= time.time() or checked.get("policy_version") != policy:
                        raise HostCapabilityError("CHECK_REQUIRED")
                    if assessment and (assessment["candidate_hash"] != row.candidate_hash or assessment["base_revision"] != row.base_revision):
                        raise HostCapabilityError("INVALID_ASSESSMENT")
                    candidate = decode_package(row.candidate_blob)
                    if baseline.digest != decode_package(row.package_blob).digest or candidate.digest != row.candidate_hash:
                        raise HostCapabilityError("REVISION_CONFLICT")
                    validate_candidate(baseline.main_content, candidate.main_content, row.name)
                    check()  # Last cancellation boundary: PREPARED is irrevocable admission.
                    operation_id, changed, prepared = self._prepare(session, owner_id=row.owner_id, asset=asset, before=baseline, after=candidate, method="commit", key=idempotency_key, request=request, proposal=row, assessment=assessment)
                result = self._publish_result(storage, operation_id, changed, prepared)
            return self._refresh_result(proposal.owner_id, result)

        return await self._work(commit)

    async def get_operation(self, *, operation_id):
        def read(_):
            with self.repository.sessions() as session:
                return operation_view(self._row(session, SkillOperationRow, operation_id))

        return await self._work(read)

    async def find_operation(self, *, idempotency_key, method="commit"):
        self._key(idempotency_key)
        if method not in {"commit", "revert"}:
            raise HostCapabilityError("INVALID_REQUEST")

        def read(_):
            with self.repository.sessions() as session:
                row = session.scalar(select(SkillOperationRow).where(SkillOperationRow.plugin_id == self.binding.plugin_id, SkillOperationRow.method == method, SkillOperationRow.idempotency_key == idempotency_key))
                return operation_view(self._row(session, SkillOperationRow, row.operation_id)) if row else None

        return await self._work(read)

    async def revert(self, *, operation_id, expected_current_revision, idempotency_key):
        if self._closing or self._closed:
            raise HostCapabilityError("UNAVAILABLE")
        task = asyncio.create_task(self._revert(operation_id=operation_id, expected_current_revision=expected_current_revision, idempotency_key=idempotency_key))
        self._reverts.add(task)
        task.add_done_callback(self._reverts.discard)
        return await task

    async def _revert(self, *, operation_id, expected_current_revision, idempotency_key):
        self._key(idempotency_key)
        request = fingerprint([operation_id, asdict(expected_current_revision)])

        def inspect(check):
            with self.repository.sessions() as session:
                original = self._row(session, SkillOperationRow, operation_id, "revert")
                existing = self._existing_operation(session, "revert", idempotency_key, request)
                if existing:
                    return operation_view(existing), None, None
                if original.publication != "APPLIED" or original.before_blob is None or original.rollback_expires_at <= time.time():
                    raise HostCapabilityError("ROLLBACK_UNAVAILABLE")
                try:
                    before, _ = operation_packages(original)
                except ValueError as exc:
                    raise HostCapabilityError("ROLLBACK_UNAVAILABLE") from exc
                return None, operation_view(original), before

        existing, original, restored = await self._work(inspect)
        if existing:
            return existing
        token = uuid.uuid4().hex

        def reserve(check):
            with self._guard(original.owner_id, check) as storage:
                asset, _ = self._capture(storage, original.name)
                if revision(asset) != expected_current_revision or revision(asset) != original.after_revision or asset.operation_id != operation_id:
                    raise HostCapabilityError("REVISION_CONFLICT")
                with self.repository.sessions.begin() as session:
                    reserve_scan(session, plugin_id=self.binding.plugin_id, owner_id=original.owner_id, subject="revert:" + operation_id, token=token)

        await self._work(reserve)
        try:
            async with asyncio.timeout(120):
                verdict = await self.scanner.scan(restored, original.name)
        except Exception as exc:
            raise HostCapabilityError("CHECK_REQUIRED") from exc
        finally:
            await self.workers.run(lambda _: release_scan(self.repository, token))
        if verdict.decision != "allow":
            raise HostCapabilityError("CHECK_REQUIRED")

        def revert(check):
            with self._guard(original.owner_id, check) as storage:
                asset, current = self._capture(storage, original.name)
                with self.repository.sessions.begin() as session:
                    row = self._row(session, SkillOperationRow, operation_id, "revert")
                    existing = self._existing_operation(session, "revert", idempotency_key, request)
                    if existing:
                        return operation_view(existing)
                    if row.before_blob is None or row.rollback_expires_at <= time.time():
                        raise HostCapabilityError("ROLLBACK_UNAVAILABLE")
                    if revision(asset) != expected_current_revision or revision(asset) != AssetRevision(**row.after_revision) or asset.operation_id != row.operation_id:
                        raise HostCapabilityError("REVISION_CONFLICT")
                    if not asset.enabled:
                        raise HostCapabilityError("ASSET_DISABLED")
                    if verdict.policy_version != self.scanner.policy_version_sync():
                        raise HostCapabilityError("CHECK_REQUIRED")
                    if restored.digest != decode_package(row.before_blob).digest:
                        raise HostCapabilityError("ROLLBACK_UNAVAILABLE")
                    check()
                    new_id, changed, prepared = self._prepare(session, owner_id=row.owner_id, asset=asset, before=current, after=restored, method="revert", key=idempotency_key, request=request, reverts=row.operation_id)
                result = self._publish_result(storage, new_id, changed, prepared)
            return self._refresh_result(original.owner_id, result)

        return await self._work(revert)
