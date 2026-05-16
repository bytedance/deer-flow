"""Sandbox metadata for cross-process discovery and state persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SandboxInfo:
    """Persisted sandbox metadata that enables cross-process discovery.

    This dataclass holds all the information needed to reconnect to an
    existing sandbox from a different process (e.g., gateway vs langgraph,
    multiple workers, or across K8s pods with shared storage).
    """

    sandbox_id: str
    sandbox_url: str  # e.g. http://localhost:8080 or http://k3s:30001
    container_name: str | None = None  # Only for local container backend
    container_id: str | None = None  # Only for local container backend
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "sandbox_id": self.sandbox_id,
            "sandbox_url": self.sandbox_url,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SandboxInfo:
        return cls(
            sandbox_id=data["sandbox_id"],
            sandbox_url=data.get("sandbox_url", data.get("base_url", "")),
            container_name=data.get("container_name"),
            container_id=data.get("container_id"),
            created_at=data.get("created_at", time.time()),
        )
