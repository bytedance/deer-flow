"""Thin synchronous HTTP client for the OpenViking server API."""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from .config import OpenVikingConfig
from .models import OpenVikingCommitResult, OpenVikingIdentity, OpenVikingMessage, OpenVikingSearchHit, OpenVikingSessionContext


class OpenVikingClientError(RuntimeError):
    """Base error raised by the remote OpenViking adapter."""

    def __init__(self, operation: str, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.operation = operation
        self.status_code = status_code
        self.code = code


class OpenVikingAuthenticationError(OpenVikingClientError):
    pass


class OpenVikingTimeoutError(OpenVikingClientError):
    pass


class OpenVikingUnavailableError(OpenVikingClientError):
    pass


class OpenVikingProtocolError(OpenVikingClientError):
    pass


class OpenVikingHttpClient:
    """OpenViking API wrapper with bounded timeout and conservative retries."""

    def __init__(self, config: OpenVikingConfig, *, transport: httpx.BaseTransport | None = None):
        self._config = config
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.write_timeout_seconds,
            pool=config.pool_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
        )
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=timeout,
            limits=limits,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> bool:
        response = self._request("health", "GET", "/health", identity=None, retryable=True)
        if response.status_code != 200:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        return payload.get("status") == "ok"

    def ensure_session(self, identity: OpenVikingIdentity, session_id: str) -> None:
        self._request_result(
            "session.ensure",
            "GET",
            f"/api/v1/sessions/{session_id}",
            identity=identity,
            params={"auto_create": "true"},
            retryable=True,
        )

    def add_messages(self, identity: OpenVikingIdentity, session_id: str, messages: list[OpenVikingMessage]) -> int:
        if not messages:
            return 0
        added = 0
        # OpenViking caps one batch at 100 messages.
        for offset in range(0, len(messages), 100):
            batch = messages[offset : offset + 100]
            result = self._request_result(
                "messages.add",
                "POST",
                f"/api/v1/sessions/{session_id}/messages/batch",
                identity=identity,
                json={"messages": [message.as_request() for message in batch]},
                retryable=False,
            )
            added += int(result.get("added", len(batch)))
        return added

    def commit_session(self, identity: OpenVikingIdentity, session_id: str) -> OpenVikingCommitResult:
        result = self._request_result(
            "session.commit",
            "POST",
            f"/api/v1/sessions/{session_id}/commit",
            identity=identity,
            json={"keep_recent_count": 0},
            retryable=False,
        )
        return OpenVikingCommitResult(
            status=str(result.get("status") or ""),
            task_id=str(result["task_id"]) if result.get("task_id") else None,
            archive_uri=str(result["archive_uri"]) if result.get("archive_uri") else None,
            archived=bool(result.get("archived", False)),
        )

    def search(
        self,
        identity: OpenVikingIdentity,
        query: str,
        *,
        top_k: int,
        category: str | None = None,
        session_id: str | None = None,
    ) -> list[OpenVikingSearchHit]:
        body: dict[str, Any] = {
            "query": query,
            "target_uri": "viking://user/memories",
            "context_type": "memory",
            "node_limit": top_k,
        }
        if session_id:
            body["session_id"] = session_id
        if self._config.score_threshold is not None:
            body["score_threshold"] = self._config.score_threshold
        result = self._request_result(
            "search",
            "POST",
            "/api/v1/search/search" if session_id else "/api/v1/search/find",
            identity=identity,
            json=body,
            retryable=True,
        )
        values = result.get("memories", [])
        if not isinstance(values, list):
            raise OpenVikingProtocolError("search", "OpenViking response field result.memories is not a list")
        hits = [OpenVikingSearchHit.from_response(value) for value in values if isinstance(value, dict)]
        if category:
            category_key = category.casefold()
            hits = [hit for hit in hits if hit.category.casefold() == category_key]
        return hits[:top_k]

    def get_session_context(
        self,
        identity: OpenVikingIdentity,
        session_id: str,
        *,
        token_budget: int,
    ) -> OpenVikingSessionContext:
        result = self._request_result(
            "session.context",
            "GET",
            f"/api/v1/sessions/{session_id}/context",
            identity=identity,
            params={"token_budget": token_budget},
            retryable=True,
        )
        messages = result.get("messages", [])
        return OpenVikingSessionContext(
            latest_archive_overview=str(result.get("latest_archive_overview") or ""),
            messages=messages if isinstance(messages, list) else [],
            estimated_tokens=int(result.get("estimatedTokens") or 0),
        )

    def _headers(self, identity: OpenVikingIdentity | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
        if identity is not None and self._config.auth_mode == "trusted":
            headers["X-OpenViking-Account"] = identity.account
            headers["X-OpenViking-User"] = identity.user
        return headers

    def _request_result(self, operation: str, method: str, path: str, *, identity: OpenVikingIdentity, retryable: bool, **kwargs: Any) -> dict[str, Any]:
        response = self._request(operation, method, path, identity=identity, retryable=retryable, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenVikingProtocolError(operation, "OpenViking returned non-JSON data", status_code=response.status_code) from exc
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = str(error.get("code") or "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
            message = str(error.get("message") or "OpenViking request failed") if isinstance(error, dict) else "OpenViking request failed"
            error_type = OpenVikingAuthenticationError if response.status_code in {401, 403} else OpenVikingProtocolError
            raise error_type(operation, message, status_code=response.status_code, code=code)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise OpenVikingProtocolError(operation, "OpenViking response field result is not an object", status_code=response.status_code)
        return result

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        identity: OpenVikingIdentity | None,
        retryable: bool,
        **kwargs: Any,
    ) -> httpx.Response:
        attempts = self._config.max_retries + 1 if retryable else 1
        for attempt in range(attempts):
            try:
                response = self._client.request(method, path, headers=self._headers(identity), **kwargs)
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    time.sleep(_retry_delay(attempt))
                    continue
                raise OpenVikingTimeoutError(operation, "OpenViking request timed out") from exc
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    time.sleep(_retry_delay(attempt))
                    continue
                raise OpenVikingUnavailableError(operation, "OpenViking is unavailable") from exc
            if response.status_code in {429, 502, 503, 504} and attempt + 1 < attempts:
                time.sleep(_retry_delay(attempt))
                continue
            if response.status_code >= 400:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                code = str(error.get("code") or "HTTP_ERROR") if isinstance(error, dict) else "HTTP_ERROR"
                message = str(error.get("message") or f"OpenViking HTTP {response.status_code}") if isinstance(error, dict) else f"OpenViking HTTP {response.status_code}"
                error_type = OpenVikingAuthenticationError if response.status_code in {401, 403} else OpenVikingProtocolError
                raise error_type(operation, message, status_code=response.status_code, code=code)
            return response
        raise OpenVikingUnavailableError(operation, "OpenViking request failed")


def _retry_delay(attempt: int) -> float:
    base_delay = 0.05 * (2**attempt)
    return base_delay + random.uniform(0.0, base_delay)
