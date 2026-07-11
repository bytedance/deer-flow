"""Run ownership configuration for multi-worker deployments."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunOwnershipConfig(BaseModel):
    """Per-run ownership and lease configuration.

    When ``heartbeat_enabled`` is True, each worker periodically renews
    the lease on its active runs. This is required for multi-worker
    deployments to detect orphaned runs from crashed workers.

    Clock-sync assumption
    ---------------------
    Reconciliation compares another worker's UTC ``lease_expires_at`` against
    this worker's ``datetime.now(UTC)``. The only skew budget between two
    workers' clocks is ``grace_seconds`` (plus whatever heartbeat slop is
    left in the current cycle — at most ``lease_seconds / 3``). Worst case,
    if the owning worker's heartbeat is just about to fire, a peer whose
    clock is more than ``grace_seconds`` ahead can mis-reclaim a still-live
    run as an orphan.

    Operators should ensure worker clocks are synchronised (NTP / chrony /
    systemd-timesyncd in K8s nodes) within a few seconds. If the
    environment cannot guarantee that, raise ``grace_seconds``; the cost is
    longer recovery latency for genuinely dead workers
    (``lease_seconds + grace_seconds`` from last heartbeat to reclaim).
    """

    lease_seconds: int = Field(
        default=30,
        ge=5,
        description="Seconds before a run lease expires if not renewed. Heartbeat renews every lease_seconds / 3.",
    )
    grace_seconds: int = Field(
        default=10,
        ge=0,
        description=(
            "Extra seconds past lease expiry before an orphaned run is reclaimed. Also the clock-skew budget between workers — raise it if worker clocks are not tightly synced; cost is slower recovery of genuinely dead-worker runs."
        ),
    )
    heartbeat_enabled: bool = Field(
        default=False,
        description="When True, the worker periodically renews leases on its active runs. Enable for multi-worker deployments (GATEWAY_WORKERS > 1).",
    )
