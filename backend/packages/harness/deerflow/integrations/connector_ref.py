"""Connector reference resolution utilities.

Resolves IntegrationSystemConfig.connector_ref to HTTP transport configuration
from the tenant connector store.
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.integrations.config import IntegrationSystemConfig

logger = logging.getLogger(__name__)


def resolve_connector_ref(
    config: IntegrationSystemConfig,
) -> dict[str, Any] | None:
    """Resolve connector_ref to HTTP transport configuration.

    Args:
        config: Integration system configuration with connector_ref

    Returns:
        Dict with transport config (base_url, auth_headers, timeout) if resolved,
        None if connector_ref is not set or resolution fails.

    Note:
        This is a stub implementation. Full tenant connector lookup requires
        integration with the tenant_connectors API (Phase 2 feature).
        Currently logs a warning and returns None, allowing adapters to fall
        back to base_url from the system config.
    """
    if not config.connector_ref:
        return None

    # Phase 2: Implement tenant connector lookup here
    # For now, log warning and return None to trigger fallback
    logger.warning(
        "connector_ref '%s' for system '%s' not resolved — "
        "tenant connector lookup not yet implemented. "
        "Falling back to base_url from system config.",
        config.connector_ref,
        config.system_key,
    )
    return None


def build_transport_config(
    config: IntegrationSystemConfig,
) -> dict[str, Any]:
    """Build HTTP transport configuration from system config + connector_ref.

    Attempts to resolve connector_ref first, falls back to system config values.

    Args:
        config: Integration system configuration

    Returns:
        Dict with keys: base_url, timeout_seconds, auth_type, secret_ref
    """
    connector_config = resolve_connector_ref(config)

    if connector_config:
        # Merge connector config with system config (system config takes precedence)
        return {
            "base_url": config.base_url or connector_config.get("base_url"),
            "timeout_seconds": config.timeout_seconds,
            "auth_type": config.auth_type,
            "secret_ref": config.secret_ref,
        }

    # Fallback to system config
    return {
        "base_url": config.base_url,
        "timeout_seconds": config.timeout_seconds,
        "auth_type": config.auth_type,
        "secret_ref": config.secret_ref,
    }
