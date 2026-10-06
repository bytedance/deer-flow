"""Generic OpenAI-compatible rerank client (spec 2026-09-14 §4.1, shape from §8.4).

Contract — verified against vLLM's own implementation (Apache-2.0), whose example declares
the endpoint "compatible with Jina and Cohere":

- ``POST {base_url}/rerank`` (the same handler is mounted at ``/v1/rerank`` and ``/v2/rerank``)
- body ``{"model", "query", "documents", "top_n"}`` — **no ``instruct``**, which is a
  DashScope-only field
- response ``{"results": [{"index", "relevance_score", "document"}], "usage"}``

Only the path and the request body actually differ from
:class:`~deerflow.knowledge.reranker.DashScopeReranker`, so the response parses identically.

Errors deliberately reuse that module's exception types: the retrieval paths degrade to the
RRF order on ``RerankerError``, so a second exception type would silently break that
degradation instead of failing loudly.

``base_url`` has **no default** — unlike DashScope a generic provider has no address to fall
back to, so requiring it turns "forgot to configure the endpoint" into a construction error
rather than a request sent nowhere.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence

import httpx

from deerflow.config.rag_config_file import configured_rag_secret
from deerflow.knowledge.endpoint_url import join_endpoint
from deerflow.knowledge.providers import secret_env_var
from deerflow.knowledge.reranker import RerankerAuthError, RerankerError

logger = logging.getLogger(__name__)

#: vLLM mounts the same handler at ``/v1/rerank`` and ``/v2/rerank`` too; ``/rerank`` is the
#: one its own example uses.
RERANK_PATH = "/rerank"

#: Read from the allowlist rather than spelled out here, so the name the admin API reports
#: as this provider's environment fallback and the name read here cannot drift.
_KEY_ENV_VAR = secret_env_var("rerank", "generic-rerank")


class GenericReranker:
    def __init__(
        self,
        *,
        base_url: str,
        model: str | None = None,
        api_key: str | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if model is None:
            from deerflow.config.app_config import get_app_config

            model = get_app_config().rag.rerank_model
        self._model = model
        self._api_key = api_key  # resolved lazily, so env-only usage never passes keys around
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str:
        key = self._api_key or configured_rag_secret("rerank_api_key")
        if not key and _KEY_ENV_VAR:
            key = os.environ.get(_KEY_ENV_VAR)
        if not key:
            hint = _KEY_ENV_VAR or "RAG_RERANK_API_KEY"
            raise RerankerAuthError(f"{hint} is not set; add it to .env (see .env.example)")
        return key

    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int = 5) -> list[tuple[int, float]]:
        """Return ``(document_index, relevance_score)`` pairs, best first."""
        if not documents:
            return []
        payload = {
            "model": self._model,
            "query": query,
            "documents": list(documents),
            "top_n": min(top_n, len(documents)),
        }
        body = await self._post_with_retry(payload)
        results = body.get("results") or []
        pairs = [(int(item["index"]), float(item["relevance_score"])) for item in results if isinstance(item, dict) and "index" in item]
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs

    async def _post_with_retry(self, payload: dict) -> dict:
        url = join_endpoint(self._base_url, RERANK_PATH)
        headers = {"Authorization": f"Bearer {self._read_api_key()}", "Content-Type": "application/json"}
        close_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close_client = True
        try:
            last_error: Exception | None = None
            for attempt in range(self._max_retries):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.HTTPError as exc:  # transport-level: retryable
                    last_error = RerankerError(f"Rerank request failed: {exc}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error from exc
                body = self._decode_body(response)
                if response.status_code in (401, 403):
                    raise RerankerAuthError(self._error_message(response.status_code, body))
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RerankerError(self._error_message(response.status_code, body))
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error
                if response.status_code != 200:
                    raise RerankerError(self._error_message(response.status_code, body))
                return body
            raise last_error or RerankerError("Rerank failed")
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def _decode_body(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _error_message(status_code: int, body: dict) -> str:
        code = body.get("code") or body.get("error") or ""
        message = body.get("message") or ""
        detail = f"{code}: {message}".strip(": ") or "no error detail"
        return f"Rerank failed (HTTP {status_code}): {detail}"
