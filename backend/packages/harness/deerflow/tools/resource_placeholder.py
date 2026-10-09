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

from urllib.parse import urlparse

from deerflow.config.paths import VIRTUAL_PATH_PREFIX


def model_visible_location(url: str | None) -> str | None:
    """Return *url* when it is safe to show in model-visible placeholder text.

    Shared by the conversion layer and the read-time middleware so both emit
    placeholders under the same rules:

    - virtual paths (``/mnt/user-data/...``) and remote schemes (``http(s)``,
      ``ui://``, ``s3://``, ...) carry no host-path risk and stay visible;
    - a raw ``file://`` URI, a bare host path, or a Windows drive path
      (urlparse reads the drive letter as a single-character scheme) leaks the
      deployment's filesystem layout, so it collapses to ``None`` and the
      placeholder omits the location segment (US-16);
    - ``data:`` URIs embed their whole base64 payload and ``blob:`` URIs name a
      browser-local object nothing else can dereference, so they collapse to
      ``None`` too — inlining either would put kilobytes-to-megabytes of
      base64 into the model-visible text.
    """
    if not url:
        return None
    if url.startswith(VIRTUAL_PATH_PREFIX):
        return url
    try:
        scheme = urlparse(url).scheme
    except ValueError:
        return None
    if not scheme or scheme in ("file", "data", "blob") or (len(scheme) == 1 and scheme.isalpha()):
        # Bare host path, ``file://`` URI, inline payload, browser-local
        # object, or Windows drive path.
        return None
    return url


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
