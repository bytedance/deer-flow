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
    """Any mem0 transport, HTTP, or response-format failure."""


class Mem0AuthError(Mem0APIError):
    """401 -- missing or invalid API key."""


def _memory_results(payload: dict[str, Any], *, context: str) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise Mem0APIError(f"mem0 {context} response results must be a list of objects; got {type(results).__name__}")
    for index, record in enumerate(results):
        if not isinstance(record, dict):
            raise Mem0APIError(f"mem0 {context} response results[{index}] must be an object; got {type(record).__name__}")
    return results


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

    def _request(self, method: str, path: str, *, response_context: str | None = None, **kwargs: Any) -> dict[str, Any]:
        context = response_context or f"{method} {path}"
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise Mem0APIError(f"mem0 request failed: {e}") from e
        if resp.status_code == 401:
            raise Mem0AuthError("mem0 authentication failed (check the API key)")
        if resp.status_code >= 400:
            raise Mem0APIError(f"mem0 {context} -> {resp.status_code}: {resp.text[:200]}")
        if not resp.content:
            return {}
        try:
            payload = resp.json()
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as e:
            raise Mem0APIError(f"mem0 {context} returned malformed JSON: {e}") from e
        if not isinstance(payload, dict):
            raise Mem0APIError(f"mem0 {context} returned a non-object JSON payload")
        return payload

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
        return _memory_results(self._request("POST", "/v3/memories/search/", json=body), context="POST /v3/memories/search/")

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
            context = f"POST /v3/memories/ page={page}"
            data = self._request(
                "POST",
                "/v3/memories/",
                response_context=context,
                params={"page": page, "page_size": page_size},
                json={"filters": filters},
            )
            results.extend(_memory_results(data, context=context))
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
