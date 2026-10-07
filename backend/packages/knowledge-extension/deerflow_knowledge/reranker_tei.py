"""TEI rerank client (spec 2026-09-24 §4.3, D3 甲).

Contract — pinned from the upstream source (``huggingface/text-embeddings-inference``):

- ``POST {base_url}/rerank`` — the only route it mounts (there is no ``/v1`` alias)
- body ``{"query", "texts", "raw_scores": False}`` — **no ``model``**: one TEI instance serves
  exactly one model (the rule :class:`~deerflow_knowledge.sparse.TEISparseEncoder` states), so
  this class takes no ``model`` argument either and the allowlist row says ``takes_model=False``
- response is a **bare array** ``[{"index", "score"}, ...]`` rather than the Cohere/Jina
  ``{"results": [...]}`` envelope, which is why the leg has its own provider row instead of a
  branch inside the generic client
- no ``top_n``: the service has no such parameter, so the cap is applied locally — the vector
  path feeds the return value straight to its caller as the final result list

Errors deliberately reuse :mod:`deerflow_knowledge.reranker`'s exception types: the retrieval
paths degrade to the RRF order on ``RerankerError``, so a second type would silently break that
degradation instead of failing loudly, and a malformed answer (non-array, or a row without
``index`` / ``score``) must never degrade into a silent empty ranking.

Authentication is **optional** — a TEI server started without an API key installs no auth
middleware at all, and an empty ``Bearer`` would be refused. The key is read in the same
three-step order as the other clients (explicit → ``rag_config.json`` → environment), but a
missing one is not an error here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Any

import httpx

from deerflow.config.rag_config_file import configured_rag_secret
from deerflow_knowledge.providers import secret_env_var
from deerflow_knowledge.reranker import RerankerAuthError, RerankerError

logger = logging.getLogger(__name__)

#: Upstream `server.rs` mounts one rerank route; there is no `/v1/rerank` alias to fall back on.
RERANK_PATH = "/rerank"

#: Read from the allowlist rather than spelled out here, so the name the admin API reports as
#: this provider's environment fallback and the name read here cannot drift.
_KEY_ENV_VAR = secret_env_var("rerank", "tei-rerank")


class TEIReranker:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key  # resolved lazily, so env-only usage never passes keys around
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str | None:
        key = self._api_key or configured_rag_secret("rerank_api_key")
        if not key and _KEY_ENV_VAR:
            key = os.environ.get(_KEY_ENV_VAR)
        return key

    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int = 5) -> list[tuple[int, float]]:
        """Return ``(document_index, relevance_score)`` pairs, best first, capped at ``top_n``."""
        if not documents:
            return []
        rows = await self._post_with_retry({"query": query, "texts": list(documents), "raw_scores": False})
        pairs: list[tuple[int, float]] = []
        for row in rows:
            try:
                pairs.append((int(row["index"]), float(row["score"])))
            except (TypeError, KeyError, ValueError) as exc:
                raise RerankerError(f"TEI rerank returned a malformed row: {str(row)[:200]}") from exc
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs[:top_n]

    async def _post_with_retry(self, payload: dict) -> list:
        url = f"{self._base_url}{RERANK_PATH}"
        headers = {"Content-Type": "application/json"}
        api_key = self._read_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
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
                if not isinstance(body, list):
                    raise RerankerError(f"TEI rerank returned a non-array payload: {str(body)[:200]}")
                return body
            raise last_error or RerankerError("Rerank failed")
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def _decode_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def _error_message(status_code: int, body: Any) -> str:
        detail = ""
        if isinstance(body, dict):
            code = body.get("error") or body.get("code") or ""
            message = body.get("error_type") or body.get("message") or ""
            detail = f"{code}: {message}".strip(": ")
        return f"TEI rerank failed (HTTP {status_code}): {detail or 'no error detail'}"
