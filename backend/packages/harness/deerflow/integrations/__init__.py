"""External systems integration layer.

This package provides a three-layer architecture for integrating external systems:
- Adapter (protocol layer): Handles system-specific communication
- Service (capability layer): Business-oriented interfaces
- Tool (consumption layer): Agent-facing tools

Canonical models ensure type-safe data exchange across all layers.
"""

from deerflow.integrations.config import (
    CapabilityRouteConfig,
    EntityLinkConfig,
    EntityLinkEntry,
    IntegrationSystemConfig,
    IntegrationsConfig,
    RetryPolicy,
)
from deerflow.integrations.errors import (
    CapabilityRouteNotFoundError,
    EntityLinkNotFound,
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationDataShapeError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
)
from deerflow.integrations.registry import IntegrationRegistry, get_integration_registry

__all__ = [
    # Config
    "IntegrationsConfig",
    "IntegrationSystemConfig",
    "CapabilityRouteConfig",
    "EntityLinkConfig",
    "EntityLinkEntry",
    "RetryPolicy",
    # Errors
    "IntegrationError",
    "IntegrationConfigError",
    "IntegrationAuthError",
    "IntegrationTimeoutError",
    "IntegrationUnavailableError",
    "IntegrationDataShapeError",
    "EntityLinkNotFound",
    "CapabilityRouteNotFoundError",
    # Registry
    "IntegrationRegistry",
    "get_integration_registry",
]
