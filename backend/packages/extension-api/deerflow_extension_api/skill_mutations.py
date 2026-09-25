"""Host-owned, conditional updates of existing custom skills; no learning policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AssetRevision:
    incarnation_id: str
    mutation_seq: int
    content_digest: str


@dataclass(frozen=True)
class SkillRevisionView:
    target_ref: str
    owner_id: str
    name: str
    revision: AssetRevision
    content: str
    enabled: bool


@dataclass(frozen=True)
class MutationCapabilities:
    operations: tuple[str, ...]
    protocol_version: str = "skill-mutations-v1"
    max_main_bytes: int = 131072
    max_package_bytes: int = 16777216
    max_package_files: int = 256
    max_sources: int = 20
    max_pending_proposals: int = 20
    max_model_scan_files: int = 32
    max_model_scan_bytes: int = 1048576
    max_model_scan_file_bytes: int = 131072
    max_concurrent_scans: int = 4
    max_owner_plugin_concurrent_scans: int = 2
    max_owner_plugin_scans_per_hour: int = 20
    check_timeout_seconds: int = 120
    proposal_ttl_seconds: int = 86400
    check_ttl_seconds: int = 900
    rollback_ttl_seconds: int = 2592000
    topology: str = "posix-single-host-local-filesystem"

    def __post_init__(self):
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    owner_id: str
    target_ref: str
    name: str
    base_revision: AssetRevision
    candidate_hash: str
    state: str
    expires_at: str
    source_refs: tuple[str, ...]
    operation_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True)
class BundleFile:
    path: str
    content: bytes
    sha256: str
    executable: bool

    def __post_init__(self):
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True)
class ProposalBundle:
    proposal_id: str
    baseline: tuple[BundleFile, ...]
    candidate: tuple[BundleFile, ...]
    base_revision: AssetRevision
    candidate_hash: str

    def __post_init__(self):
        object.__setattr__(self, "baseline", tuple(self.baseline))
        object.__setattr__(self, "candidate", tuple(self.candidate))


@dataclass(frozen=True)
class HostCheckResult:
    proposal_id: str
    decision: str
    candidate_hash: str
    base_revision: AssetRevision
    policy_version: str
    expires_at: str
    reason_code: str


@dataclass(frozen=True)
class AssessmentRef:
    candidate_hash: str
    base_revision: AssetRevision
    evaluator: str
    evaluator_version: str
    report_id: str


@dataclass(frozen=True)
class Operation:
    operation_id: str
    owner_id: str
    name: str
    publication: str
    views: str
    before_revision: AssetRevision
    after_revision: AssetRevision
    generation: int
    proposal_id: str | None = None
    reverts_operation_id: str | None = None
    error_code: str | None = None
    superseded_by_generation: int | None = None


class SkillMutationService(Protocol):
    @property
    def capabilities(self) -> MutationCapabilities:
        raise NotImplementedError

    async def read_skill(self, *, source_ref: str, name: str) -> SkillRevisionView:
        raise NotImplementedError

    async def stage(self, *, source_refs: tuple[str, ...], target_ref: str, expected_revision: AssetRevision, content: str, idempotency_key: str) -> Proposal:
        raise NotImplementedError

    async def get_proposal(self, *, proposal_id: str) -> Proposal:
        raise NotImplementedError

    async def read_proposal_bundle(self, *, proposal_id: str, max_bytes: int = 33554432) -> ProposalBundle:
        raise NotImplementedError

    async def check(self, *, proposal_id: str) -> HostCheckResult:
        raise NotImplementedError

    async def commit(self, *, proposal_id: str, idempotency_key: str, assessment_ref: AssessmentRef | None = None) -> Operation:
        raise NotImplementedError

    async def discard(self, *, proposal_id: str) -> Proposal:
        raise NotImplementedError

    async def revert(self, *, operation_id: str, expected_current_revision: AssetRevision, idempotency_key: str) -> Operation:
        raise NotImplementedError

    async def get_operation(self, *, operation_id: str) -> Operation:
        raise NotImplementedError

    async def find_operation(self, *, idempotency_key: str, method: str = "commit") -> Operation | None:
        raise NotImplementedError
