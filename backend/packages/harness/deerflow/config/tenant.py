"""Tenant context management for multi-tenant deployments.

Provides a :class:`ContextVar`-based tenant context that flows through the
entire request lifecycle without threading through every function signature.

Usage::

    from deerflow.config.tenant import get_current_tenant_id, set_current_tenant_id

    set_current_tenant_id("acme-corp")
    assert get_current_tenant_id() == "acme-corp"
"""

from __future__ import annotations

import contextvars
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
_DEFAULT_TENANT_ID = "default"

_current_tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deerflow_tenant_id",
    default=_DEFAULT_TENANT_ID,
)


def get_current_tenant_id() -> str:
    """Return the tenant ID for the current async context.

    Falls back to ``"default"`` when no tenant has been set.
    """
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: str) -> contextvars.Token[str]:
    """Set the tenant ID for the current async context.

    Args:
        tenant_id: The tenant ID to set. Must match ``TENANT_ID_PATTERN``.

    Returns:
        A :class:`~contextvars.Token` that can be passed to
        :func:`reset_tenant_id` to restore the previous value.

    Raises:
        ValueError: If *tenant_id* does not match the allowed pattern.
    """
    validate_tenant_id(tenant_id)
    return _current_tenant_id.set(tenant_id)


def reset_tenant_id(token: contextvars.Token[str]) -> None:
    """Restore the tenant ID to the value captured by *token*."""
    _current_tenant_id.reset(token)


def validate_tenant_id(tenant_id: Any) -> str:
    """Validate a tenant ID and return it unchanged.

    Args:
        tenant_id: The tenant ID to validate.

    Returns:
        The validated tenant ID.

    Raises:
        ValueError: If *tenant_id* is not a string or does not match
                    ``TENANT_ID_PATTERN``.
    """
    if not isinstance(tenant_id, str):
        raise ValueError(f"Tenant ID must be a string, got {type(tenant_id).__name__!r}")
    if not TENANT_ID_PATTERN.match(tenant_id):
        raise ValueError(
            f"Invalid tenant ID {tenant_id!r}: must match {TENANT_ID_PATTERN.pattern} "
            "(letters, digits, and hyphens only)"
        )
    return tenant_id
