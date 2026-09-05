"""Minimal asynchronous client for the LightRAG APIs DeerFlow consumes."""

from __future__ import annotations

from typing import Any

import httpx

QUERY_MODES = ("naive", "local", "global", "hybrid", "mix")


class LightRAGError(Exception):
    """Base class for normalized LightRAG failures."""


class LightRAGAPIError(LightRAGError):
    """LightRAG rejected the request with a readable failure."""


class LightRAGConnectionError(LightRAGError):
    """LightRAG could not be reached or timed out."""


class LightRAGProtocolError(LightRAGError):
    """LightRAG returned an invalid or unexpected HTTP response."""


class LightRAGClient:
    """Direct HTTP client for DeerFlow's read-only retrieval tools.

    The client deliberately owns no cache or persistent state. A fresh HTTP
    session is opened for each method call so callers do not need to manage a
    client lifecycle. The optional API key is sent as the ``X-API-Key``
    request header, the single credential form LightRAG documents for
    API-key-authenticated servers; unauthenticated deployments simply omit it.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key
        self._transport = transport

    def _redact(self, value: object) -> str:
        text = str(value)
        if self._api_key:
            text = text.replace(self._api_key, "[REDACTED]")
        return text

    def _error_message(self, payload: object, status_code: int) -> str | None:
        """Extract a redacted, human-readable message from an error payload.

        LightRAG failures carry text in ``message`` (QueryDataResponse
        envelope) or ``detail`` (FastAPI error handler, either a string or a
        list of validation objects whose ``msg`` holds the reason, prefixed by
        pydantic's "Value error, "). Anything else — structured bodies, plain
        text, missing payloads — yields ``None`` so the caller falls back to a
        stable protocol error instead of dumping raw JSON at the model.
        """
        if not isinstance(payload, dict):
            return None
        candidate = payload.get("message")
        if not isinstance(candidate, str) or not candidate.strip():
            detail = payload.get("detail")
            if isinstance(detail, str):
                candidate = detail
            elif isinstance(detail, list):
                candidate = self._first_validation_message(detail)
        if isinstance(candidate, str) and candidate.strip():
            text = candidate.removeprefix("Value error, ").strip()
            return self._redact(text)
        return None

    @staticmethod
    def _first_validation_message(items: list[object]) -> str | None:
        for item in items:
            if isinstance(item, dict):
                message = item.get("msg")
                if isinstance(message, str) and message.strip():
                    return message
        return None

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        request_headers = {"Accept": "application/json"}
        if self._api_key:
            request_headers["X-API-Key"] = self._api_key
        client_kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "headers": request_headers,
            "timeout": self.timeout,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(method, path, json=json)
        except httpx.TimeoutException:
            raise LightRAGConnectionError(f"LightRAG request timed out after {self.timeout:g} seconds.") from None
        except httpx.RequestError as exc:
            detail = self._redact(exc)
            raise LightRAGConnectionError(f"{type(exc).__name__}: {detail}") from None

        if response.is_error:
            # A 404 on the data-retrieval endpoint means either a wrong
            # base_url or a LightRAG older than v1.4.8, where /query/data did
            # not exist yet; the default "Not Found" body helps neither case.
            if response.status_code == 404:
                raise LightRAGAPIError("LightRAG data-retrieval endpoint not found; check base_url or upgrade LightRAG to v1.4.8 or newer.")
            try:
                error_payload = response.json()
            except ValueError:
                raise LightRAGProtocolError(f"LightRAG request failed (HTTP {response.status_code}).") from None
            message = self._error_message(error_payload, response.status_code)
            if message is not None:
                raise LightRAGAPIError(message)
            raise LightRAGProtocolError(f"LightRAG request failed (HTTP {response.status_code}).")

        try:
            payload = response.json()
        except ValueError:
            raise LightRAGProtocolError("LightRAG returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise LightRAGProtocolError("LightRAG returned a non-object JSON payload.")

        status = payload.get("status")
        if status != "success":
            message = payload.get("message")
            text = self._redact(message) if isinstance(message, str) and message.strip() else "LightRAG request failed."
            raise LightRAGAPIError(text)
        return payload

    async def query_data(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: int = 60,
        chunk_top_k: int | None = None,
    ) -> dict[str, Any]:
        """Run one read-only structured retrieval against ``POST /query/data``.

        The data endpoint performs no LLM generation and always returns
        entities, relationships, chunks, and references, which is exactly the
        read-only shape DeerFlow's knowledge tool consumes.
        """
        if mode not in QUERY_MODES:
            raise ValueError(f"mode must be one of {QUERY_MODES}")

        request_body: dict[str, object] = {"query": query, "mode": mode, "top_k": top_k}
        if chunk_top_k is not None:
            request_body["chunk_top_k"] = chunk_top_k

        payload = await self._request("POST", "/query/data", json=request_body)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LightRAGProtocolError("LightRAG returned an invalid retrieval result.")
        return data
