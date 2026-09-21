"""Durable publication through the source-bound host contract."""

import asyncio
import importlib.util
from dataclasses import asdict, dataclass
from types import SimpleNamespace

import pytest
import pytest_asyncio
from deerflow_extension_api.completed_run_evidence import CompletedRunSnapshot
from deerflow_extension_api.host_capabilities import HostCapabilityError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from deerflow.config.paths import Paths
from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader
from deerflow.extensions.host_access import BoundHostAccess, HostAccess
from deerflow.persistence.base import Base
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunRow
from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOperationRow, SkillProposalRow
from deerflow.persistence.user.model import UserRow
from deerflow.skills.mutations.guard import SkillMutationRuntime, configure_mutation_runtime
from deerflow.skills.mutations.repository import SkillMutationRepository
from deerflow.skills.mutations.scanner import ScanVerdict
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

CONTENT = "---\nname: example\ndescription: Before\n---\nA\n"
NEW = CONTENT.replace("\nA\n", "\nB\n")


@pytest_asyncio.fixture
async def host(tmp_path, monkeypatch):
    assert importlib.util.find_spec("deerflow.skills.mutations.service") is not None, "bound mutation service is missing"
    from deerflow.skills.mutations.recovery import SkillMutationRecovery
    from deerflow.skills.mutations.service import HostSkillMutationService

    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    storage = UserScopedSkillStorage("owner", host_path=str(tmp_path / "skills"))
    root = storage.get_custom_skill_dir("example")
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(CONTENT, encoding="utf-8")
    (root / "help.bin").write_bytes(b"\x00\xff")
    engine = create_engine(f"sqlite:///{tmp_path / 'mutations.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserRow(id="owner", email="owner@example.test"))
        run = RunRow(run_id="run", thread_id="thread", user_id="owner", status="success", evidence_seal_state="sealed", evidence_agent_id="trainer", evidence_origin="interactive", evidence_retention_revision=0)
        session.add(run)
        session.flush()
        snap = CompletedRunSnapshot(
            snapshot_ref="source", run_id="run", thread_id="thread", owner_id="owner", agent_id="trainer", origin="interactive", status="success", seal_state="sealed", evidence_revision=HostCompletedRunEvidenceReader.revision_for_run(run)
        )
        session.add(CompletedRunSnapshotRow(snapshot_ref="source", run_id="run", scope_digest="scope", evidence_revision=snap.evidence_revision, retention_revision=0, snapshot_json=asdict(snap)))

    class Evidence:
        scope_digest = "scope"

        @staticmethod
        def revision_for_run(run):
            return HostCompletedRunEvidenceReader.revision_for_run(run)

        async def resolve_snapshot(self, ref):
            if ref != "source":
                raise HostCapabilityError("NOT_FOUND")
            return snap

    class Scanner:
        calls = 0
        policy = "policy-1"
        decision = "allow"

        def policy_version_sync(self):
            return self.policy

        async def policy_version(self):
            return self.policy

        async def scan(self, package, name):
            self.calls += 1
            await asyncio.sleep(0)
            return ScanVerdict(self.decision, "CHECK_PASSED", self.policy)

    binding = BoundHostAccess(
        "plugin",
        HostAccess.model_validate(
            {"evidence": {"owners": ["owner"]}, "skill_mutations": {"owners": ["owner"], "operations": ["stage", "check", "commit", "revert"], "trigger_agents": ["trainer"], "target_skills": ["example"], "topology": "single_host_local"}}
        ),
    )
    runtime = SkillMutationRuntime(SkillMutationRepository(sessions), owners=frozenset({"owner"}))
    configure_mutation_runtime(runtime)

    def factory(owner):
        return storage

    recovery = SkillMutationRecovery(runtime, factory, rebuild_views=lambda _: None)
    scanner = Scanner()
    service = HostSkillMutationService(binding, runtime=runtime, evidence=Evidence(), storage_factory=factory, scanner=scanner, recovery=recovery)
    yield SimpleNamespace(service=service, recovery=recovery, scanner=scanner, runtime=runtime, storage=storage, sessions=sessions, binding=binding, snapshot=snap)
    await service.close()
    configure_mutation_runtime(None)
    engine.dispose()


async def stage(host, *, key="stage-1", content=NEW):
    skill = await host.service.read_skill(source_ref="source", name="example")
    return await host.service.stage(source_refs=("source",), target_ref=skill.target_ref, expected_revision=skill.revision, content=content, idempotency_key=key)


async def publish(host):
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    operation = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-1")
    return proposal, operation


@pytest.mark.asyncio
async def test_bundle_is_exact_detached_and_stage_is_idempotent(host):
    proposal = await stage(host)
    repeated = await stage(host)
    assert repeated == proposal
    bundle = await host.service.read_proposal_bundle(proposal_id=proposal.proposal_id)
    assert {f.path: f.content for f in bundle.baseline} == {"SKILL.md": CONTENT.encode(), "help.bin": b"\x00\xff"}
    assert {f.path: f.content for f in bundle.candidate} == {"SKILL.md": NEW.encode(), "help.bin": b"\x00\xff"}
    assert host.storage.get_custom_skill_file("example").read_text() == CONTENT


@pytest.mark.asyncio
async def test_commit_is_durable_idempotent_and_revert_moves_forward(host):
    proposal, operation = await publish(host)
    assert operation.publication == "APPLIED"
    assert operation.views == "READY"
    assert host.storage.get_custom_skill_file("example").read_text() == NEW
    assert await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-1") == operation
    with pytest.raises(HostCapabilityError, match="PROPOSAL_ALREADY_COMMITTED"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="other-key")
    assert await host.service.find_operation(idempotency_key="other-key") is None
    reverted = await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="revert-1")
    assert reverted.publication == "APPLIED"
    assert reverted.after_revision.mutation_seq == operation.after_revision.mutation_seq + 1
    assert host.storage.get_custom_skill_file("example").read_text() == CONTENT


