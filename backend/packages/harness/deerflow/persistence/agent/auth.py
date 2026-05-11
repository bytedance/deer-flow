"""Tenant authorization utilities."""

from __future__ import annotations


def is_tenant_admin(system_role: str | None) -> bool:
    """Check if a user's system_role grants tenant admin privileges.

    Both 'tenant_admin' and 'superadmin' are considered tenant administrators.
    Superadmin is treated as admin for all tenants.

    Args:
        system_role: The user's system_role value.

    Returns:
        True if the user has tenant admin or higher privileges.
    """
    return system_role in ("tenant_admin", "superadmin")
