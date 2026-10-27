import asyncio
from types import SimpleNamespace

import pytest
from deerflow_extension_api import HostCapabilityError

from deerflow_extension_skill_evolution.mutations import ManagedEvolution
from deerflow_extension_skill_evolution.service import CapabilityHandle


def _revision(seq: int = 3, digest: str = "d" * 64, incarnation: str = "inc-1"):
    return SimpleNamespace(incarnation_id=incarnation, mutation_seq=seq, content_digest=digest)


def _skill(name="my-skill", owner="user-1", enabled=True):
    return SimpleNamespace(target_ref=f"ref-{name}", owner_id=owner, name=name, revision=_revision(), enabled=enabled, content="# old")


def _proposal(name="my-skill", owner="user-1"):
    return SimpleNamespace(
        proposal_id="prop-1",
        owner_id=owner,
        target_ref=f"ref-{name}",
        name=name,
        state="PENDING",
        expires_at="2026-01-01T00:00:00Z",
        candidate_hash="c" * 64,
    )


def _operation(name="my-skill", owner="user-1"):
    # Mirrors deerflow_extension_api.skill_mutations.Operation — the real host
    # return shape of SkillMutationService.commit()/revert().
    return SimpleNamespace(
        operation_id="op-1",
        owner_id=owner,
        name=name,
        publication="APPLIED",
        views="READY",
        before_revision=_revision(seq=3),
        after_revision=_revision(seq=4, digest="n" * 64),
        generation=2,
        proposal_id="prop-1",
        reverts_operation_id=None,
        error_code=None,
        superseded_by_generation=None,
    )


def _verdict(decision="allow", reason_code="ok"):
    return SimpleNamespace(decision=decision, reason_code=reason_code, policy_version="policy-1", expires_at="2026-01-01T00:00:00Z")


def _snapshot(owner="user-1", sealed=True, origin="interactive", coverage="lead-journal-v1", ref="snap-1"):
    return SimpleNamespace(
        snapshot_ref=ref if sealed else "",
        owner_id=owner,
        seal_state="sealed" if sealed else "partial",
        origin=origin,
        coverage=coverage,
    )


class FakeService:
    def __init__(self, *, skill=None, proposal=None, operation=None, verdict=None, capabilities=None, stage_error=None, commit_error=None, check_error=None):
        self.skill = skill or _skill()
        self.proposal = proposal or _proposal()
        self.operation = operation or _operation()
        self.verdict = verdict or _verdict()
        self.capabilities = capabilities or SimpleNamespace(max_main_bytes=131072)
        self.stage_error = stage_error
        self.commit_error = commit_error
        self.check_error = check_error
        self.calls = []

    async def read_skill(self, *, source_ref, name):
        self.calls.append(("read_skill", source_ref, name))
        return self.skill

    async def stage(self, *, source_refs, target_ref, expected_revision, content, idempotency_key):
        self.calls.append(("stage", source_refs, target_ref, expected_revision.mutation_seq, content, idempotency_key))
        if self.stage_error:
            raise self.stage_error
        return self.proposal

    async def get_proposal(self, *, proposal_id):
        self.calls.append(("get_proposal", proposal_id))
        return self.proposal

    async def check(self, *, proposal_id):
        self.calls.append(("check", proposal_id))
        if self.check_error:
            raise self.check_error
        return self.verdict

    async def commit(self, *, proposal_id, idempotency_key, assessment_ref=None):
        self.calls.append(("commit", proposal_id, idempotency_key))
        if self.commit_error:
            raise self.commit_error
        return self.operation

    async def discard(self, *, proposal_id):
        self.calls.append(("discard", proposal_id))
        return SimpleNamespace(**{**vars(self.proposal), "state": "DISCARDED"})

    async def get_operation(self, *, operation_id):
        self.calls.append(("get_operation", operation_id))
        return self.operation

    async def revert(self, *, operation_id, expected_current_revision, idempotency_key):
        self.calls.append(("revert", operation_id, expected_current_revision.mutation_seq, idempotency_key))
        return SimpleNamespace(**{**vars(self.operation), "reverts_operation_id": operation_id})


class FakeReader:
    def __init__(self, snapshots):
        # list of SimpleNamespace RunStatusView-like items, newest last.
        self._snapshots = snapshots
        self.calls = []

    async def list_changed_runs(self, *, cursor=None, limit=200):
        items = tuple(SimpleNamespace(thread_id=f"t-{index}", run_id=f"r-{index}") for index in range(len(self._snapshots)))
        return SimpleNamespace(items=items, next_cursor=None, has_more=False)

    async def get_snapshot(self, *, thread_id, run_id):
        self.calls.append((thread_id, run_id))
        index = int(run_id.split("-")[1])
        return self._snapshots[index]


