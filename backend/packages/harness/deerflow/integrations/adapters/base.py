"""Base adapter protocol and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthContext:
    """Authentication context for adapter calls."""

    tenant_id: str
    user_id: str | None = None
    token: str | None = None
    roles: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthStatus:
    """Adapter health status."""

    healthy: bool
    latency_ms: float | None = None
    message: str = ""
    checked_at: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IntegrationAdapter(Protocol):
    """Protocol for integration adapters."""

    @property
    def system_key(self) -> str:
        """Unique system identifier."""
        ...

    @property
    def system_type(self) -> str:
        """System type discriminator."""
        ...

    async def initialize(self) -> None:
        """Initialize adapter resources."""
        ...

    async def shutdown(self) -> None:
        """Shutdown adapter resources."""
        ...

    async def call(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> Any:
        """Execute a capability call.

        Args:
            capability_key: Capability identifier (e.g., 'monitoring.trend')
            query: Query object specific to the capability
            auth_context: Authentication context

        Returns:
            Canonical model result

        Raises:
            IntegrationError: On capability failure
        """
        ...

    async def health_check(self) -> HealthStatus:
        """Check adapter health.

        Returns:
            HealthStatus with connectivity and latency info
        """
        ...
