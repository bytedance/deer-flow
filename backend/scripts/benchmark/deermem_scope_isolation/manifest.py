from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANARY_PATTERN = re.compile(r"DFMEM_[A-Z0-9_]+")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageSpec(StrictModel):
    role: Literal["human", "ai"]
    content: str


class FactSpec(StrictModel):
    content: str
    category: str = "context"
    confidence: float = 0.99


class CorrectionExpectation(StrictModel):
    old_canary: str
    new_canary: str


class SemanticExpectation(StrictModel):
    persist_canaries: list[str]
    reject_canaries: list[str]
    corrections: list[CorrectionExpectation] = Field(default_factory=list)


class SemanticCase(StrictModel):
    id: str
    scenario: Literal[
        "durable_preference",
        "task_constraint",
        "project_constraint",
        "transactional_authority",
        "mixed_scope",
        "user_correction",
    ]
    user_id: str
    agent_name: str | None
    messages: list[MessageSpec]
    seed_facts: list[FactSpec] = Field(default_factory=list)
    expected: SemanticExpectation
    replay_response: dict[str, object]

    @field_validator("messages")
    @classmethod
    def require_conversation_pair(cls, value: list[MessageSpec]) -> list[MessageSpec]:
        roles = {message.role for message in value}
        if roles != {"human", "ai"}:
            raise ValueError("each semantic case must contain human and ai messages")
        return value


class IdentityProbe(StrictModel):
    id: str
    user_id: str
    agent_name: str | None
    dimension: Literal["same_scope", "cross_agent", "cross_user"]
    expected_visible: bool


class IdentityCase(StrictModel):
    id: str
    source_semantic_case_id: str
    probes: list[IdentityProbe]


class ScopeIsolationManifest(StrictModel):
    schema_version: Literal[1]
    protocol_id: Literal["deermem-scope-isolation-v1"]
    production_prompt_sha256: str
    semantic_cases: list[SemanticCase]
    identity_cases: list[IdentityCase]

    @model_validator(mode="after")
    def validate_protocol(self) -> ScopeIsolationManifest:
        semantic_ids = [case.id for case in self.semantic_cases]
        identity_ids = [case.id for case in self.identity_cases]
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("semantic case IDs must be unique")
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("identity case IDs must be unique")
        if any(case.source_semantic_case_id not in semantic_ids for case in self.identity_cases):
            raise ValueError("identity cases must reference a semantic case")
        declarations = _declared_canaries(self)
        if len(declarations) != len(set(declarations)):
            raise ValueError("declared canaries must be unique")
        if any(CANARY_PATTERN.fullmatch(canary) is None for canary in declarations):
            raise ValueError("every declared canary must use the DFMEM_ synthetic format")
        declared = set(declarations)
        referenced = set(CANARY_PATTERN.findall(json.dumps(self.model_dump(mode="json"), sort_keys=True)))
        if referenced != declared:
            raise ValueError("every canary reference must have exactly one declaration")
        for case in self.semantic_cases:
            seeded = {fact.content for fact in case.seed_facts}
            for correction in case.expected.corrections:
                if correction.old_canary not in seeded:
                    raise ValueError("a correction's old canary must be seeded in the same case")
                if correction.old_canary == correction.new_canary:
                    raise ValueError("a correction must replace the old canary with a different value")
        for identity_case in self.identity_cases:
            probe_ids = [probe.id for probe in identity_case.probes]
            if len(probe_ids) != len(set(probe_ids)):
                raise ValueError("identity probe IDs must be unique within a case")
        return self


def load_manifest(path: Path) -> ScopeIsolationManifest:
    return ScopeIsolationManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _declared_canaries(manifest: ScopeIsolationManifest) -> list[str]:
    declared: list[str] = []
    for case in manifest.semantic_cases:
        declared.extend(fact.content for fact in case.seed_facts)
        declared.extend(case.expected.persist_canaries)
        declared.extend(case.expected.reject_canaries)
        declared.extend(correction.new_canary for correction in case.expected.corrections)
    return declared


def all_canaries(manifest: ScopeIsolationManifest) -> list[str]:
    return _declared_canaries(manifest)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_production_contract(manifest: ScopeIsolationManifest, prompt_path: Path) -> None:
    actual = sha256_file(prompt_path)
    if actual != manifest.production_prompt_sha256:
        raise ValueError(f"production memory prompt changed; review the protocol and update production_prompt_sha256 (expected {manifest.production_prompt_sha256}, got {actual})")
