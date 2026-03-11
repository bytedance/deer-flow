"""Memory scope parsing and normalization helpers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Canonical memory scope identity.

    When strict scope is disabled, missing values normalize to the global scope.
    """

    workspace_type: str
    workspace_id: str

    @classmethod
    def from_values(cls, workspace_type: str | None, workspace_id: str | None, *, strict: bool) -> "MemoryScope":
        normalized_type = workspace_type.strip() if isinstance(workspace_type, str) else ""
        normalized_id = workspace_id.strip() if isinstance(workspace_id, str) else ""

        if strict and (not normalized_type or not normalized_id):
            raise ValueError("workspace_type and workspace_id are required when memory.strict_scope=true")

        return cls(
            workspace_type=normalized_type or "global",
            workspace_id=normalized_id or "global",
        )

    @property
    def key(self) -> str:
        return f"{self.workspace_type}:{self.workspace_id}"

    @property
    def is_global(self) -> bool:
        return self.workspace_type == "global" and self.workspace_id == "global"
