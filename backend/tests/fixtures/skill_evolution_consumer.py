"""External-consumer contract fixture: imports only the standalone public API."""

from deerflow_extension_api import ExtensionRuntimeDeps


async def exercise(deps: ExtensionRuntimeDeps, *, thread_id: str, run_id: str, name: str):
    evidence, skills = deps.completed_run_evidence, deps.skill_mutations
    assert evidence is not None and skills is not None
    snapshot = await evidence.get_snapshot(thread_id=thread_id, run_id=run_id)
    assert snapshot.seal_state == "sealed"
    await evidence.read_events(snapshot_ref=snapshot.snapshot_ref)
    skill = await skills.read_skill(source_ref=snapshot.snapshot_ref, name=name)
    proposal = await skills.stage(source_refs=(snapshot.snapshot_ref,), target_ref=skill.target_ref, expected_revision=skill.revision, content=skill.content + "\nA fixed test improvement.\n", idempotency_key="fixture-stage")
    bundle = await skills.read_proposal_bundle(proposal_id=proposal.proposal_id)
    assert bundle.base_revision == skill.revision
    result = await skills.check(proposal_id=proposal.proposal_id)
    assert result.decision == "allow"
    operation = await skills.commit(proposal_id=proposal.proposal_id, idempotency_key="fixture-commit")
    assert operation.publication == "APPLIED"
    assert await skills.get_operation(operation_id=operation.operation_id) == operation
    assert await skills.find_operation(idempotency_key="fixture-commit") == operation
    reverted = await skills.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="fixture-revert")
    assert reverted.publication == "APPLIED"
    assert reverted.after_revision.mutation_seq > operation.after_revision.mutation_seq
    return operation, reverted
