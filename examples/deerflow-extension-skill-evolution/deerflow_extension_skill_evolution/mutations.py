"""The guarded managed-mutation pipeline adapter (PR #5645 host APIs).

This module is where the extension actually *uses* the host's
``SkillMutationService`` backbone instead of only reporting it: it drives the
full ``read_skill`` → ``stage`` → ``check`` → ``commit``/``discard`` pipeline
plus forward-version ``revert``, against sealed completed-run evidence
obtained through the ``CompletedRunEvidenceReader``.

Identity model (the security boundary this adapter owns):

* The host service derives the acting owner from the *evidence source*, never
  from the caller, and enforces the operator's restart-bound
  ``host_access.skill_mutations`` owner/target allowlist on every call.
* The production Gateway injects the service-bound evidence reader with
  **global cross-user visibility** (it exists for trusted operator
  extensions). Without an extension-side check, any authenticated user of this
  plugin surface could stage proposals against an enrolled owner's sealed
  runs. This adapter therefore requires, for every operation, that the
  caller's principal id equals the owner of the evidence source (propose/read)
  or of the existing proposal/operation (publish/discard/rollback), and never
  accepts an owner id from the payload.

Everything that makes a mutation safe stays host-side: candidate validation,
static + model scanning (the ``check`` verdict gates ``commit``), CAS
publication, durable idempotency, crash recovery and rollback fencing. This
adapter adds no second security or storage truth — it sequences host calls and
maps ``HostCapabilityError`` codes to stable, redacted JSON results.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from deerflow_extension_api import HostCapabilityError

from .recent_runs import recent_changed_runs

logger = logging.getLogger(__name__)

# Mirrors the host's canonical skill-name rule (host_access.py::skill_names).
_SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_ID_BYTES = 128
_DEFAULT_MAX_MAIN_BYTES = 131072
_VALID_ORIGINS = frozenset({"interactive", "scheduled"})
_VALID_COVERAGE = "lead-journal-v1"
# Bounded lookback for automatic source discovery; explicit sources bypass it.
_DISCOVERY_LIMIT = 50


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _skill_view(view: Any) -> dict[str, Any]:
    return {
        "target_ref": view.target_ref,
        "owner_id": view.owner_id,
        "name": view.name,
        "revision": {
            "incarnation_id": view.revision.incarnation_id,
            "mutation_seq": view.revision.mutation_seq,
            "content_digest": view.revision.content_digest,
        },
        "enabled": view.enabled,
        "content": view.content,
    }


def _proposal_view(proposal: Any) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "owner_id": proposal.owner_id,
        "target_ref": proposal.target_ref,
        "name": proposal.name,
        "state": proposal.state,
        "expires_at": proposal.expires_at,
        "candidate_hash": proposal.candidate_hash,
    }


def _operation_view(operation: Any) -> dict[str, Any]:
    # Field-for-field the deerflow_extension_api.skill_mutations.Operation
    # contract; a view that invents fields (an earlier draft read
    # ``target_ref``/``method``, which the contract does not define) raises
    # AttributeError against the real host object and turns every successful
    # commit/revert into a redacted INTERNAL error.
    return {
        "operation_id": operation.operation_id,
        "owner_id": operation.owner_id,
        "name": operation.name,
        "publication": operation.publication,
        "views": operation.views,
        "generation": operation.generation,
        "proposal_id": operation.proposal_id,
        "reverts_operation_id": operation.reverts_operation_id,
        "error_code": operation.error_code,
        "after_revision": {
            "incarnation_id": operation.after_revision.incarnation_id,
            "mutation_seq": operation.after_revision.mutation_seq,
            "content_digest": operation.after_revision.content_digest,
        },
    }


def _error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, HostCapabilityError):
        error: dict[str, Any] = {"code": exc.code}
        if exc.retry_after is not None:
            error["retry_after"] = exc.retry_after
        return {"ok": False, "error": error}
    # Never leak exception text: it can carry host paths and internals.
    return {"ok": False, "error": {"code": "INTERNAL"}}


def _check_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_ID_BYTES or any(ord(c) < 32 for c in value):
        raise HostCapabilityError("INVALID_REQUEST")
    return value


def _check_skill_name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 64 or not _SKILL_NAME_RE.fullmatch(value):
        raise HostCapabilityError("INVALID_REQUEST")
    return value


def _verdict_view(verdict: Any) -> dict[str, Any]:
    return {
        "decision": verdict.decision,
        "reason_code": verdict.reason_code,
        "policy_version": verdict.policy_version,
        "expires_at": verdict.expires_at,
    }


def _usable_source(snapshot: Any, user_id: str) -> bool:
    return snapshot is not None and snapshot.owner_id == user_id and snapshot.seal_state == "sealed" and snapshot.origin in _VALID_ORIGINS and snapshot.coverage == _VALID_COVERAGE and bool(snapshot.snapshot_ref)


class ManagedEvolution:
    """Sequences host mutation calls; owns no security or storage truth.

    All public coroutines return plain dict results and never raise
    ``HostCapabilityError``: a stable ``{"ok": false, "error": {"code": ...}}``
    payload is the contract for the plugin actions layer.
    """

    def __init__(self, mutations: Any, evidence: Any, recorder: Any = None) -> None:
        self._mutations = mutations
        self._evidence = evidence
        self._recorder = recorder

    def _record_stage(self, user_id: str, proposal: Any, content: str) -> None:
        """Best-effort staged-content snapshot; never fails a succeeded stage."""
        if self._recorder is None:
            return
        try:
            self._recorder.record_stage(owner=user_id, proposal_id=proposal.proposal_id, name=proposal.name, content=content)
        except Exception:
            logger.warning("skill-evolution: failed to snapshot the staged content for %s", proposal.name, exc_info=True)

    def _record_outcome(self, user_id: str, operation: Any, method: str, *, proposal_id: str | None = None, reverts_operation_id: str | None = None) -> None:
        """Best-effort authorship record; never fails a succeeded host commit."""
        if self._recorder is None:
            return
        try:
            self._recorder.record_outcome(owner=user_id, name=operation.name, method=method, operation_id=operation.operation_id, proposal_id=proposal_id, reverts_operation_id=reverts_operation_id)
        except Exception:
            logger.warning("skill-evolution: failed to record the %s outcome for %s", method, operation.name, exc_info=True)

    def available(self) -> bool:
        return self._mutations.get() is not None and self._evidence.get() is not None

    async def _service(self) -> Any:
        service = self._mutations.get()
        if service is None:
            raise HostCapabilityError("UNAVAILABLE")
        return service

    async def _reader(self) -> Any:
        reader = self._evidence.get()
        if reader is None:
            raise HostCapabilityError("UNAVAILABLE")
        return reader

    def _max_main_bytes(self, service: Any) -> int:
        try:
            limit = int(service.capabilities.max_main_bytes)
            return limit if limit > 0 else _DEFAULT_MAX_MAIN_BYTES
        except Exception:
            return _DEFAULT_MAX_MAIN_BYTES

    async def _snapshot(self, user_id: str, source: Any) -> Any:
        """Resolve and validate one sealed evidence source owned by the caller.

        ``source`` is either ``None`` (auto-discovery: newest sealed run of the
        caller) or an explicit ``{"thread_id", "run_id"}`` mapping. The host
        re-validates the source against the operator grant on every mutation
        call; the caller-ownership check here is the extension-side boundary
        that keeps the globally visible reader from becoming a cross-user
        staging surface.
        """
        reader = await self._reader()
        if source is None:
            recent = await recent_changed_runs(reader, limit=_DISCOVERY_LIMIT)
            for status in reversed(recent):
                snapshot = await reader.get_snapshot(thread_id=status.thread_id, run_id=status.run_id)
                if self._usable_source(snapshot, user_id):
                    return snapshot
            raise HostCapabilityError("SOURCE_STALE_OR_GONE")
        if not isinstance(source, dict) or set(source) != {"thread_id", "run_id"}:
            raise HostCapabilityError("INVALID_REQUEST")
        thread_id = _check_id(source.get("thread_id"), label="thread_id")
        run_id = _check_id(source.get("run_id"), label="run_id")
        snapshot = await reader.get_snapshot(thread_id=thread_id, run_id=run_id)
        if not self._usable_source(snapshot, user_id):
            # Owner mismatches and missing snapshots are indistinguishable on
            # purpose: never confirm which sealed runs exist for other users.
            raise HostCapabilityError("SOURCE_STALE_OR_GONE")
        return snapshot

    @staticmethod
    def _usable_source(snapshot: Any, user_id: str) -> bool:
        return _usable_source(snapshot, user_id)

    async def read(self, *, user_id: str, source: Any, skill_name: Any) -> dict[str, Any]:
        try:
            service = await self._service()
            name = _check_skill_name(skill_name)
            snapshot = await self._snapshot(user_id, source)
            view = await service.read_skill(source_ref=snapshot.snapshot_ref, name=name)
            return {"ok": True, "skill": _skill_view(view)}
        except Exception as exc:
            return _error(exc)

    async def _stage_candidate(self, service: Any, *, user_id: str, source: Any, skill_name: Any, content: Any) -> Any:
        """Validate and stage one candidate against a caller-owned sealed source."""
        name = _check_skill_name(skill_name)
        if not isinstance(content, str) or not content:
            raise HostCapabilityError("INVALID_REQUEST")
        if len(content.encode("utf-8")) > self._max_main_bytes(service):
            raise HostCapabilityError("QUOTA_EXCEEDED")
        snapshot = await self._snapshot(user_id, source)
        current = await service.read_skill(source_ref=snapshot.snapshot_ref, name=name)
        idempotency_key = "propose:" + _digest(user_id, name, snapshot.snapshot_ref, content)
        return await service.stage(
            source_refs=(snapshot.snapshot_ref,),
            target_ref=current.target_ref,
            expected_revision=current.revision,
            content=content,
            idempotency_key=idempotency_key,
        )

    async def stage(self, *, user_id: str, source: Any, skill_name: Any, content: Any) -> dict[str, Any]:
        """Stage a candidate only — the single ``stage`` pipeline step.

        The host's guarded ``check`` is deliberately a separate call so the
        page can expose the operator-granted operations (config.yaml
        ``host_access.skill_mutations.operations``) as individual buttons.
        """
        try:
            service = await self._service()
            proposal = await self._stage_candidate(service, user_id=user_id, source=source, skill_name=skill_name, content=content)
            self._record_stage(user_id, proposal, content)
            return {"ok": True, "proposal": _proposal_view(proposal)}
        except Exception as exc:
            return _error(exc)

    async def check(self, *, user_id: str, proposal_id: Any) -> dict[str, Any]:
        """Run the host's guarded check on one owned staged proposal."""
        try:
            service = await self._service()
            proposal = await self._owned_proposal(service, user_id, proposal_id)
            verdict = await service.check(proposal_id=proposal.proposal_id)
            return {"ok": True, "proposal": _proposal_view(proposal), "check": _verdict_view(verdict)}
        except Exception as exc:
            return _error(exc)

    async def propose(self, *, user_id: str, source: Any, skill_name: Any, content: Any) -> dict[str, Any]:
        """Stage a candidate and run the host's guarded check in one call.

        Publication is deliberately a separate ``publish`` step: the check
        verdict (static + model scan) is returned to the caller, and only an
        explicit later ``commit`` — which the host re-gates on a fresh
        ``allow`` verdict — mutates the skill.
        """
        try:
            service = await self._service()
            proposal = await self._stage_candidate(service, user_id=user_id, source=source, skill_name=skill_name, content=content)
            self._record_stage(user_id, proposal, content)
            verdict = await service.check(proposal_id=proposal.proposal_id)
            return {"ok": True, "proposal": _proposal_view(proposal), "check": _verdict_view(verdict)}
        except Exception as exc:
            return _error(exc)

    async def _owned_proposal(self, service: Any, user_id: str, proposal_id: Any) -> Any:
        proposal = await service.get_proposal(proposal_id=_check_id(proposal_id, label="proposal_id"))
        if proposal.owner_id != user_id:
            raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
        return proposal

    async def publish(self, *, user_id: str, proposal_id: Any) -> dict[str, Any]:
        """Commit a checked proposal; deterministic keys make retries safe."""
        try:
            service = await self._service()
            proposal = await self._owned_proposal(service, user_id, proposal_id)
            operation = await service.commit(proposal_id=proposal.proposal_id, idempotency_key="publish:" + _digest(proposal.proposal_id))
            self._record_outcome(user_id, operation, "commit", proposal_id=proposal.proposal_id)
            return {"ok": True, "operation": _operation_view(operation)}
        except Exception as exc:
            return _error(exc)

    async def discard(self, *, user_id: str, proposal_id: Any) -> dict[str, Any]:
        try:
            service = await self._service()
            proposal = await self._owned_proposal(service, user_id, proposal_id)
            discarded = await service.discard(proposal_id=proposal.proposal_id)
            return {"ok": True, "proposal": _proposal_view(discarded)}
        except Exception as exc:
            return _error(exc)

    async def rollback(self, *, user_id: str, operation_id: Any) -> dict[str, Any]:
        """Revert one published operation to its recorded before-state."""
        try:
            service = await self._service()
            checked = _check_id(operation_id, label="operation_id")
            operation = await service.get_operation(operation_id=checked)
            if operation.owner_id != user_id:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            revert = await service.revert(
                operation_id=operation.operation_id,
                expected_current_revision=operation.after_revision,
                idempotency_key="rollback:" + _digest(operation.operation_id),
            )
            self._record_outcome(user_id, revert, "revert", reverts_operation_id=operation.operation_id)
            return {"ok": True, "operation": _operation_view(revert)}
        except Exception as exc:
            return _error(exc)
