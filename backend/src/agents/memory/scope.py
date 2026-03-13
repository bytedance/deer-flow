"""Memory scope parsing and normalization helpers."""

from dataclasses import dataclass


ALLOWED_NAMESPACE_TYPES = frozenset({"org_user"})
_INTERNAL_NAMESPACE_TYPES = frozenset({"global"})


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Canonical memory scope identity.

    When strict scope is disabled, missing values normalize to the global scope.
    """

    namespace_type: str
    namespace_id: str

    @classmethod
    def from_values(cls, namespace_type: str | None, namespace_id: str | None, *, strict: bool) -> "MemoryScope":
        normalized_type = namespace_type.strip() if isinstance(namespace_type, str) else ""
        normalized_id = namespace_id.strip() if isinstance(namespace_id, str) else ""

        if strict and (not normalized_type or not normalized_id):
            raise ValueError("namespace_type and namespace_id are required when memory.strict_scope=true")

        if normalized_type and normalized_type not in ALLOWED_NAMESPACE_TYPES and normalized_type not in _INTERNAL_NAMESPACE_TYPES:
            allowed = ", ".join(sorted(ALLOWED_NAMESPACE_TYPES))
            raise ValueError(f"namespace_type must be one of: {allowed}")

        return cls(
            namespace_type=normalized_type or "global",
            namespace_id=normalized_id or "global",
        )

    @property
    def key(self) -> str:
        return f"{self.namespace_type}:{self.namespace_id}"

    @property
    def is_global(self) -> bool:
        return self.namespace_type == "global" and self.namespace_id == "global"
