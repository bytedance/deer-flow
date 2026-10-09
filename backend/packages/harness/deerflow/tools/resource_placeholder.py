"""Canonical model-visible placeholder text for MCP resource links.

Both the MCP conversion layer (``deerflow.mcp.tools``) and the read-time
``ModelContentCompatibilityMiddleware`` downgrade resource references that a
chat model cannot consume into a short text placeholder. They share this
formatter so a thread healed at read time shows the model the exact same
placeholder shape a fresh conversion would have produced. Persisted content
blocks carry no resource name, so the name segment is optional and simply
omitted when absent.
"""

from __future__ import annotations


def resource_placeholder_text(
    *,
    name: str | None = None,
    mime_type: str | None = None,
    url: str | None = None,
) -> str:
    """Return the canonical ``[Resource ...]`` placeholder text.

    ``mime_type`` falls back to ``"unknown type"``; an empty/``None`` ``url``
    omits the location segment entirely (used for host paths that must never
    reach model-visible text and for non-referenceable inline schemes).
    """
    mime = mime_type or "unknown type"
    location = f" available at {url}" if url else ""
    if name:
        return f"[Resource: {name} ({mime}){location}]"
    return f"[Resource ({mime}){location}]"
