"""DashScope qwen3-rerank client (spec §4.1 precision ranking).

Contract (verified against the Aliyun Model Studio docs) — qwen3-rerank uses
the **flat** compatible-api shape, unlike the older gte-rerank:

- ``POST {base_url}/compatible-api/v1/reranks``
- body ``{"model", "query", "documents": [...], "top_n", "instruct"}`` — no
  ``input``/``parameters`` wrapper
- response carries ``results`` at the top level (no ``output`` envelope):
  ``[{"index", "relevance_score"}]`` sorted by score descending; document
  bodies are NOT returned, so callers map results back through ``index``.
- Limits: ≤ 500 documents per call, ≤ 4000 tokens per query/document.

The API key always comes from ``DASHSCOPE_RERANK_API_KEY`` — never from the
caller (same rule as the embedding key).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence

import httpx

from deerflow.config.rag_config_file import SECRET_ENV_VARS, configured_rag_secret

logger = logging.getLogger(__name__)

DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com"
_RERANK_PATH = "/compatible-api/v1/reranks"
_KEY_ENV_VAR = SECRET_ENV_VARS["rerank_api_key"]

#: Default rerank task instruction (Aliyun's recommended QA-retrieval prompt).
DEFAULT_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query."


class RerankerError(Exception):
    """Any DashScope rerank failure after retries are exhausted."""


class RerankerAuthError(RerankerError):
    """Missing or rejected API key (never retried)."""


class DashScopeReranker:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = DASHSCOPE_RERANK_BASE_URL,
        instruct: str = DEFAULT_INSTRUCT,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if model is None:
            from deerflow.config.app_config import get_app_config

            model = get_app_config().rag.rerank_model
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._instruct = instruct
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str:
        key = self._api_key or configured_rag_secret("rerank_api_key") or os.environ.get(_KEY_ENV_VAR)
        if not key:
            raise RerankerAuthError(f"{_KEY_ENV_VAR} is not set; add it to .env (see .env.example)")
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
            "instruct": self._instruct,
        }
        body = await self._post_with_retry(payload)
        results = body.get("results") or []
        pairs = [(int(item["index"]), float(item["relevance_score"])) for item in results if isinstance(item, dict) and "index" in item]
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs

    async def _post_with_retry(self, payload: dict) -> dict:
        url = f"{self._base_url}{_RERANK_PATH}"
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
                except httpx.HTTPError as exc:
                    last_error = RerankerError(f"DashScope rerank request failed: {exc}")
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
                code = str(body.get("code") or "")
                if code:
                    message = self._error_message(response.status_code, body)
                    if "apikey" in code.lower().replace("_", ""):
                        raise RerankerAuthError(message)
                    raise RerankerError(message)
                return body
            raise last_error or RerankerError("DashScope rerank failed")
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
        code = body.get("code") or ""
        message = body.get("message") or ""
        detail = f"{code}: {message}".strip(": ") or "no error detail"
        return f"DashScope rerank failed (HTTP {status_code}): {detail}"
