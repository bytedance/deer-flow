"""Minimal synchronous Honcho v3 HTTP client for the memory backend.

Deliberately dependency-light: plain httpx against the v3 REST API (peers and
sessions are get-or-create server-side, so every call here is idempotent).
Moving to the official ``honcho-ai`` SDK is a possible follow-up, mirroring the
OpenViking custom-HTTP -> official-adapter arc.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import HonchoConfig


class HonchoRequestError(RuntimeError):
    """A Honcho API call failed (transport error or non-2xx response)."""


class HonchoClient:
    def __init__(self, config: HonchoConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        # `transport` exists so tests can inject httpx.MockTransport (Mem0Client precedent).
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.Client(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds, connect=config.connect_timeout_seconds),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, payload: Any) -> Any:
        try:
            response = self._http.post(path, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HonchoRequestError(f"Honcho request failed: POST {path}: {exc}") from exc
        if response.content:
            try:
                return response.json()
            except ValueError as exc:
                raise HonchoRequestError(f"Honcho returned non-JSON response: POST {path}: {exc}") from exc
        return None

    def get_or_create_peer(self, workspace: str, peer_id: str) -> None:
        self._post(f"/v3/workspaces/{workspace}/peers", {"id": peer_id})

    def get_or_create_session(self, workspace: str, session_id: str) -> None:
        self._post(f"/v3/workspaces/{workspace}/sessions", {"id": session_id})

    def set_session_peers(self, workspace: str, session_id: str, peer_ids: list[str]) -> None:
        self._post(f"/v3/workspaces/{workspace}/sessions/{session_id}/peers", {peer_id: {} for peer_id in peer_ids})

    def add_messages(self, workspace: str, session_id: str, messages: list[dict[str, str]]) -> None:
        self._post(f"/v3/workspaces/{workspace}/sessions/{session_id}/messages", {"messages": messages})

    def working_representation(self, workspace: str, peer_id: str, *, max_conclusions: int = 25) -> str:
        data = self._post(f"/v3/workspaces/{workspace}/peers/{peer_id}/representation", {"max_conclusions": max_conclusions})
        if isinstance(data, dict):
            return str(data.get("representation") or "")
        return ""

    def search(self, workspace: str, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        data = self._post(f"/v3/workspaces/{workspace}/search", {"query": query, "limit": limit})
        return list(data) if isinstance(data, list) else []
