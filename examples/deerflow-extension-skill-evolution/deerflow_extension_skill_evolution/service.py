"""Evidence-gated skill evolution orchestration over the host mutation contract.

This service is the demonstration the roadmap asks for: it drives the merged
``SkillMutationService`` (#5645) through *propose → evaluate → apply → rollback*
and refuses to commit a revision that carries no recorded, passing evidence.

It depends only on the public ``deerflow-extension-api`` contract — never on
harness internals — so it is the same code path a third-party integrator would
write. The host owns storage, security scanning, revision identity and
authorization; this service owns only the *policy* of "commit only when a
recorded regression case justifies the change".
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow_extension_api import (
    AssessmentRef,
    CompletedRunEvidenceReader,
    ExtensionRuntimeDeps,
    HostCapabilityError,
    SkillMutationService,
)

from deerflow_extension_skill_evolution.evaluator import (
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    Case,
    Evaluation,
    evaluate,
    load_cases_dir,
    report_id,
)


@dataclass
class ProposalRecord:
    """The example's own view of one in-flight proposal and its evaluation."""

    proposal_id: str
    name: str
    owner_id: str
    candidate_hash: str
    decision: str
    reasons: tuple[str, ...]
    report_id: str
    report: dict[str, Any]
    operation_id: str | None = None
    committed: bool = False


