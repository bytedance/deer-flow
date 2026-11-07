"""End-to-end orchestration test against a fake host implementing only the public contract.

CI installs this package with the extension-api alone (no harness), so the fake
host here mirrors what ``HostSkillMutationService`` guarantees: content-addressed
revisions, baseline/candidate bundles, an allow-only check gate, commit that
re-validates the assessment against the proposal, and an append-only revert.
The point is that the example needs nothing beyond the contract.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

import pytest
from deerflow_extension_api import (
    AssessmentRef,
    AssetRevision,
    BundleFile,
    CompletedRunEventPage,
    CompletedRunSnapshot,
    EvidenceLimits,
    ExtensionRuntimeDeps,
    HostCapabilityError,
    HostCheckResult,
    MutationCapabilities,
    Operation,
    Proposal,
    ProposalBundle,
    SkillRevisionView,
)
from deerflow_extension_api.run_evidence import RunPage

from deerflow_extension_skill_evolution.evaluator import Case, Check
from deerflow_extension_skill_evolution.service import EvolutionService, SkillEvolutionError

SKILL = "example-skill"
OWNER = "owner"
BASE_MAIN = "---\nname: example-skill\ndescription: demo\n---\n\nRun `scripts/run.py --fmt json`.\n"
FIXED_MAIN = BASE_MAIN.replace("--fmt json", "--format json")
SCRIPT = "import json\nprint(json.dumps({'ok': True}))\n"

ARG_CASE = Case(
    case_id="converter-arg",
    description="SKILL.md must instruct --format json, not --fmt",
    checks=(Check("text_contains", path="SKILL.md", needle="--format json"),),
)


def _digest(files: dict[str, bytes]) -> str:
    canonical = json.dumps({k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _bundle(files: dict[str, bytes]) -> tuple[BundleFile, ...]:
    return tuple(BundleFile(path=p, content=c, sha256=hashlib.sha256(c).hexdigest(), executable=p.startswith("scripts/") and p.endswith(".py")) for p, c in sorted(files.items()))


@dataclass
class _OpRow:
    operation_id: str
    publication: str
    before_revision: AssetRevision
    after_revision: AssetRevision
    assessment: dict[str, Any] | None
    reverts_operation_id: str | None = None


class FakeMutationService:
    """A contract-faithful in-memory host for the mutation lifecycle."""

    def __init__(self, *, files: dict[str, bytes] | None = None, check_decision: str = "allow") -> None:
        self._files = files if files is not None else {"SKILL.md": BASE_MAIN.encode(), "scripts/run.py": SCRIPT.encode()}
        self._check_decision = check_decision
        self._seq = 0
        self._proposals: dict[str, Proposal] = {}
        self._bundles: dict[str, tuple[tuple[BundleFile, ...], tuple[BundleFile, ...]]] = {}
        self._operations: dict[str, _OpRow] = {}
        self._committed: set[str] = set()
        self._discarded: set[str] = set()

    @property
    def capabilities(self) -> MutationCapabilities:
        return MutationCapabilities(operations=("stage", "check", "commit", "revert"))

    def _current_revision(self) -> AssetRevision:
        return AssetRevision(incarnation_id="inc-1", mutation_seq=self._seq, content_digest=_digest(self._files))

    async def read_skill(self, *, source_ref: str, name: str) -> SkillRevisionView:
        if name != SKILL:
            raise HostCapabilityError("NOT_FOUND", name)
        rev = self._current_revision()
        return SkillRevisionView(target_ref=f"asset:{name}", owner_id=OWNER, name=name, revision=rev, content=self._files["SKILL.md"].decode(), enabled=True)

    async def stage(self, *, source_refs: tuple[str, ...], target_ref: str, expected_revision: AssetRevision, content: str, idempotency_key: str) -> Proposal:
        if expected_revision != self._current_revision():
            raise HostCapabilityError("REVISION_CONFLICT")
        candidate = {**self._files, "SKILL.md": content.encode()}
        pid = f"prop-{len(self._proposals) + 1}"
        base = self._current_revision()
        proposal = Proposal(
            proposal_id=pid,
            owner_id=OWNER,
            target_ref=target_ref,
            name=SKILL,
            base_revision=base,
            candidate_hash=_digest(candidate),
            state="STAGED",
            expires_at="2999-01-01T00:00:00Z",
            source_refs=tuple(source_refs),
        )
        self._proposals[pid] = proposal
        self._bundles[pid] = (_bundle(self._files), _bundle(candidate))
        return proposal

    async def get_proposal(self, *, proposal_id: str) -> Proposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise HostCapabilityError("NOT_FOUND", proposal_id)
        return proposal

    async def read_proposal_bundle(self, *, proposal_id: str, max_bytes: int = 33554432) -> ProposalBundle:
        proposal = await self.get_proposal(proposal_id=proposal_id)
        baseline, candidate = self._bundles[proposal_id]
        return ProposalBundle(proposal_id=proposal_id, baseline=baseline, candidate=candidate, base_revision=proposal.base_revision, candidate_hash=proposal.candidate_hash)

    async def discard(self, *, proposal_id: str) -> Proposal:
        await self.get_proposal(proposal_id=proposal_id)
        self._discarded.add(proposal_id)
        return replace(self._proposals[proposal_id], state="DISCARDED")

    async def check(self, *, proposal_id: str) -> HostCheckResult:
        proposal = await self.get_proposal(proposal_id=proposal_id)
        return HostCheckResult(
            proposal_id=proposal_id,
            decision=self._check_decision,
            candidate_hash=proposal.candidate_hash,
            base_revision=proposal.base_revision,
            policy_version="policy-1",
            expires_at="2999-01-01T00:00:00Z",
            reason_code="CHECK_PASSED" if self._check_decision == "allow" else "CHECK_BLOCKED",
        )

    async def commit(self, *, proposal_id: str, idempotency_key: str, assessment_ref: AssessmentRef | None = None) -> Operation:
        proposal = await self.get_proposal(proposal_id=proposal_id)
        if proposal_id in self._committed:
            raise HostCapabilityError("PROPOSAL_ALREADY_COMMITTED")
        if proposal_id in self._discarded:
            raise HostCapabilityError("PROPOSAL_DISCARDED")
        # The host re-validates the assessment against the exact proposal.
        if assessment_ref is not None and (assessment_ref.candidate_hash != proposal.candidate_hash or assessment_ref.base_revision != proposal.base_revision):
            raise HostCapabilityError("INVALID_ASSESSMENT")
        before = self._current_revision()
        # Recover the candidate bytes from the staged bundle.
        baseline_files, candidate_files = self._bundles[proposal_id]
        del baseline_files
        self._files = {f.path: f.content for f in candidate_files}
        changed = _digest(self._files) != before.content_digest
        self._seq += int(changed)
        after = AssetRevision(before.incarnation_id, before.mutation_seq + int(changed), _digest(self._files))
        op_id = f"op-{len(self._operations) + 1}"
        assessment = None
        if assessment_ref is not None:
            assessment = {"candidate_hash": assessment_ref.candidate_hash, "evaluator": assessment_ref.evaluator, "report_id": assessment_ref.report_id}
        # ``publication``, not ``views``: a committed change is APPLIED (or
        # NO_CHANGE when the candidate is identical to the baseline). The real
        # host never reports READY here -- that is a ``views`` state.
        self._operations[op_id] = _OpRow(operation_id=op_id, publication="APPLIED" if changed else "NO_CHANGE", before_revision=before, after_revision=after, assessment=assessment)
        self._committed.add(proposal_id)
        return self._operation_view(op_id)

    async def revert(self, *, operation_id: str, expected_current_revision: AssetRevision, idempotency_key: str) -> Operation:
        row = self._operations.get(operation_id)
        if row is None:
            raise HostCapabilityError("NOT_FOUND", operation_id)
        if expected_current_revision != self._current_revision():
            raise HostCapabilityError("REVISION_CONFLICT")
        # Revert to the revision that operation replaced.
        self._files = {f.path: f.content for f in self._bundles_of_operation(operation_id)}
        self._seq += 1
        after = AssetRevision("inc-1", self._seq, _digest(self._files))
        new_id = f"op-{len(self._operations) + 1}"
        self._operations[new_id] = _OpRow(operation_id=new_id, publication="APPLIED", before_revision=expected_current_revision, after_revision=after, assessment=None, reverts_operation_id=operation_id)
        return self._operation_view(new_id)

    def _bundles_of_operation(self, operation_id: str) -> tuple[BundleFile, ...]:
        # The pre-image of a commit is the baseline bundle it staged from.
        for pid, row in self._operations.items():
            if row.operation_id == operation_id:
                for staged_pid, proposal in self._proposals.items():
                    baseline, _candidate = self._bundles[staged_pid]
                    return baseline
        return _bundle(self._files)

    async def get_operation(self, *, operation_id: str) -> Operation:
        if operation_id not in self._operations:
            raise HostCapabilityError("NOT_FOUND", operation_id)
        return self._operation_view(operation_id)

    async def find_operation(self, *, idempotency_key: str, method: str = "commit") -> Operation | None:
        return None

    def _operation_view(self, op_id: str) -> Operation:
        row = self._operations[op_id]
        return Operation(
            operation_id=row.operation_id,
            owner_id=OWNER,
            name=SKILL,
            publication=row.publication,
            views="READY",
            before_revision=row.before_revision,
            after_revision=row.after_revision,
            generation=row.after_revision.mutation_seq,
            reverts_operation_id=row.reverts_operation_id,
        )


class FakeEvidence:
    """Minimal sealed-run evidence source keyed by (thread_id, run_id)."""

    def __init__(self, snapshot_ref: str = "source") -> None:
        self._ref = snapshot_ref

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        return RunPage(items=())

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        return CompletedRunSnapshot(snapshot_ref=self._ref, run_id=run_id, thread_id=thread_id, owner_id=OWNER, agent_id="lead_agent", origin="interactive", status="success", seal_state="sealed", coverage="lead-journal-v1")

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        return CompletedRunEventPage()


@pytest.fixture
def service(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "01-arg.json").write_text(
        json.dumps({"id": "converter-arg", "description": ARG_CASE.description, "checks": [{"kind": "text_contains", "path": "SKILL.md", "needle": "--format json"}]}),
        encoding="utf-8",
    )
    return EvolutionService(cases_dir=cases_dir)


async def _start(service: EvolutionService, mutations: FakeMutationService) -> None:
    deps = ExtensionRuntimeDeps(skill_mutations=mutations, completed_run_evidence=FakeEvidence())
    await service.start(deps)


async def test_full_loop_propose_apply_rollback(service):
    mutations = FakeMutationService()
    await _start(service, mutations)

    source = await service.resolve_source(thread_id="t", run_id="r")
    record = await service.propose(skill_name=SKILL, candidate_content=FIXED_MAIN, source_ref=source)

    assert record.decision == "justified"
    assert record.candidate_hash and len(record.report_id) == 64

    operation = await service.apply(proposal_id=record.proposal_id)
    assert operation.publication == "APPLIED"
    assert record.committed is True
    assert operation.before_revision.content_digest != operation.after_revision.content_digest
    # The committed operation carries the evaluator's assessment.
    assert mutations._operations[operation.operation_id].assessment["report_id"] == record.report_id

    revert = await service.rollback(operation_id=operation.operation_id)
    assert revert.reverts_operation_id == operation.operation_id
    assert mutations._files["SKILL.md"].decode() == BASE_MAIN  # back to known-good


async def test_apply_refuses_without_justifying_evidence(service):
    mutations = FakeMutationService()
    await _start(service, mutations)
    source = await service.resolve_source(thread_id="t", run_id="r")
    # A recorded case the baseline already satisfies: the change fixes nothing
    # on record, so the proposal is unjustified and must not commit.
    passing_on_both = Case(case_id="scripts-parse", description="bundled scripts parse", checks=(Check("scripts_parse"),))
    record = await service.propose(skill_name=SKILL, candidate_content=FIXED_MAIN, source_ref=source, cases=[passing_on_both])
    assert record.decision == "unjustified"
    assert record.proposal_id in mutations._discarded  # dead proposal cleaned up
    with pytest.raises(SkillEvolutionError) as exc:
        await service.apply(proposal_id=record.proposal_id)
    assert exc.value.code == "EVIDENCE_REQUIRED"


async def test_apply_refuses_when_candidate_still_fails(service):
    mutations = FakeMutationService()
    await _start(service, mutations)
    source = await service.resolve_source(thread_id="t", run_id="r")
    broken = FIXED_MAIN.replace("--format json", "--format xml")
    record = await service.propose(skill_name=SKILL, candidate_content=broken, source_ref=source)
    assert record.decision == "failed"
    with pytest.raises(SkillEvolutionError) as exc:
        await service.apply(proposal_id=record.proposal_id)
    assert exc.value.code == "EVIDENCE_REQUIRED"


async def test_apply_blocks_when_host_check_denies(service):
    mutations = FakeMutationService(check_decision="block")
    await _start(service, mutations)
    source = await service.resolve_source(thread_id="t", run_id="r")
    record = await service.propose(skill_name=SKILL, candidate_content=FIXED_MAIN, source_ref=source)
    assert record.decision == "justified"
    with pytest.raises(SkillEvolutionError) as exc:
        await service.apply(proposal_id=record.proposal_id)
    assert exc.value.code == "HOST_CHECK_DENIED"


async def test_apply_rejects_double_commit(service):
    mutations = FakeMutationService()
    await _start(service, mutations)
    source = await service.resolve_source(thread_id="t", run_id="r")
    record = await service.propose(skill_name=SKILL, candidate_content=FIXED_MAIN, source_ref=source)
    await service.apply(proposal_id=record.proposal_id)
    # A successful apply must flip the record's committed flag; otherwise the
    # ALREADY_COMMITTED guard below never fires against a real host.
    assert record.committed is True
    with pytest.raises(SkillEvolutionError) as exc:
        await service.apply(proposal_id=record.proposal_id)
    assert exc.value.code == "ALREADY_COMMITTED"


async def test_start_requires_the_grant(service):
    with pytest.raises(SkillEvolutionError) as exc:
        await service.start(ExtensionRuntimeDeps(skill_mutations=None))
    assert exc.value.code == "NOT_GRANTED"


async def test_propose_before_start_raises(service):
    with pytest.raises(SkillEvolutionError) as exc:
        await service.propose(skill_name=SKILL, candidate_content=FIXED_MAIN, source_ref="source")
    assert exc.value.code == "NOT_STARTED"


async def test_resolve_source_requires_evidence_grant(service):
    await service.start(ExtensionRuntimeDeps(skill_mutations=FakeMutationService(), completed_run_evidence=None))
    with pytest.raises(SkillEvolutionError) as exc:
        await service.resolve_source(thread_id="t", run_id="r")
    assert exc.value.code == "NO_EVIDENCE"
