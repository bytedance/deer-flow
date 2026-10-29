"""Minimal synchronous Honcho v3 HTTP client for the memory backend.

Deliberately dependency-light: plain httpx against the v3 REST API. Peers and
sessions are get-or-create server-side; message creation is append-only.
Moving to the official ``honcho-ai`` SDK is a possible follow-up, mirroring the
OpenViking custom-HTTP -> official-adapter arc.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import HonchoConfig

SOURCE_ID_KEY = "deerflow_source_id"
MESSAGE_BATCH_SIZE = 100
MAX_LOOKUP_PAGES = 10


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

    def add_messages(self, workspace: str, session_id: str, messages: list[dict[str, Any]]) -> None:
        self._post(f"/v3/workspaces/{workspace}/sessions/{session_id}/messages", {"messages": messages})

    def existing_source_ids(self, workspace: str, session_id: str, source_ids: list[str]) -> set[str]:
        """Consume all lookup pages within a bounded budget, or fail the batch."""
        if not source_ids:
            return set()
        requested = set(source_ids)
        payload = {"filters": {"OR": [{"metadata": {SOURCE_ID_KEY: key}} for key in source_ids]}}
        found: set[str] = set()
        page = 1
        while True:
            data = self._post(f"/v3/workspaces/{workspace}/sessions/{session_id}/messages/list?page={page}&size=100", payload)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise HonchoRequestError("Honcho message lookup returned an invalid page")
            pages = data.get("pages")
            if type(pages) is not int or pages < 0 or type(data.get("page")) is not int or data["page"] != page:
                raise HonchoRequestError("Honcho message lookup returned invalid pagination")
            if pages < page and not (page == 1 and pages == 0 and not data["items"]):
                raise HonchoRequestError("Honcho message lookup returned inconsistent pagination")
            # Duplicate stored identities can span multiple pages even for one
            # requested key. Bound requests, not the number of matching rows.
            if pages > MAX_LOOKUP_PAGES:
                raise HonchoRequestError(f"Honcho message lookup exceeded the {MAX_LOOKUP_PAGES}-page limit")
            for item in data["items"]:
                metadata = item.get("metadata") if isinstance(item, dict) else None
                key = metadata.get(SOURCE_ID_KEY) if isinstance(metadata, dict) else None
                if not isinstance(key, str) or key not in requested:
                    raise HonchoRequestError("Honcho message lookup returned an invalid source identity")
                found.add(key)
            if page >= pages:
                return found
            page += 1

    def working_representation(self, workspace: str, peer_id: str, *, max_conclusions: int = 25) -> str:
        data = self._post(f"/v3/workspaces/{workspace}/peers/{peer_id}/representation", {"max_conclusions": max_conclusions})
        if isinstance(data, dict):
            return str(data.get("representation") or "")
        return ""

    def search(self, workspace: str, query: str, *, limit: int = 5, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if filters:
            payload["filters"] = filters
        data = self._post(f"/v3/workspaces/{workspace}/search", payload)
        return list(data) if isinstance(data, list) else []
