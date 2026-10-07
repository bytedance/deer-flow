"""Generic OpenAI-compatible embedding client (spec 2026-09-14 §4.2).

The dense-only counterpart of ``DashScopeEmbedder``: any endpoint that speaks the OpenAI
embeddings shape can be plugged in. It never returns a sparse half — the sparse route is
supplied by the composition layer (``external`` service or local BM25), which is exactly
why pairing this provider with ``embedding_sparse_source=provider`` is refused at build
time (spec §4.2 交叉校验).

Contract (standard OpenAI shape):

- ``POST {base_url}/v1/embeddings`` with ``{"model", "input": [...]}``
- response ``{"data": [{"index", "embedding": [...]}, ...]}`` — read back **by index**,
  because providers are not required to preserve request order
- no ``dimensions`` parameter is sent: the endpoint's model decides the width and our
  probe measures it (spec §4.2 维度 #1: 探测为主, 显式字段只作覆盖)

Failures reuse the shared ``EmbedderError`` / ``EmbedderAuthError`` so the worker's
"one bad batch never aborts the document" contract behaves identically across providers.
The key's environment fallback comes from the curated allowlist, so the name this client
reads and the name the settings API reports cannot drift.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence

import httpx
from qdrant_client.models import SparseVector

from deerflow_knowledge.embedder import EmbedderAuthError, EmbedderError, EmbeddingResult
from deerflow_knowledge.endpoint_url import join_endpoint
from deerflow_knowledge.providers import secret_env_var

logger = logging.getLogger(__name__)

_EMBEDDINGS_PATH = "/v1/embeddings"
_KEY_ENV_VAR = secret_env_var("embedding", "openai-compatible")

#: Conservative default: generic endpoints vary wildly in what they accept per call. Ten is
#: the lowest cap actually measured (DashScope compatible-mode refuses 20 with HTTP 400
#: ``batch size is invalid``). The generic leg no longer starts here — it walks `BATCH_LADDER` —
#: but the sparse leg still builds with this value, so it stays as it is.
DEFAULT_BATCH_LIMIT = 10

#: Rows per embedding call, tried from the top (spec 2026-09-26 D3 甲′). The first rung is the
#: highest cap we have evidence for (``qwen3.7-text-embedding`` answers 200 at 20 rows), and a
#: batch-size 400 steps down one rung and remembers where it landed: an endpoint that refuses 20
#: costs one wasted round trip per process, while one whose cap is below 10 stops failing every
#: batch forever. The bottom rung is 1 so a service that takes one row at a time still ingests.
BATCH_LADDER: tuple[int, ...] = (20, 10, 5, 2, 1)

#: What this process learned about an endpoint, keyed by ``(base_url, model)`` — the two
#: coordinates a client instance actually holds. Process-local on purpose: it certifies *this*
#: deployment's endpoint, and a config change alters the key anyway.
_BATCH_CAPS: dict[tuple[str, str], int] = {}
_NO_DIMENSION_PARAM: set[tuple[str, str]] = set()


class _Rejected(EmbedderError):
    """A non-retryable non-2xx answer (the 400 family): the *payload* is what has to change.

    Private and transient: it only travels from ``_post_with_retry`` to the batch healer, which
    turns it into either a healed request or the ordinary ``EmbedderError`` the worker knows.
    """


class OpenAICompatibleEmbedder:
    """Dense-only embedder for any OpenAI-compatible ``/v1/embeddings`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None = None,
        api_key: str | None = None,
        batch_size: int | None = None,
        dimension: int | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not (base_url or "").strip():
            raise ValueError("通用嵌入 provider 需要服务地址：请设置 rag.embedding_base_url")
        if model is None:
            from deerflow.config.app_config import get_app_config

            model = get_app_config().rag.embedding_model
        self._model = model
        self._base_url = base_url.strip().rstrip("/")
        self._api_key = api_key
        #: The declared width, sent on every request unless this endpoint proved it refuses the
        #: parameter (D2 甲a). None means "nobody declared one" — today's request, byte for byte.
        self._dimension = dimension
        self.batch_size = self._initial_batch_size(batch_size)
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str | None:
        """Optional credential: an internal endpoint usually needs none (unlike DashScope)."""
        if self._api_key:
            return self._api_key
        return os.environ.get(_KEY_ENV_VAR) if _KEY_ENV_VAR else None

    def _key(self) -> tuple[str, str]:
        return (self._base_url, str(self._model or ""))

    def _initial_batch_size(self, explicit: int | None) -> int:
        """An explicit cap wins; otherwise the ladder's top, or where this endpoint left off."""
        if explicit is not None:
            return max(1, explicit)
        return _BATCH_CAPS.get(self._key(), BATCH_LADDER[0])

    def _sends_dimension(self) -> bool:
        return self._dimension is not None and self._key() not in _NO_DIMENSION_PARAM

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]:
        """Embed texts in input order; ``text_type`` is not transmitted (the shape has no such knob)."""
        if not texts:
            return []
        results: list[EmbeddingResult] = []
        index = 0
        while index < len(texts):
            batch = list(texts[index : index + self.batch_size])
            batch_results, consumed = await self._embed_with_healing(batch)
            results.extend(batch_results)
            index += consumed
        return results

    async def _embed_with_healing(self, batch: list[str]) -> tuple[list[EmbeddingResult], int]:
        """Send one batch and heal it in place, so ``index_chunks`` only ever sees real failures.

        The order is the one the spec fixed (D3): a multi-row rejection means the *batch* is too
        big, so the ladder steps down and the same batch is re-sent; only a single-row batch that
        is still carrying ``dimensions`` can blame the parameter, and dropping it is the last try.
        Both healings are remembered per endpoint, so the next process's first second is cheaper
        but never required — a fresh process simply walks the ladder again.
        """
        size = len(batch)
        send_dimension = self._sends_dimension()
        while True:
            try:
                results = await self._embed_batch(batch[:size], dimension=self._dimension if send_dimension else None)
                return results, size
            except _Rejected as exc:
                if size > 1:
                    smaller = next((rung for rung in BATCH_LADDER if rung < size), None)
                    if smaller is None:
                        raise EmbedderError(str(exc)) from exc
                    logger.info("embedding endpoint %s refused %d rows; stepping down to %d", self._key()[0], size, smaller)
                    size = smaller
                    self.batch_size = smaller  # the rest of this run stays there too
                    _BATCH_CAPS[self._key()] = smaller
                    continue
                if send_dimension:
                    logger.info("embedding endpoint %s refused the dimensions parameter; dropping it", self._key()[0])
                    send_dimension = False
                    _NO_DIMENSION_PARAM.add(self._key())
                    continue
                raise EmbedderError(str(exc)) from exc

    async def _embed_batch(self, texts: list[str], *, dimension: int | None) -> list[EmbeddingResult]:
        payload: dict = {"model": self._model, "input": texts}
        if dimension is not None:
            payload["dimensions"] = dimension
        body = await self._post_with_retry(payload)
        items = body.get("data") or []
        by_index = {int(item.get("index", position)): item for position, item in enumerate(items)}
        results: list[EmbeddingResult] = []
        for position in range(len(texts)):
            item = by_index.get(position)
            if item is None:
                raise EmbedderError(f"embedding response is missing index {position}")
            dense = [float(value) for value in (item.get("embedding") or [])]
            if not dense:
                raise EmbedderError(f"embedding response for index {position} carries an empty vector")
            results.append(EmbeddingResult(dense=dense, sparse=SparseVector(indices=[], values=[])))
        return results

    async def _post_with_retry(self, payload: dict) -> dict:
        url = join_endpoint(self._base_url, _EMBEDDINGS_PATH)
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
                    last_error = EmbedderError(f"embedding request failed: {exc}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error from exc
                if response.status_code in (401, 403):
                    raise EmbedderAuthError(f"embedding endpoint rejected the API key (HTTP {response.status_code})")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = EmbedderError(f"embedding endpoint HTTP {response.status_code}: {response.text[:200]}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error
                if response.status_code != 200:
                    raise _Rejected(f"embedding endpoint HTTP {response.status_code}: {response.text[:200]}")
                try:
                    return response.json()
                except ValueError as exc:
                    raise EmbedderError(f"embedding endpoint returned non-JSON: {response.text[:200]}") from exc
            raise last_error or EmbedderError("embedding request failed")
        finally:
            if close_client:
                await client.aclose()
