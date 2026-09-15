"""Synchronous httpx client for the mem0 REST API (v3; delete is v1).

The MemoryManager contract is synchronous (DeerMem's LLM calls are sync too),
so this client is a plain ``httpx.Client``. It is constructed with an
optional ``transport`` so tests can inject ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class Mem0APIError(RuntimeError):
    """Any mem0 request failure (transport, 4xx/5xx)."""


class Mem0AuthError(Mem0APIError):
    """401 -- missing or invalid API key."""


class Mem0Client:
    """Thin wrapper over the mem0 endpoints DeerFlow uses."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise Mem0APIError(f"mem0 request failed: {e}") from e
        if resp.status_code == 401:
            raise Mem0AuthError("mem0 authentication failed (check the API key)")
        if resp.status_code >= 400:
            raise Mem0APIError(f"mem0 {method} {path} -> {resp.status_code}: {resp.text[:200]}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise Mem0APIError(f"mem0 {method} {path} returned malformed JSON: {e}") from e

    def add_memories(
        self,
        *,
        messages: list[dict[str, str]],
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue extraction (async server-side; response carries an event_id)."""
        body: dict[str, Any] = {"messages": messages}
        if user_id:
            body["user_id"] = user_id
        if agent_id:
            body["agent_id"] = agent_id
        if run_id:
            body["run_id"] = run_id
        return self._request("POST", "/v3/memories/add/", json=body)

    def search_memories(
        self,
        *,
        query: str,
        filters: dict[str, Any],
        top_k: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        body = {"query": query, "filters": filters, "top_k": top_k, "threshold": threshold}
        return self._request("POST", "/v3/memories/search/", json=body).get("results", [])

    def list_memories(
        self,
        *,
        filters: dict[str, Any],
        page_size: int = 200,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """List memories across pages until exhausted or ``max_items`` reached."""
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "POST",
                "/v3/memories/",
                params={"page": page, "page_size": page_size},
                json={"filters": filters},
            )
            results.extend(data.get("results", []))
            if not data.get("next") or (max_items is not None and len(results) >= max_items):
                return results[:max_items] if max_items is not None else results
            page += 1

    def delete_all_memories(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        params = {k: v for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v}
        self._request("DELETE", "/v1/memories/", params=params)

    def ping(self) -> None:
        """Startup auth check: a 1-item list scoped to a sentinel user id.

        Proves the API key works without touching real data (the sentinel
        bucket is always empty).
        """
        self.list_memories(filters={"user_id": "__deerflow_startup_check__"}, page_size=1, max_items=1)