@pytest.mark.asyncio
async def test_source_deletion_prevents_commit_but_not_query_or_revert(host):
    proposal, operation = await publish(host)
    with host.sessions.begin() as session:
        session.delete(session.get(RunRow, "run"))
    assert (await host.service.get_proposal(proposal_id=proposal.proposal_id)).operation_id == operation.operation_id
    assert await host.service.get_operation(operation_id=operation.operation_id) == operation
    reverted = await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="revert-1")
    assert reverted.publication == "APPLIED"


@pytest.mark.asyncio
async def test_fresh_source_fence_and_stale_policy_fail_closed(host):
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    host.scanner.policy = "policy-2"
    with pytest.raises(HostCapabilityError, match="CHECK_REQUIRED"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-1")
    await host.service.check(proposal_id=proposal.proposal_id)
    with host.sessions.begin() as session:
        session.get(RunRow, "run").evidence_retention_revision += 1
    with pytest.raises(HostCapabilityError, match="SOURCE_STALE_OR_GONE"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-1")
    assert host.storage.get_custom_skill_file("example").read_text() == CONTENT


@pytest.mark.asyncio
async def test_commit_maps_malformed_assessment_to_contract_error(host):
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)

    @dataclass(frozen=True)
    class DriftedAssessment:
        evaluator: str
        evaluator_version: str

    for index, assessment in enumerate(({"evaluator": "plugin"}, DriftedAssessment("plugin", "1"))):
        with pytest.raises(HostCapabilityError, match="INVALID_ASSESSMENT"):
            await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key=f"bad-assessment-{index}", assessment_ref=assessment)


@pytest.mark.asyncio
async def test_commit_bounds_serialized_assessment_bytes(host):
    from deerflow_extension_api.skill_mutations import AssessmentRef

    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    assessment = AssessmentRef(proposal.candidate_hash, proposal.base_revision, "é" * 300, "é" * 300, "é" * 300)
    with pytest.raises(HostCapabilityError, match="INVALID_ASSESSMENT"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="oversized-assessment", assessment_ref=assessment)


@pytest.mark.asyncio
async def test_commit_persists_valid_assessment(host):
    from deerflow_extension_api.skill_mutations import AssessmentRef

    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    assessment = AssessmentRef(proposal.candidate_hash, proposal.base_revision, "skill-evolution", "1", "report-1")
    operation = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="assessed", assessment_ref=assessment)
    with host.sessions() as session:
        assert session.get(SkillOperationRow, operation.operation_id).assessment == asdict(assessment)


@pytest.mark.asyncio
async def test_no_change_has_persisted_result_without_version_increment(host):
    proposal = await stage(host, content=CONTENT)
    await host.service.check(proposal_id=proposal.proposal_id)
    op = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="same")
    assert op.publication == "NO_CHANGE"
    assert op.before_revision == op.after_revision == proposal.base_revision
    assert (await host.service.find_operation(idempotency_key="same")).operation_id == op.operation_id


