"""OVMemoryBackend — stores and retrieves memories via the OpenViking HTTP API.

Identity isolation is achieved by setting the three OV headers on every request:
  X-OpenViking-Account  ← dept_id
  X-OpenViking-User     ← user_id
  X-OpenViking-Agent    ← agent_name

This backend is activated when MemoryConfig.backend is 'ov' or 'ov+local'.
"""
from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)


def _agent_space_name(identity: "AgentIdentity") -> str:
    """Derive a stable OV agent-space name from the three identity fields.

    Uses MD5 to match OpenViking's internal hashing convention.
    Falls back to "default" when all fields are absent.
    """
    raw = f"{identity.ov_account}/{identity.ov_user}/{identity.ov_agent}"
    return hashlib.md5(raw.encode()).hexdigest()


class OVMemoryBackend:
    """Async client for OpenViking memory operations with identity isolation."""

    def __init__(self, ov_url: str, api_key: str | None, identity: "AgentIdentity") -> None:
        self._base_url = ov_url.rstrip("/")
        self._identity = identity
        self._api_key = api_key

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._identity.ov_headers,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # ── Public API ────────────────────────────────────────────────────────

    async def store_memory(self, messages: list[dict[str, str]]) -> None:
        """Store a conversation exchange as memories in OV.

        *messages* should be a list of ``{"role": ..., "content": ...}`` dicts.
        """
        if not messages:
            return

        payload: dict[str, Any] = {"messages": messages}
        url = f"{self._base_url}/api/memory/store"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                logger.debug("OV memory stored: %d messages, identity=%s", len(messages), self._identity)
        except httpx.HTTPStatusError as exc:
            logger.error("OV memory store failed (HTTP %d): %s", exc.response.status_code, exc)
            raise
        except httpx.RequestError as exc:
            logger.error("OV memory store connection error: %s", exc)
            raise

    async def search_memory(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        """Search memories semantically.

        Returns a list of memory dicts with at least a ``content`` field.
        Returns an empty list on connection errors (graceful degradation).
        """
        url = f"{self._base_url}/api/memory/search"
        payload = {"query": query, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return data.get("memories", data) if isinstance(data, dict) else data
        except httpx.HTTPStatusError as exc:
            logger.warning("OV memory search failed (HTTP %d): %s", exc.response.status_code, exc)
            return []
        except httpx.RequestError as exc:
            logger.warning("OV memory search connection error (degrading to empty): %s", exc)
            return []
