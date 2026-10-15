"""Storage contract for deployment-level managed subagents."""

from __future__ import annotations

import abc
import re
from collections.abc import Hashable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REQUIRED_DISALLOWED_TOOLS = frozenset({"task", "ask_clarification", "present_files"})
MANAGED_SUBAGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def normalize_managed_subagent_name(value: str) -> str:
    """Validate and normalize a managed subagent natural key."""
    if not isinstance(value, str) or not MANAGED_SUBAGENT_NAME_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid managed subagent name {value!r}. Must match {MANAGED_SUBAGENT_NAME_PATTERN.pattern}")
    return value.lower()


class ManagedSubagentDefinition(BaseModel):
    """Administrator-managed worker definition stored outside config.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str | None = None
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    tools: list[str] | None = None
    disallowed_tools: list[str] = Field(default_factory=lambda: sorted(REQUIRED_DISALLOWED_TOOLS))
    skills: list[str] | None = None
    model: str = "inherit"
    max_turns: int = Field(default=50, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_managed_subagent_name(value)

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("description", "system_prompt")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("tools", "skills")
    @classmethod
    def _validate_name_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            stripped = item.strip()
            if not stripped:
                raise ValueError("entries must not be blank")
            if stripped not in normalized:
                normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def _enforce_worker_tool_boundary(self) -> ManagedSubagentDefinition:
        denied = list(dict.fromkeys([*self.disallowed_tools, *sorted(REQUIRED_DISALLOWED_TOOLS)]))
        self.disallowed_tools = denied
        return self


class ManagedSubagentExistsError(Exception):
    """Raised when a managed definition already owns a name."""


class ManagedSubagentStore(abc.ABC):
    def cache_identity(self) -> Hashable:
        """Return the process-local identity of the backing catalog.

        Stateless store instances that point at the same backing data should
        override this so registry snapshots can be reused across instances.
        """
        return id(self)

    @abc.abstractmethod
    def get(self, name: str) -> ManagedSubagentDefinition:
        """Return one definition or raise ``FileNotFoundError``."""

    @abc.abstractmethod
    def list(self) -> list[ManagedSubagentDefinition]:
        """Return every managed definition, including disabled ones."""

    @abc.abstractmethod
    def create(self, definition: ManagedSubagentDefinition) -> None:
        """Create one definition or raise ``ManagedSubagentExistsError``."""

    @abc.abstractmethod
    def update(self, definition: ManagedSubagentDefinition) -> None:
        """Replace one existing definition or raise ``FileNotFoundError``."""

    @abc.abstractmethod
    def delete(self, name: str) -> bool:
        """Delete one definition and return whether it existed."""

    @abc.abstractmethod
    def signature(self) -> Hashable:
        """Return an opaque token suitable for cache invalidation."""