class SkillEvolutionError(RuntimeError):
    """A named, caller-facing failure distinct from host capability errors."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class EvolutionService:
    """Orchestrates evidence-gated skill revisions through the host contract.

    Lifecycle: ``start(deps)`` captures the host capability handles the Gateway
    injects (``skill_mutations`` + ``completed_run_evidence``); ``stop()`` drops
    them. Reports are held in memory for the life of the instance — the durable
    evidence is the ``assessment`` the host freezes onto each committed
    ``Operation``, not this cache.
    """

    def __init__(self, *, cases_dir: str | Path | None = None, cases: Sequence[Case] | None = None) -> None:
        self._mutations: SkillMutationService | None = None
        self._evidence: CompletedRunEvidenceReader | None = None
        self._cases_dir = Path(cases_dir) if cases_dir is not None else None
        self._static_cases: tuple[Case, ...] | None = tuple(cases) if cases is not None else None
        self._proposals: dict[str, ProposalRecord] = {}

    # -- ExtensionService protocol -----------------------------------------

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._mutations = deps.skill_mutations
        self._evidence = deps.completed_run_evidence
        if self._mutations is None:
            raise SkillEvolutionError(
                "NOT_GRANTED",
                "skill_mutations capability missing; grant host_access.skill_mutations in config.yaml plugins",
            )

    async def stop(self) -> None:
        self._mutations = None
        self._evidence = None

    # -- introspection ------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._mutations is not None

    def cases(self) -> tuple[Case, ...]:
        """Recorded regression cases: explicit set, else loaded from cases_dir."""
        if self._static_cases is not None:
            return self._static_cases
        if self._cases_dir is None:
            return ()
        return load_cases_dir(self._cases_dir)

    def get_proposal(self, proposal_id: str) -> ProposalRecord:
        record = self._proposals.get(proposal_id)
        if record is None:
            raise SkillEvolutionError("NO_SUCH_PROPOSAL", proposal_id)
        return record

    def list_proposals(self) -> list[ProposalRecord]:
        return list(self._proposals.values())

    # -- core orchestration -------------------------------------------------

    async def resolve_source(self, *, thread_id: str, run_id: str) -> str:
        """Turn a completed run into the sealed evidence ref ``stage`` requires."""
        if self._evidence is None:
            raise SkillEvolutionError("NO_EVIDENCE", "completed_run_evidence capability not granted")
        snapshot = await self._evidence.get_snapshot(thread_id=thread_id, run_id=run_id)
        if not snapshot.snapshot_ref:
            raise SkillEvolutionError("SOURCE_UNSEALED", f"run {run_id} has no sealed evidence snapshot")
        return snapshot.snapshot_ref

    async def propose(
        self,
        *,
        skill_name: str,
        candidate_content: str,
        source_ref: str,
        idempotency_key: str | None = None,
        cases: Sequence[Case] | None = None,
    ) -> ProposalRecord:
        """Stage a candidate, evaluate it against recorded cases, and record the verdict.

        Staging freezes both bundles host-side; evaluation runs entirely on the
        returned ``ProposalBundle`` bytes, so the verdict is about exactly the
        revision that would commit. Nothing is written to the live skill here.
        """
        mutations = self._require_mutations()
        recorded = tuple(cases) if cases is not None else self.cases()

        view = await mutations.read_skill(source_ref=source_ref, name=skill_name)
        proposal = await mutations.stage(
            source_refs=(source_ref,),
            target_ref=view.target_ref,
            expected_revision=view.revision,
            content=candidate_content,
            idempotency_key=idempotency_key or uuid.uuid4().hex,
        )
        bundle = await mutations.read_proposal_bundle(proposal_id=proposal.proposal_id)
        baseline = {item.path: item.content for item in bundle.baseline}
        candidate = {item.path: item.content for item in bundle.candidate}

        evaluation: Evaluation = evaluate(recorded, baseline, candidate)
        report = evaluation.report(candidate_hash=proposal.candidate_hash)
        rid = report_id(report)

        record = ProposalRecord(
            proposal_id=proposal.proposal_id,
            name=skill_name,
            owner_id=proposal.owner_id,
            candidate_hash=proposal.candidate_hash,
            decision=evaluation.decision,
            reasons=evaluation.reasons,
            report_id=rid,
            report=report,
        )
        self._proposals[proposal.proposal_id] = record

        # An unjustified or failed proposal must not linger pending; discard it
        # so the host's pending-proposal quota is not consumed by dead weight.
        if evaluation.decision != "justified":
            await mutations.discard(proposal_id=proposal.proposal_id)
        return record

    async def apply(self, *, proposal_id: str, idempotency_key: str | None = None) -> Any:
        """Commit a justified proposal with its evidence attached, after host check.

        Refuses unless the recorded evaluation was ``justified``. The host
        ``check`` (security scan / moderation) runs next and must allow; only
        then does ``commit`` land, carrying an ``AssessmentRef`` whose
        ``candidate_hash`` and ``base_revision`` the host re-validates against
        the proposal — the evidence is cryptographically bound to the change.
        """
        mutations = self._require_mutations()
        record = self.get_proposal(proposal_id)
        if record.committed:
            raise SkillEvolutionError("ALREADY_COMMITTED", proposal_id)
        if record.decision != "justified":
            raise SkillEvolutionError(
                "EVIDENCE_REQUIRED",
                f"proposal evaluated '{record.decision}': {'; '.join(record.reasons)}",
            )

        proposal = await mutations.get_proposal(proposal_id=proposal_id)
        check = await mutations.check(proposal_id=proposal_id)
        if check.decision != "allow":
            raise SkillEvolutionError("HOST_CHECK_DENIED", f"{check.reason_code} (decision={check.decision})")

        assessment = AssessmentRef(
            candidate_hash=proposal.candidate_hash,
            base_revision=proposal.base_revision,
            evaluator=EVALUATOR_NAME,
            evaluator_version=EVALUATOR_VERSION,
            report_id=record.report_id,
        )
        operation = await mutations.commit(
            proposal_id=proposal_id,
            idempotency_key=idempotency_key or uuid.uuid4().hex,
            assessment_ref=assessment,
        )
        record.operation_id = operation.operation_id
        record.committed = operation.publication in {"PREPARED", "READY", "NO_CHANGE"}
        return operation

    async def rollback(self, *, operation_id: str, idempotency_key: str | None = None) -> Any:
        """Revert a committed revision to its known-good predecessor.

        The revert is itself an audited ``Operation`` (history stays append-only),
        so a rollback is as traceable as the change it undoes.
        """
        mutations = self._require_mutations()
        operation = await mutations.get_operation(operation_id=operation_id)
        return await mutations.revert(
            operation_id=operation_id,
            expected_current_revision=operation.after_revision,
            idempotency_key=idempotency_key or uuid.uuid4().hex,
        )

    def _require_mutations(self) -> SkillMutationService:
        if self._mutations is None:
            raise SkillEvolutionError("NOT_STARTED", "service.start(deps) has not bound the host capability")
        return self._mutations


def build_router(service: EvolutionService):
    """Expose the closed loop as a small HTTP surface for the README walkthrough."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field

    router = APIRouter(prefix="/api/extension-skill-evolution", tags=["skill-evolution"])

    class ProposeRequest(BaseModel):
        model_config = {"extra": "forbid"}
        skill_name: str = Field(min_length=1, max_length=64)
        candidate_content: str = Field(min_length=1)
        thread_id: str = Field(min_length=1)
        run_id: str = Field(min_length=1)
        idempotency_key: str | None = None

    class ApplyRequest(BaseModel):
        model_config = {"extra": "forbid"}
        idempotency_key: str | None = None

    class RevertRequest(BaseModel):
        model_config = {"extra": "forbid"}
        idempotency_key: str | None = None

    def _guard(coro):
        """Translate named example/host errors into HTTP statuses."""

        async def run():
            try:
                return await coro
            except SkillEvolutionError as exc:
                status = 409 if exc.code in {"EVIDENCE_REQUIRED", "HOST_CHECK_DENIED", "ALREADY_COMMITTED"} else 400
                raise HTTPException(status_code=status, detail=str(exc)) from exc
            except HostCapabilityError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        return run()

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {"ready": service.ready, "evaluator": EVALUATOR_NAME, "evaluator_version": EVALUATOR_VERSION, "cases": len(service.cases())}

    @router.post("/proposals")
    async def create_proposal(body: ProposeRequest) -> dict[str, Any]:
        async def work():
            source_ref = await service.resolve_source(thread_id=body.thread_id, run_id=body.run_id)
            record = await service.propose(
                skill_name=body.skill_name,
                candidate_content=body.candidate_content,
                source_ref=source_ref,
                idempotency_key=body.idempotency_key,
            )
            return {
                "proposal_id": record.proposal_id,
                "decision": record.decision,
                "reasons": list(record.reasons),
                "report_id": record.report_id,
                "report": record.report,
            }

        return await _guard(work())

    @router.get("/proposals")
    async def list_proposals() -> dict[str, Any]:
        return {
            "proposals": [
                {
                    "proposal_id": record.proposal_id,
                    "name": record.name,
                    "decision": record.decision,
                    "committed": record.committed,
                    "operation_id": record.operation_id,
                    "report_id": record.report_id,
                }
                for record in service.list_proposals()
            ]
        }

    @router.get("/proposals/{proposal_id}")
    async def read_proposal(proposal_id: str) -> dict[str, Any]:
        try:
            record = service.get_proposal(proposal_id)
        except SkillEvolutionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"proposal_id": record.proposal_id, "decision": record.decision, "reasons": list(record.reasons), "committed": record.committed, "operation_id": record.operation_id, "report": record.report}

    @router.post("/proposals/{proposal_id}/apply")
    async def apply_proposal(proposal_id: str, body: ApplyRequest) -> dict[str, Any]:
        async def work():
            operation = await service.apply(proposal_id=proposal_id, idempotency_key=body.idempotency_key)
            return {
                "operation_id": operation.operation_id,
                "publication": operation.publication,
                "before_revision": operation.before_revision.content_digest,
                "after_revision": operation.after_revision.content_digest,
            }

        return await _guard(work())

    @router.post("/operations/{operation_id}/revert")
    async def revert_operation(operation_id: str, body: RevertRequest) -> dict[str, Any]:
        async def work():
            operation = await service.rollback(operation_id=operation_id, idempotency_key=body.idempotency_key)
            return {"operation_id": operation.operation_id, "publication": operation.publication, "reverts": operation.reverts_operation_id}

        return await _guard(work())

    return router