def _wired(service=None, reader=None, recorder=None):
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    if service is not None:
        mutations.bind(service)
    if reader is not None:
        evidence.bind(reader)
    return ManagedEvolution(mutations, evidence, recorder=recorder)


def _stage_call(service):
    return [call for call in service.calls if call[0] == "stage"][-1]


def test_actions_report_unavailable_without_grants() -> None:
    evolution = _wired()
    for coroutine in (
        evolution.read(user_id="user-1", source=None, skill_name="my-skill"),
        evolution.stage(user_id="user-1", source=None, skill_name="my-skill", content="# new"),
        evolution.check(user_id="user-1", proposal_id="prop-1"),
        evolution.propose(user_id="user-1", source=None, skill_name="my-skill", content="# new"),
        evolution.publish(user_id="user-1", proposal_id="prop-1"),
        evolution.discard(user_id="user-1", proposal_id="prop-1"),
        evolution.rollback(user_id="user-1", operation_id="op-1"),
    ):
        assert asyncio.run(coroutine) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
    assert not evolution.available()


def test_evidence_only_grant_is_still_unavailable() -> None:
    evolution = _wired(reader=FakeReader([]))
    assert not evolution.available()
    assert asyncio.run(evolution.read(user_id="user-1", source=None, skill_name="my-skill")) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_read_uses_explicit_caller_owned_source() -> None:
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).read(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill"))
    assert result["ok"] is True
    assert result["skill"]["name"] == "my-skill"
    assert result["skill"]["revision"]["mutation_seq"] == 3
    assert ("read_skill", "snap-1", "my-skill") in service.calls


def test_read_rejects_source_owned_by_another_user() -> None:
    reader = FakeReader([_snapshot(owner="user-2")])
    result = asyncio.run(_wired(FakeService(), reader).read(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill"))
    assert result == {"ok": False, "error": {"code": "SOURCE_STALE_OR_GONE"}}


def test_read_rejects_unsealed_or_unexpected_coverage() -> None:
    for snapshot in (_snapshot(sealed=False), _snapshot(coverage="other"), _snapshot(origin="api")):
        reader = FakeReader([snapshot])
        result = asyncio.run(_wired(FakeService(), reader).read(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill"))
        assert result == {"ok": False, "error": {"code": "SOURCE_STALE_OR_GONE"}}


def test_auto_discovery_picks_newest_sealed_run_of_caller() -> None:
    snapshots = [
        _snapshot(owner="user-1", sealed=False, ref="snap-0"),
        _snapshot(owner="user-2", ref="snap-1"),
        _snapshot(owner="user-1", ref="snap-2"),
        _snapshot(owner="user-1", ref="snap-3"),
    ]
    service, reader = FakeService(), FakeReader(snapshots)
    result = asyncio.run(_wired(service, reader).read(user_id="user-1", source=None, skill_name="my-skill"))
    assert result["ok"] is True
    assert ("read_skill", "snap-3", "my-skill") in service.calls


def test_auto_discovery_fails_closed_without_a_usable_source() -> None:
    reader = FakeReader([_snapshot(owner="user-2"), _snapshot(owner="user-1", sealed=False)])
    result = asyncio.run(_wired(FakeService(), reader).read(user_id="user-1", source=None, skill_name="my-skill"))
    assert result == {"ok": False, "error": {"code": "SOURCE_STALE_OR_GONE"}}


def test_stage_stages_without_checking() -> None:
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).stage(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result["ok"] is True
    assert result["proposal"]["proposal_id"] == "prop-1"
    assert "check" not in result
    # The split pipeline step: stage runs, check does not.
    assert any(call[0] == "stage" for call in service.calls)
    assert not any(call[0] == "check" for call in service.calls)
    stage = _stage_call(service)
    assert stage[5].startswith("propose:")


def test_stage_enforces_content_bounds_from_capabilities() -> None:
    service = FakeService(capabilities=SimpleNamespace(max_main_bytes=8))
    reader = FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).stage(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="x" * 9))
    assert result == {"ok": False, "error": {"code": "QUOTA_EXCEEDED"}}
    assert not any(call[0] == "stage" for call in service.calls)


def test_check_runs_the_guarded_check_on_the_owned_proposal() -> None:
    service = FakeService()
    result = asyncio.run(_wired(service).check(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is True
    assert result["proposal"]["proposal_id"] == "prop-1"
    assert result["check"] == {"decision": "allow", "reason_code": "ok", "policy_version": "policy-1", "expires_at": "2026-01-01T00:00:00Z"}
    assert ("check", "prop-1") in service.calls


def test_check_rejects_a_foreign_proposal() -> None:
    service = FakeService(proposal=_proposal(owner="user-2"))
    result = asyncio.run(_wired(service).check(user_id="user-1", proposal_id="prop-1"))
    assert result == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
    assert not any(call[0] == "check" for call in service.calls)


def test_propose_stages_checks_and_returns_the_verdict() -> None:
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).propose(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result["ok"] is True
    assert result["proposal"]["proposal_id"] == "prop-1"
    assert result["check"]["decision"] == "allow"
    stage = _stage_call(service)
    assert stage[2] == "ref-my-skill"
    assert stage[3] == 3  # expected revision taken from the fresh read
    assert stage[4] == "# new"
    assert stage[5].startswith("propose:")


def test_propose_idempotency_key_is_deterministic() -> None:
    service, reader = FakeService(), FakeReader([_snapshot()])
    evolution = _wired(service, reader)
    source = {"thread_id": "t-0", "run_id": "r-0"}
    asyncio.run(evolution.propose(user_id="user-1", source=source, skill_name="my-skill", content="# new"))
    first = _stage_call(service)[5]
    asyncio.run(evolution.propose(user_id="user-1", source=source, skill_name="my-skill", content="# new"))
    assert _stage_call(service)[5] == first
    asyncio.run(evolution.propose(user_id="user-1", source=source, skill_name="my-skill", content="# different"))
    assert _stage_call(service)[5] != first


def test_propose_returns_denied_verdict_without_publishing() -> None:
    service = FakeService(verdict=_verdict(decision="deny", reason_code="SKILLSCAN-CRITICAL"))
    reader = FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).propose(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# bad"))
    assert result["ok"] is True
    assert result["check"] == {"decision": "deny", "reason_code": "SKILLSCAN-CRITICAL", "policy_version": "policy-1", "expires_at": "2026-01-01T00:00:00Z"}
    assert not any(call[0] == "commit" for call in service.calls)


def test_propose_enforces_content_bounds_from_capabilities() -> None:
    service = FakeService(capabilities=SimpleNamespace(max_main_bytes=8))
    reader = FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).propose(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="x" * 9))
    assert result == {"ok": False, "error": {"code": "QUOTA_EXCEEDED"}}
    assert not any(call[0] == "stage" for call in service.calls)


@pytest.mark.parametrize("skill_name", ["My-Skill", "my skill", "", "-lead", "a" * 65, 7, None])
def test_invalid_skill_names_are_rejected_before_any_host_call(skill_name) -> None:
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).read(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name=skill_name))
    assert result == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert service.calls == []


def test_publish_commits_with_a_deterministic_key() -> None:
    service = FakeService()
    result = asyncio.run(_wired(service).publish(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is True
    assert result["operation"]["operation_id"] == "op-1"
    assert result["operation"]["publication"] == "APPLIED"
    assert result["operation"]["views"] == "READY"
    assert result["operation"]["generation"] == 2
    assert result["operation"]["after_revision"]["mutation_seq"] == 4
    commit = next(call for call in service.calls if call[0] == "commit")
    assert commit[1] == "prop-1"
    key = commit[2]
    assert key.startswith("publish:") and len(key) == len("publish:") + 64
    import re as _re

    assert _re.fullmatch(r"publish:[0-9a-f]{64}", key)


def test_publish_rejects_a_foreign_proposal() -> None:
    service = FakeService(proposal=_proposal(owner="user-2"))
    result = asyncio.run(_wired(service).publish(user_id="user-1", proposal_id="prop-1"))
    assert result == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
    assert not any(call[0] == "commit" for call in service.calls)


def test_discard_marks_the_owned_proposal() -> None:
    service = FakeService()
    result = asyncio.run(_wired(service).discard(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is True
    assert result["proposal"]["state"] == "DISCARDED"


def test_rollback_reverts_with_the_recorded_after_revision() -> None:
    service = FakeService()
    result = asyncio.run(_wired(service).rollback(user_id="user-1", operation_id="op-1"))
    assert result["ok"] is True
    assert result["operation"]["reverts_operation_id"] == "op-1"
    revert = next(call for call in service.calls if call[0] == "revert")
    assert revert[1] == "op-1"
    assert revert[2] == 4  # after_revision of the recorded operation
    assert revert[3].startswith("rollback:")


def test_rollback_rejects_a_foreign_operation() -> None:
    service = FakeService(operation=_operation(owner="user-2"))
    result = asyncio.run(_wired(service).rollback(user_id="user-1", operation_id="op-1"))
    assert result == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
    assert not any(call[0] == "revert" for call in service.calls)


class FakeRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.records = []
        self.stages = []
        self.error = error

    def record_stage(self, *, owner, proposal_id, name, content):
        if self.error:
            raise self.error
        self.stages.append({"owner": owner, "proposal_id": proposal_id, "name": name, "content": content})

    def record_outcome(self, *, owner, name, method, operation_id, proposal_id=None, reverts_operation_id=None):
        if self.error:
            raise self.error
        self.records.append({"owner": owner, "name": name, "method": method, "operation_id": operation_id, "proposal_id": proposal_id, "reverts_operation_id": reverts_operation_id})


def test_publish_records_the_saved_skill_for_the_caller() -> None:
    recorder = FakeRecorder()
    result = asyncio.run(_wired(FakeService(), recorder=recorder).publish(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is True
    assert recorder.records == [{"owner": "user-1", "name": "my-skill", "method": "commit", "operation_id": "op-1", "proposal_id": "prop-1", "reverts_operation_id": None}]


def test_rollback_records_the_reverted_skill() -> None:
    recorder = FakeRecorder()
    result = asyncio.run(_wired(FakeService(), recorder=recorder).rollback(user_id="user-1", operation_id="op-1"))
    assert result["ok"] is True
    assert recorder.records == [{"owner": "user-1", "name": "my-skill", "method": "revert", "operation_id": "op-1", "proposal_id": None, "reverts_operation_id": "op-1"}]


def test_stage_snapshots_the_candidate_content() -> None:
    recorder = FakeRecorder()
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader, recorder=recorder).stage(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result["ok"] is True
    assert recorder.stages == [{"owner": "user-1", "proposal_id": "prop-1", "name": "my-skill", "content": "# new"}]


def test_propose_snapshots_the_candidate_content_too() -> None:
    recorder = FakeRecorder()
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader, recorder=recorder).propose(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result["ok"] is True
    assert recorder.stages == [{"owner": "user-1", "proposal_id": "prop-1", "name": "my-skill", "content": "# new"}]


def test_failed_operations_record_nothing() -> None:
    recorder = FakeRecorder()
    service = FakeService(commit_error=HostCapabilityError("BUSY"))
    result = asyncio.run(_wired(service, recorder=recorder).publish(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is False
    assert recorder.records == []


def test_recorder_failure_never_fails_a_succeeded_commit() -> None:
    recorder = FakeRecorder(error=RuntimeError("store broke"))
    result = asyncio.run(_wired(FakeService(), recorder=recorder).publish(user_id="user-1", proposal_id="prop-1"))
    assert result["ok"] is True
    assert result["operation"]["operation_id"] == "op-1"


def test_recorder_failure_never_fails_a_succeeded_stage() -> None:
    recorder = FakeRecorder(error=RuntimeError("store broke"))
    service, reader = FakeService(), FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader, recorder=recorder).stage(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result["ok"] is True
    assert result["proposal"]["proposal_id"] == "prop-1"


def test_host_capability_error_codes_and_retry_guidance_survive() -> None:
    service = FakeService(stage_error=HostCapabilityError("BUSY", retry_after=1))
    reader = FakeReader([_snapshot()])
    result = asyncio.run(_wired(service, reader).propose(user_id="user-1", source={"thread_id": "t-0", "run_id": "r-0"}, skill_name="my-skill", content="# new"))
    assert result == {"ok": False, "error": {"code": "BUSY", "retry_after": 1}}


def test_unexpected_exceptions_are_redacted() -> None:
    service = FakeService(commit_error=RuntimeError("/secret/host/path broke"))
    result = asyncio.run(_wired(service).publish(user_id="user-1", proposal_id="prop-1"))
    assert result == {"ok": False, "error": {"code": "INTERNAL"}}
    assert "/secret/host/path" not in repr(result)


def test_source_discovery_reaches_the_final_metadata_page():
    class PagedReader(FakeReader):
        async def list_changed_runs(self, *, cursor=None, limit=200):
            start = int(cursor or 0)
            end = min(start + 20, len(self._snapshots))
            return SimpleNamespace(items=tuple(SimpleNamespace(thread_id=f"t-{i}", run_id=f"r-{i}") for i in range(start, end)), next_cursor=str(end) if end < len(self._snapshots) else None, has_more=end < len(self._snapshots))

    snapshots = [_snapshot(ref=f"snap-{i}", owner="user-2") for i in range(60)] + [_snapshot(ref="newest-owned")]
    service, reader = FakeService(), PagedReader(snapshots)
    result = asyncio.run(_wired(service, reader).read(user_id="user-1", source=None, skill_name="my-skill"))
    assert result["ok"]
    assert ("read_skill", "newest-owned", "my-skill") in service.calls
