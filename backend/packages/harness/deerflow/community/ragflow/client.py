"""Minimal asynchronous client for the RAGFlow APIs DeerFlow consumes."""

from __future__ import annotations

from typing import Any

import httpx


class RAGFlowError(Exception):
    """Base class for normalized RAGFlow failures."""


class RAGFlowAPIError(RAGFlowError):
    """RAGFlow returned a valid response envelope with a non-zero code."""

    def __init__(self, message: str, *, code: object = None) -> None:
        self.code = code
        super().__init__(message)


class RAGFlowConnectionError(RAGFlowError):
    """RAGFlow could not be reached or timed out."""


class RAGFlowProtocolError(RAGFlowError):
    """RAGFlow returned an invalid or unexpected HTTP response."""


class RAGFlowClient:
    """Direct HTTP client for DeerFlow's read-only retrieval tools.

    The client deliberately owns no cache or persistent state. A fresh HTTP
    session is opened for each method call so callers do not need to manage a
    client lifecycle.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | list[tuple[str, str]] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        client_kwargs: dict[str, Any] = {
            "base_url": f"{self.base_url}/api/v1",
            "headers": request_headers,
            "timeout": self.timeout,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(method, path, params=params, json=json)
        except httpx.TimeoutException:
            raise RAGFlowConnectionError(f"请求超时（{self.timeout:g} 秒）") from None
        except httpx.RequestError as exc:
            detail = self._redact(exc)
            raise RAGFlowConnectionError(f"{type(exc).__name__}: {detail}") from None

        if response.is_error:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            if isinstance(error_payload, dict) and error_payload.get("code") not in (None, 0):
                message = self._redact(error_payload.get("message") or f"RAGFlow API error (HTTP {response.status_code})")
                raise RAGFlowAPIError(message, code=error_payload.get("code"))
            raise RAGFlowProtocolError(f"RAGFlow 请求失败（HTTP {response.status_code}）")

        try:
            payload = response.json()
        except ValueError:
            raise RAGFlowProtocolError("RAGFlow 返回了无效 JSON") from None
        if not isinstance(payload, dict):
            raise RAGFlowProtocolError("RAGFlow 返回了非对象 JSON")

        code = payload.get("code")
        if code != 0:
            message = self._redact(payload.get("message") or "RAGFlow 请求失败")
            raise RAGFlowAPIError(message, code=code)
        return payload

    async def list_datasets(self) -> list[dict[str, Any]]:
        """List every RAGFlow dataset accessible to the configured tenant key."""
        page = 1
        page_size = 100
        datasets: list[dict[str, Any]] = []

        while True:
            params: dict[str, object] = {"page": page, "page_size": page_size}
            payload = await self._request(
                "GET",
                "/datasets",
                params=params,
            )
            data = payload.get("data")
            if not isinstance(data, list):
                raise RAGFlowProtocolError("RAGFlow 返回了无效的知识库列表")
            batch = [item for item in data if isinstance(item, dict)]
            datasets.extend(batch)

            total = payload.get("total_datasets", payload.get("total"))
            if isinstance(total, int) and len(datasets) >= total:
                break
            if len(data) < page_size:
                break
            page += 1

        return datasets

    async def retrieve(
        self,
        query: str,
        *,
        dataset_ids: list[str] | None = None,
        page_size: int = 8,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        top_k: int = 256,
    ) -> dict[str, Any]:
        """Retrieve chunks, optionally scoped to specific dataset UUIDs."""
        request_body: dict[str, object] = {
            "question": query,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "top_k": top_k,
        }
        if dataset_ids is not None:
            request_body["dataset_ids"] = dataset_ids

        payload = await self._request("POST", "/retrieval", json=request_body)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RAGFlowProtocolError("RAGFlow 返回了无效的检索结果")
        return data
