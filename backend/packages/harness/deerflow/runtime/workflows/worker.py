"""Worker identity helpers for durable workflow leases."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowWorkerIdentity:
    """Stable identity a workflow worker uses when claiming leases."""

    worker_id: str
    hostname: str
    process_id: int


@dataclass(frozen=True)
class WorkflowLeaseConfig:
    """Lease timing knobs for future workflow worker processes."""

    lease_seconds: int = 300
    renewal_interval_seconds: int = 60

    @classmethod
    def from_env(cls) -> "WorkflowLeaseConfig":
        return cls(
            lease_seconds=_positive_int_env("DEER_FLOW_WORKFLOW_LEASE_SECONDS", cls.lease_seconds),
            renewal_interval_seconds=_positive_int_env(
                "DEER_FLOW_WORKFLOW_RENEW_INTERVAL_SECONDS",
                cls.renewal_interval_seconds,
            ),
        )


def default_workflow_worker_identity(*, prefix: str = "workflow-worker") -> WorkflowWorkerIdentity:
    """Return the configured worker identity or derive one from host/process."""

    hostname = socket.gethostname()
    process_id = os.getpid()
    configured = os.getenv("DEER_FLOW_WORKFLOW_WORKER_ID")
    worker_id = configured.strip() if configured else ""
    if not worker_id:
        worker_id = f"{prefix}:{hostname}:{process_id}"
    return WorkflowWorkerIdentity(worker_id=worker_id, hostname=hostname, process_id=process_id)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
