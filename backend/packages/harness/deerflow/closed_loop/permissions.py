"""Permission constants for the closed-loop subsystem.

These are referenced by:

- :mod:`deerflow.closed_loop.service` to enforce per-action authorization
- ``app/gateway/authz.py`` so the FastAPI ``require_permission`` decorator
  can guard the REST routes
- ``builtin closure_ticket_tools`` so direct tool calls also propagate auth
"""

from __future__ import annotations

CLOSURE_READ = "closure:read"
"""Permission to view closure tickets and listings."""

CLOSURE_WRITE = "closure:write"
"""Permission to create / dispatch / progress / reject closure tickets.

Covers actions: ``create``, ``assign``, ``start``, ``submit_verification``,
``reject``, ``reopen``, ``update_metadata``.
"""

CLOSURE_VERIFY = "closure:verify"
"""Permission to verify and close a ticket (``verify_close`` action)."""

CLOSURE_PERMISSIONS: tuple[str, ...] = (CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY)
"""Convenience tuple — register every closure permission with the RBAC layer."""
