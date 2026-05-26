"""Permission constants for the insights subsystem.

These are referenced by:

- :mod:`app.gateway.routers.insights` to enforce per-action authorization
- ``app/gateway/authz.py`` so the FastAPI ``require_permission`` decorator
  can guard the REST routes
"""

from __future__ import annotations

INSIGHTS_READ = "insights:read"
"""Permission to view feedback trends, closure metrics, and improvement suggestions."""

INSIGHTS_WRITE = "insights:write"
"""Permission to apply improvements, dismiss suggestions, and promote KB candidates."""

INSIGHTS_PERMISSIONS: tuple[str, ...] = (INSIGHTS_READ, INSIGHTS_WRITE)
"""Convenience tuple — register every insights permission with the RBAC layer."""
