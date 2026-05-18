"""HMAC-SHA256 signer for audit events (plan M2-4, RFC §5.3).

We sign the audit row's canonical serialisation, not the raw Pydantic
model. Two practical reasons:

1. ``details: dict`` has no key order guarantee at the Python level —
   ``json.dumps(..., sort_keys=True)`` gives us a deterministic byte
   stream that survives a round-trip through SQLite TEXT storage.
2. The signer is **storage-agnostic**: SqliteAuditStorage and
   PostgresAuditStorage both call ``signer.sign(event)`` exactly the
   same way, so verify_integrity can re-derive the signature without
   knowing the backend.

The hex digest is stored in the ``signature`` column; integrity
verification recomputes it and compares with :func:`hmac.compare_digest`
to avoid timing side channels.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

from deerflow.enterprise.audit.events import AuditEvent


# Fields that are NOT included in the signed payload. ``signature``
# itself is obviously excluded (it would be a chicken-and-egg). ``id``
# is excluded so that a row's signature is stable across legitimate
# regeneration paths (e.g. backfill scripts that compute signatures
# after the row id has been allocated). Storage backends still index
# the id; we just don't tie tamper-detection to it.
_UNSIGNED_FIELDS: frozenset[str] = frozenset({"signature"})


class AuditSigner:
    """Sign and verify :class:`AuditEvent` rows with a shared secret."""

    def __init__(self, key: str | bytes):
        if not key:
            raise ValueError("AuditSigner requires a non-empty key")
        self._key: bytes = key.encode("utf-8") if isinstance(key, str) else key

    # ── public API ────────────────────────────────────────────────────

    def sign(self, event: AuditEvent) -> str:
        """Return the HMAC-SHA256 hex digest of ``event``'s canonical bytes."""
        payload = self._canonical_bytes(event)
        return hmac.new(self._key, payload, sha256).hexdigest()

    def verify(self, event: AuditEvent) -> bool:
        """True iff ``event.signature`` matches the recomputed digest.

        Returns False — never raises — when ``signature`` is missing so
        callers can treat "unsigned" and "tampered" as the same
        operational class without try/except plumbing.
        """
        if not event.signature:
            return False
        expected = self.sign(event)
        return hmac.compare_digest(expected, event.signature)

    # ── canonicalisation ──────────────────────────────────────────────

    @staticmethod
    def _canonical_bytes(event: AuditEvent) -> bytes:
        """Serialise the signed fields into deterministic JSON bytes.

        We hand-roll the payload (rather than ``event.model_dump_json``)
        so the byte format is decoupled from Pydantic's serialisation
        quirks across versions. A schema migration in Pydantic would
        otherwise silently invalidate every historical signature.
        """
        payload: dict[str, Any] = {}
        for name in type(event).model_fields:
            if name in _UNSIGNED_FIELDS:
                continue
            value = getattr(event, name)
            payload[name] = AuditSigner._normalise(value)
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _normalise(value: Any) -> Any:
        """Convert non-JSON-native types (datetime, Enum) to strings.

        :class:`AuditEventType` is a ``str`` Enum so ``.value`` is the
        canonical wire form. ``datetime`` is rendered via ``.isoformat``
        — explicitly UTC by convention (see :class:`AuditEvent`).
        """
        # Late imports keep this module dependency-free at top level.
        from datetime import datetime
        from enum import Enum

        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: AuditSigner._normalise(v) for k, v in value.items()}
        if isinstance(value, list):
            return [AuditSigner._normalise(v) for v in value]
        return value


__all__ = ["AuditSigner"]