@pytest.mark.asyncio
async def test_revert_refuses_even_caller_supplied_new_head(host):
    _, operation = await publish(host)
    host.storage.get_custom_skill_file("example").write_text(NEW + "manual", encoding="utf-8")
    current = host.runtime.read_revision(host.storage, "example")
    with pytest.raises(HostCapabilityError, match="REVISION_CONFLICT"):
        await host.service.revert(operation_id=operation.operation_id, expected_current_revision=current, idempotency_key="revert-1")


@pytest.mark.asyncio
async def test_check_reuses_valid_result_and_rejection_cannot_publish(host):
    proposal = await stage(host)
    host.scanner.decision = "reject"
    result = await host.service.check(proposal_id=proposal.proposal_id)
    assert await host.service.check(proposal_id=proposal.proposal_id) == result
    assert host.scanner.calls == 1
    with pytest.raises(HostCapabilityError, match="CHECK_REQUIRED"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-1")


@pytest.mark.asyncio
async def test_discard_and_expiry_do_not_destroy_idempotence(host):
    proposal = await stage(host)
    assert (await host.service.discard(proposal_id=proposal.proposal_id)).state == "DISCARDED"
    host.recovery.collect_garbage()
    assert (await stage(host)).proposal_id == proposal.proposal_id
    with pytest.raises(HostCapabilityError, match="PROPOSAL_UNAVAILABLE"):
        await host.service.read_proposal_bundle(proposal_id=proposal.proposal_id)


@pytest.mark.asyncio
async def test_view_failure_keeps_applied_publication(host):
    def fail(_):
        raise RuntimeError("view failure")

    host.recovery.rebuild_views = fail
    _, operation = await publish(host)
    assert (operation.publication, operation.views) == ("APPLIED", "ERROR")
    assert host.storage.get_custom_skill_file("example").read_text() == NEW


@pytest.mark.asyncio
async def test_idempotency_key_cannot_change_request(host):
    await stage(host)
    with pytest.raises(HostCapabilityError, match="IDEMPOTENCY_CONFLICT"):
        await stage(host, content=NEW + "different")


@pytest.mark.asyncio
async def test_pending_quota_is_durable(host):
    for number in range(20):
        await stage(host, key=f"stage-{number}")
    with pytest.raises(HostCapabilityError, match="QUOTA_EXCEEDED"):
        await stage(host, key="overflow")
    with host.sessions() as session:
        assert len(session.scalars(select(SkillProposalRow)).all()) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("disk,expected", [(CONTENT, "ABORTED"), (NEW, "APPLIED"), (NEW + "external", "NEEDS_REPAIR")])
async def test_recovery_classifies_disk_without_replaying(host, monkeypatch, disk, expected):
    def interrupted(*_):
        raise RuntimeError("simulated process exit after PREPARED")

    monkeypatch.setattr("deerflow.skills.mutations.service.publish_prepared", interrupted)
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    response = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="crash")
    assert response.publication == "PREPARED"
    operation = await host.service.find_operation(idempotency_key="crash")
    assert operation.publication == "PREPARED"
    host.storage.get_custom_skill_file("example").write_text(disk, encoding="utf-8")
    recovered = host.recovery.recover_operation(operation.operation_id)
    assert recovered.publication == expected
    assert host.storage.get_custom_skill_file("example").read_text() == disk
    assert host.recovery.recover_operation(operation.operation_id) == recovered
    if expected == "NEEDS_REPAIR":
        with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
            host.recovery.recover_owner("owner")
        host.recovery.recover_all()  # A broken owner must not take down startup.


