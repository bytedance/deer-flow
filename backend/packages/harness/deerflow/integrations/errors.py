"""Unified error hierarchy for integration layer.

All adapters, services, and tools use these error types instead of
system-specific exceptions.
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for all integration errors."""

    def __init__(
        self,
        message: str,
        system_key: str | None = None,
        capability_key: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.system_key = system_key
        self.capability_key = capability_key

    def __str__(self) -> str:
        parts = [self.message]
        if self.system_key:
            parts.append(f"[system={self.system_key}]")
        if self.capability_key:
            parts.append(f"[capability={self.capability_key}]")
        return " ".join(parts)


class IntegrationConfigError(IntegrationError):
    """Configuration parsing or validation errors."""

    pass


class IntegrationAuthError(IntegrationError):
    """Authentication/authorization failures."""

    pass


class IntegrationTimeoutError(IntegrationError):
    """Request timeout exceeded."""

    pass


class IntegrationUnavailableError(IntegrationError):
    """System unreachable or health check failed."""

    pass


class IntegrationDataShapeError(IntegrationError):
    """Response structure mismatch."""

    pass


class EntityLinkNotFound(IntegrationError):
    """Cross-system entity mapping does not exist."""

    pass


class CapabilityRouteNotFoundError(IntegrationError):
    """No route configured for the requested capability."""

    pass
