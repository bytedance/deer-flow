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
    container_id: str | None = None  # Runtime generation: container ID or Pod UID
    created_at: float = field(default_factory=time.time)
    # Ephemeral control-plane credentials reconstructed from local Docker
    # discovery. Intentionally excluded from to_dict() and repr so they cannot
    # leak through metadata persistence or routine lifecycle logs.
    request_headers: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    # Discovery-only lifecycle signal. A backend may report a running sandbox
    # whose persisted provisioning policy is incompatible with this process,
    # but it must not destroy that sandbox while merely enumerating it. The
    # provider consumes this flag and performs replacement only after obtaining
    # its local teardown reservation and cross-instance teardown lease.
    requires_replacement: bool = field(default=False, repr=False, compare=False)
    # None means an older remote provisioner did not attest its actual mode.
    lark_cli_broker: bool | None = False

    def to_dict(self) -> dict:
        return {
            "sandbox_id": self.sandbox_id,
            "sandbox_url": self.sandbox_url,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "created_at": self.created_at,
            "lark_cli_broker": self.lark_cli_broker,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SandboxInfo:
        return cls(
            sandbox_id=data["sandbox_id"],
            sandbox_url=data.get("sandbox_url", data.get("base_url", "")),
            container_name=data.get("container_name"),
            container_id=data.get("container_id"),
            created_at=data.get("created_at", time.time()),
            lark_cli_broker=data.get("lark_cli_broker", False),
        )