@pytest.mark.asyncio
async def test_gc_keeps_live_recovery_blobs_and_terminal_metadata(host, monkeypatch):
    def interrupted(*_):
        raise RuntimeError("simulated exit")

    monkeypatch.setattr("deerflow.skills.mutations.service.publish_prepared", interrupted)
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    response = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="crash")
    assert response.publication == "PREPARED"
    operation = await host.service.find_operation(idempotency_key="crash")
    with host.sessions.begin() as session:
        session.get(SkillProposalRow, proposal.proposal_id).expires_at = 0
        session.get(SkillOperationRow, operation.operation_id).rollback_expires_at = 0
    host.recovery.collect_garbage()
    with host.sessions() as session:
        assert session.get(SkillOperationRow, operation.operation_id).before_blob
        assert session.get(SkillProposalRow, proposal.proposal_id).candidate_blob
    host.recovery.recover_operation(operation.operation_id)
    host.recovery.collect_garbage()
    with host.sessions() as session:
        row = session.get(SkillOperationRow, operation.operation_id)
        assert row.before_blob is row.after_blob is None
    assert (await host.service.find_operation(idempotency_key="crash")).publication == "ABORTED"


@pytest.mark.asyncio
async def test_concurrent_check_is_singleflight(host):
    proposal = await stage(host)
    first, second = await asyncio.gather(host.service.check(proposal_id=proposal.proposal_id), host.service.check(proposal_id=proposal.proposal_id))
    assert first == second
    assert host.scanner.calls == 1


@pytest.mark.asyncio
async def test_owner_quiesce_refuses_new_mutations_and_queries(host):
    proposal = await stage(host)
    host.recovery.quiesce_owner("owner")
    with pytest.raises(HostCapabilityError, match="NOT_FOUND_OR_FORBIDDEN"):
        await host.service.get_proposal(proposal_id=proposal.proposal_id)
    with pytest.raises(HostCapabilityError, match="NOT_FOUND_OR_FORBIDDEN"):
        await host.service.check(proposal_id=proposal.proposal_id)


@pytest.mark.asyncio
async def test_source_identity_change_invalidates_snapshot_even_when_new_agent_is_granted(host):
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    with host.sessions.begin() as session:
        session.get(RunRow, "run").evidence_origin = "scheduled"
    with pytest.raises(HostCapabilityError, match="SOURCE_STALE_OR_GONE"):
        await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="changed-identity")


@pytest.mark.asyncio
async def test_revert_scan_cost_has_persisted_quota(host):
    _, operation = await publish(host)
    host.scanner.decision = "reject"
    for index in range(19):
        with pytest.raises(HostCapabilityError, match="CHECK_REQUIRED"):
            await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key=f"reject-{index}")
    with pytest.raises(HostCapabilityError, match="QUOTA_EXCEEDED"):
        await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="overflow")


@pytest.mark.asyncio
async def test_recovery_does_not_claim_applied_when_durability_barrier_fails(host, monkeypatch):
    def interrupted(*_):
        raise RuntimeError("simulated exit")

    monkeypatch.setattr("deerflow.skills.mutations.service.publish_prepared", interrupted)
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    response = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="crash")
    assert response.publication == "PREPARED"
    operation = await host.service.find_operation(idempotency_key="crash")
    host.storage.get_custom_skill_file("example").write_text(NEW, encoding="utf-8")

    def failed_fsync(_):
        raise OSError("disk error")

    monkeypatch.setattr("deerflow.skills.mutations.publication.os.fsync", failed_fsync)
    assert host.recovery.recover_operation(operation.operation_id).publication == "PREPARED"


def test_replace_collision_does_not_remove_existing_file(host):
    from deerflow.skills.mutations.publication import replace_main

    root = host.storage.get_custom_skill_dir("example")
    temporary = root.parent / ".host-mutation-collision"
    temporary.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        replace_main(root, NEW.encode(), operation_id="collision")
    assert temporary.read_text() == "existing"


@pytest.mark.asyncio
async def test_publication_preserves_permissions(host):
    import stat

    main = host.storage.get_custom_skill_file("example")
    main.chmod(0o640)
    await publish(host)
    assert stat.S_IMODE(main.stat().st_mode) == 0o640


@pytest.mark.asyncio
async def test_managed_reader_lazily_recovers_accepted_publication(host, monkeypatch):
    def interrupted(*_):
        raise RuntimeError("simulated exit")

    monkeypatch.setattr("deerflow.skills.mutations.service.publish_prepared", interrupted)
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    operation = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="crash")
    host.storage.get_custom_skill_file("example").write_text(NEW, encoding="utf-8")
    assert host.storage.load_skills()
    assert host.recovery.get_operation(operation.operation_id).publication == "APPLIED"


