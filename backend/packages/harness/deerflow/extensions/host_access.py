"""Restart-bound, host-owned grants; not a sandbox for trusted Python code."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owners: tuple[str, ...] = ()

    @field_validator("owners")
    @classmethod
    def exact_identifiers(cls, values):
        if len(values) > 1000 or len(set(values)) != len(values):
            raise ValueError("grant lists must be bounded and unique")
        if any(not value or len(value) > 128 or value.strip() != value or "*" in value or any(ord(c) < 32 for c in value) for value in values):
            raise ValueError("grant lists require exact nonempty identifiers, without wildcards")
        return values


class SkillMutationAccess(EvidenceAccess):
    operations: tuple[Literal["stage", "check", "commit", "revert"], ...] = ()
    trigger_agents: tuple[str, ...] = ()
    target_skills: tuple[str, ...] = ()
    topology: Literal["single_host_local"] | None = Field(
        default=None,
        description="Operator assertion: all writers upgraded; one POSIX host and shared local disk, not NFS/CSI. Required for mutation service.",
    )

    @field_validator("trigger_agents", "target_skills")
    @classmethod
    def exact_targets(cls, values):
        return cls.exact_identifiers(values)

    @field_validator("target_skills")
    @classmethod
    def skill_names(cls, values):
        if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64 for name in values):
            raise ValueError("target_skills must contain canonical skill names")
        return values


class HostAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: EvidenceAccess = Field(default_factory=EvidenceAccess)
    skill_mutations: SkillMutationAccess = Field(default_factory=SkillMutationAccess)

    @property
    def granted(self):
        return bool(self.evidence.owners or self.skill_mutations.owners or self.skill_mutations.operations)


@dataclass(frozen=True)
class BoundHostAccess:
    plugin_id: str
    access: HostAccess

    def allows(self, operation: str, owner_id: str, name: str) -> bool:
        grant = self.access.skill_mutations
        return operation in grant.operations and owner_id in grant.owners and name in grant.target_skills


def bind_host_access(specs) -> dict[str, BoundHostAccess]:
    """Source attribution is host registry data, never a plugin-supplied ID.

    Ungranted legacy duplicate entry points stay legal. Once a source is
    granted, all of its enabled registrations must identify one installation.
    Changing the name or entry point deliberately creates a new durable identity.
    """
    enabled = [spec for spec in specs if spec.enabled]
    names = Counter(spec.name for spec in enabled)
    entries = Counter(spec.use for spec in enabled)
    bindings = {}
    for spec in enabled:
        if not spec.host_access.granted:
            continue
        if not spec.name or names[spec.name] != 1 or entries[spec.use] != 1:
            raise ValueError("host_access requires a unique explicit plugin name and entry point")
        identity = json.dumps([spec.name, spec.use], ensure_ascii=True, separators=(",", ":"))
        bindings[spec.use] = BoundHostAccess(hashlib.sha256(identity.encode()).hexdigest(), spec.host_access)
    return bindings
