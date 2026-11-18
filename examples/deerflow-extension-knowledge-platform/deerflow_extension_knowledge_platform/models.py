"""Extension-owned policy; executable configuration never comes from HTTP."""

import hashlib
import json
from typing import Any, Literal

from deerflow_extension_knowledge_management.contracts import Model, Operation, ProcessingOptions
from pydantic import Field, field_validator, model_validator

OPERATIONS = frozenset({"capabilities", "status", "upload", "url", "manual", "reprocess", "cancel"})
TOOLS = frozenset({"knowledge_search", "knowledge_entries_search", "entity_relations_search"})
Role = Literal["blocked", "viewer", "editor", "manager"]
RANK = {"blocked": 0, "viewer": 1, "editor": 2, "manager": 3}
Tool = Literal["knowledge_search", "knowledge_entries_search", "entity_relations_search"]


def resource_key(provider: str, connection: str, base: str) -> str:
    return "kp1_" + hashlib.sha256(json.dumps([provider, connection, base], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


class Resource(Model):
    base_id: str = Field(min_length=1, max_length=256)
    dataset_id: str = Field(min_length=1, max_length=256)
    operations: frozenset[Operation] = OPERATIONS
    tools: frozenset[Tool] = TOOLS


class Connection(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    provider_factory: str = "deerflow_extension_knowledge_management.weknora:WeKnoraManagement"
    provider_config: dict[str, Any] = Field(default_factory=dict, repr=False)
    resources: tuple[Resource, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique(self):
        if len({r.base_id for r in self.resources}) != len(self.resources):
            raise ValueError("Duplicate native base identity")
        return self


class Settings(Model):
    enabled: bool = Field(default=False, strict=True)
    storage_path: str
    connections: tuple[Connection, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique(self):
        if len({c.id for c in self.connections}) != len(self.connections):
            raise ValueError("Duplicate connection identity")
        return self


class Policy(Model):
    enabled: bool = Field(default=True, strict=True)
    operations: frozenset[Operation] | None = None
    tools: frozenset[Tool] | None = None
    default_tool: Tool | None = None
    processing: ProcessingOptions = Field(default_factory=ProcessingOptions)


class ConnectionPolicy(Policy):
    title: str = Field(default="", max_length=200)


class Space(Policy):
    title: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    resources: frozenset[str] | None = None
    members: dict[str, Role] = Field(default_factory=dict, max_length=200)

    @field_validator("members")
    @classmethod
    def exact_users(cls, members):
        if any(not user or user != user.strip() or len(user) > 256 for user in members):
            raise ValueError("Use exact bounded host user identities")
        return members


class PlatformPolicy(Model):
    defaults: Policy = Field(default_factory=Policy)
    connections: dict[str, ConnectionPolicy] = Field(default_factory=dict, max_length=20)
    spaces: dict[str, Space] = Field(default_factory=dict, max_length=500)


class Update(Model):
    revision: int = Field(ge=0, strict=True)
    policy: PlatformPolicy