@pytest.mark.asyncio
async def test_failed_legacy_write_after_publication_is_recoverable(host, monkeypatch):
    _, operation = await publish(host)

    def no_space(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr("deerflow.skills.storage.user_scoped_skill_storage.tempfile.NamedTemporaryFile", no_space)
    with pytest.raises(OSError, match="no space"):
        host.storage.write_custom_skill("example", "SKILL.md", NEW + "manual")

    with host.sessions() as session:
        asset = session.scalar(select(SkillAssetRow).where(SkillAssetRow.owner_id == "owner", SkillAssetRow.name == "example"))
        assert asset.mutating is True
        assert asset.operation_id == operation.operation_id

    assert host.storage.load_skills()
    with host.sessions() as session:
        asset = session.scalar(select(SkillAssetRow).where(SkillAssetRow.owner_id == "owner", SkillAssetRow.name == "example"))
        assert asset.mutating is False
        assert asset.operation_id is None
        assert asset.mutation_seq == operation.after_revision.mutation_seq + 1


@pytest.mark.asyncio
async def test_history_mirror_is_compact_and_deduplicated_by_operation(host):
    _, operation = await publish(host)
    host.recovery.recover_all()
    host.recovery.recover_all()
    mirrored = [entry for entry in host.storage.read_history("example") if entry.get("operation_id") == operation.operation_id]
    assert len(mirrored) == 1
    assert mirrored[0]["scope"] == "main-file-only"
    assert "prev_content" not in mirrored[0] and "new_content" not in mirrored[0]


@pytest.mark.asyncio
async def test_history_mirror_failure_does_not_change_publication(host, monkeypatch):
    import deerflow.skills.mutations.history as history

    def fail(*_):
        raise OSError("mirror unavailable")

    monkeypatch.setattr(history, "mirror_operations", fail)
    _, operation = await publish(host)
    assert (operation.publication, operation.views) == ("APPLIED", "READY")


@pytest.mark.asyncio
async def test_admin_operation_pagination_uses_creation_order(host):
    _, committed = await publish(host)
    reverted = await host.service.revert(operation_id=committed.operation_id, expected_current_revision=committed.after_revision, idempotency_key="revert-order")
    newer_id, older_id = sorted((committed.operation_id, reverted.operation_id))
    with host.sessions.begin() as session:
        older = session.get(SkillOperationRow, older_id)
        newer = session.get(SkillOperationRow, newer_id)
        older.created_at, newer.created_at = 1.0, 2.0
        older.views = newer.views = "ERROR"

    first = host.recovery.list_operations(limit=1)
    assert [item.operation_id for item in first] == [older_id]
    second = host.recovery.list_operations(limit=2, after_id=older_id)
    assert [item.operation_id for item in second] == [newer_id]


@pytest.mark.asyncio
async def test_bound_identity_and_current_grants_are_required_for_queries(host):
    proposal, operation = await publish(host)
    original = host.service.binding
    host.service.binding = BoundHostAccess("different-plugin", original.access)
    for call in (host.service.get_proposal(proposal_id=proposal.proposal_id), host.service.get_operation(operation_id=operation.operation_id)):
        with pytest.raises(HostCapabilityError, match="NOT_FOUND_OR_FORBIDDEN"):
            await call
    host.service.binding = BoundHostAccess(original.plugin_id, HostAccess())
    with pytest.raises(HostCapabilityError, match="NOT_FOUND_OR_FORBIDDEN"):
        await host.service.get_operation(operation_id=operation.operation_id)


@pytest.mark.asyncio
async def test_close_drains_revert_scan_and_its_publication(host):
    _, operation = await publish(host)
    entered, release = asyncio.Event(), asyncio.Event()
    scan = host.scanner.scan

    async def blocked(*args):
        entered.set()
        await release.wait()
        return await scan(*args)

    host.scanner.scan = blocked
    reverting = asyncio.create_task(host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="close-revert"))
    await asyncio.wait_for(entered.wait(), 2)
    closing = asyncio.create_task(host.service.close())
    await asyncio.sleep(0)
    assert not closing.done()
    with pytest.raises(HostCapabilityError, match="UNAVAILABLE"):
        await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="new")
    release.set()
    await closing
    assert (await reverting).publication == "APPLIED"


@pytest.mark.asyncio
async def test_gc_does_not_load_retained_history_blobs(host):
    from sqlalchemy import event

    await publish(host)
    statements = []
    engine = host.sessions.kw["bind"]

    def observed(_conn, _cursor, statement, *_):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", observed)
    try:
        host.recovery.collect_garbage()
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert not any(statement.startswith("select") and "_blob" in statement for statement in statements)


