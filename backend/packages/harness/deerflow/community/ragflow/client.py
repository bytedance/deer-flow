"""Minimal asynchronous client for the RAGFlow APIs DeerFlow consumes."""

from __future__ import annotations

from typing import Any

import httpx

_DATASET_PAGE_SIZE = 100
_MAX_DATASET_PAGES = 100


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
            raise RAGFlowConnectionError(f"RAGFlow request timed out after {self.timeout:g} seconds.") from None
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
            raise RAGFlowProtocolError(f"RAGFlow request failed (HTTP {response.status_code}).")

        try:
            payload = response.json()
        except ValueError:
            raise RAGFlowProtocolError("RAGFlow returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise RAGFlowProtocolError("RAGFlow returned a non-object JSON payload.")

        code = payload.get("code")
        if code != 0:
            message = self._redact(payload.get("message") or "RAGFlow request failed.")
            raise RAGFlowAPIError(message, code=code)
        return payload

    async def list_datasets(self, *, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """Resolve one dataset ID, or enumerate every page when no ID is given."""
        if dataset_id is not None:
            dataset_id = dataset_id.strip()
            if not dataset_id:
                raise ValueError("dataset_id must not be empty")

            # RAGFlow's singular `id` filter returns the generic DATA_ERROR code
            # for an inaccessible or missing dataset, which is indistinguishable
            # from several provider failures. Its `ids` filter instead returns a
            # successful empty list for an inaccessible ID, allowing callers to
            # classify only that result as a missing binding while preserving all
            # real API errors.
            payload = await self._request("GET", "/datasets", params={"ids": dataset_id})
            data = payload.get("data")
            if not isinstance(data, list):
                raise RAGFlowProtocolError("RAGFlow returned an invalid dataset list.")
            return [item for item in data if isinstance(item, dict)]

        datasets: list[dict[str, Any]] = []
        received_count = 0
        for page in range(1, _MAX_DATASET_PAGES + 1):
            payload = await self._request(
                "GET",
                "/datasets",
                params={"page": page, "page_size": _DATASET_PAGE_SIZE},
            )
            data = payload.get("data")
            if not isinstance(data, list):
                raise RAGFlowProtocolError("RAGFlow returned an invalid dataset list.")

            datasets.extend(item for item in data if isinstance(item, dict))
            received_count += len(data)

            total = payload.get("total")
            if not (isinstance(total, int) and not isinstance(total, bool) and total >= 0):
                total = payload.get("total_datasets")
            has_valid_total = isinstance(total, int) and not isinstance(total, bool) and total >= 0
            if has_valid_total:
                if received_count >= total:
                    return datasets
                if not data:
                    raise RAGFlowProtocolError("RAGFlow dataset listing ended before the reported total.")
            elif len(data) < _DATASET_PAGE_SIZE:
                return datasets

        raise RAGFlowProtocolError(f"RAGFlow dataset listing exceeded {_MAX_DATASET_PAGES} pages.")

    async def retrieve(
        self,
        query: str,
        *,
        dataset_ids: list[str],
        page_size: int = 8,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        top_k: int = 256,
    ) -> dict[str, Any]:
        """Retrieve chunks from an explicit, non-empty dataset allowlist."""
        if not dataset_ids or not all(isinstance(dataset_id, str) and dataset_id.strip() for dataset_id in dataset_ids):
            raise ValueError("dataset_ids must contain at least one dataset ID")

        request_body: dict[str, object] = {
            "question": query,
            "dataset_ids": dataset_ids,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "top_k": top_k,
        }

        payload = await self._request("POST", "/retrieval", json=request_body)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RAGFlowProtocolError("RAGFlow returned an invalid retrieval result.")
        return data
