"""Shared sandbox scope-token derivation (RFC #4741).

COMPATIBILITY CONTRACT: this derivation is a durable identity boundary. AIO,
E2B, BoxLite, Tenki, and OpenSandbox locate existing containers and VMs
through this token. Changing any property — separator, encoding, digest,
casing, or truncation length — is a breaking migration: existing remote
resources would no longer be found and would be cold-started.

Providers resolve ``user_id`` before calling this function, and their
resolutions differ (effective-user lookup, ``""`` substitution, or raw
pass-through). That resolution stays provider-private; this module only pins
what happens to the resolved strings.
"""

from __future__ import annotations

import hashlib
import re

SANDBOX_ID_VERSION = 1

_TOKEN_HEX_LEN = 16
_TOKEN_RE = re.compile(r"[0-9a-f]{16}")


def derive_sandbox_scope_token(*, user_id: str, thread_id: str) -> str:
    """Return the durable 16-lowercase-hex sandbox scope token.

    Keyword-only: every provider helper this replaces takes
    ``(thread_id, user_id)`` positionally — the reverse order — and both are
    plain ``str``; keyword-only call sites eliminate silent argument-order
    mistakes during and after the migration.

    WARNING: changing the separator, encoding, digest, casing, or truncation
    length is a breaking migration — existing containers and VMs would no
    longer be found. See module docstring.
    """
    return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:_TOKEN_HEX_LEN]


def is_sandbox_scope_token(value: object) -> bool:
    """Validate token shape only; a truncated hash is not reversible."""
    return isinstance(value, str) and _TOKEN_RE.fullmatch(value) is not None