def test_capabilities_describe_persisted_scan_budgets(host):
    capabilities = host.service.capabilities
    assert capabilities.max_concurrent_scans == 4
    assert capabilities.max_owner_plugin_concurrent_scans == 2
    assert capabilities.max_owner_plugin_scans_per_hour == 20


@pytest.mark.asyncio
async def test_nonbaseline_source_coverage_cannot_authorize_stage(host):
    from dataclasses import replace

    source = replace(host.snapshot, coverage="unknown-journal-v2")

    async def resolve(_):
        return source

    host.service.evidence.resolve_snapshot = resolve
    with host.sessions.begin() as session:
        session.get(CompletedRunSnapshotRow, "source").snapshot_json = asdict(source)
    with pytest.raises(HostCapabilityError, match="SOURCE_STALE_OR_GONE"):
        await stage(host)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,blob", [("before_blob", None), ("before_blob", b"[]"), ("after_blob", None), ("after_blob", b"invalid")])
async def test_recovery_quarantines_missing_or_corrupt_blobs(host, monkeypatch, field, blob):
    def interrupted(*_):
        raise RuntimeError("simulated exit")

    monkeypatch.setattr("deerflow.skills.mutations.service.publish_prepared", interrupted)
    proposal = await stage(host)
    await host.service.check(proposal_id=proposal.proposal_id)
    operation = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="crash")
    with host.sessions.begin() as session:
        setattr(session.get(SkillOperationRow, operation.operation_id), field, blob)
    host.storage.get_custom_skill_file("example").write_text(NEW, encoding="utf-8")
    recovered = host.recovery.recover_operation(operation.operation_id)
    assert recovered.publication == "NEEDS_REPAIR"
    assert recovered.error_code == "BLOB_INTEGRITY_ERROR"
    assert host.storage.get_custom_skill_file("example").read_text() == NEW


@pytest.mark.asyncio
async def test_revert_rejects_blob_with_wrong_digest(host):
    from deerflow.skills.mutations.codec import decode_package, encode_package

    _, operation = await publish(host)
    with host.sessions.begin() as session:
        row = session.get(SkillOperationRow, operation.operation_id)
        row.before_blob = encode_package(decode_package(row.before_blob).with_main(CONTENT + "tampered"))
    with pytest.raises(HostCapabilityError, match="ROLLBACK_UNAVAILABLE"):
        await host.service.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="bad-blob")


@pytest.mark.asyncio
async def test_aborted_later_attempt_preserves_previous_revert_head(host, monkeypatch):
    _, first = await publish(host)
    proposal = await stage(host, key="stage-later", content=NEW + "later")
    await host.service.check(proposal_id=proposal.proposal_id)
    import deerflow.skills.mutations.service as service_module

    publish_prepared = service_module.publish_prepared

    def interrupted(*_):
        raise RuntimeError("simulated exit")

    monkeypatch.setattr(service_module, "publish_prepared", interrupted)
    later = await host.service.commit(proposal_id=proposal.proposal_id, idempotency_key="commit-later")
    assert host.recovery.recover_operation(later.operation_id).publication == "ABORTED"
    monkeypatch.setattr(service_module, "publish_prepared", publish_prepared)
    reverted = await host.service.revert(operation_id=first.operation_id, expected_current_revision=first.after_revision, idempotency_key="revert-earlier")
    assert reverted.publication == "APPLIED"
    assert host.storage.get_custom_skill_file("example").read_text() == CONTENT


@pytest.mark.asyncio
async def test_superseded_view_points_to_replacing_generation(host):
    _, original = await publish(host)
    restored = await host.service.revert(operation_id=original.operation_id, expected_current_revision=original.after_revision, idempotency_key="revert")
    old = await host.service.get_operation(operation_id=original.operation_id)
    assert old.views == "SUPERSEDED"
    assert old.superseded_by_generation == restored.generation


@pytest.mark.asyncio
async def test_legacy_writer_immediately_supersedes_old_operation_view(host):
    _, operation = await publish(host)
    host.storage.write_custom_skill("example", "SKILL.md", NEW + "manual")
    old = await host.service.get_operation(operation_id=operation.operation_id)
    assert old.views == "SUPERSEDED"
    assert old.superseded_by_generation == host.runtime.repository.generation("owner")
