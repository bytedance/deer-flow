"""DashScope (Aliyun Bailian) embedding client (spec §3.3).

One call per batch yields **both** the dense and the sparse vector via
``output_type=dense&sparse`` — the reason the whole embedding/rerank选型 moved
to Bailian (bge-m3's OpenAI-compatible API never exposes the sparse path).
The sparse payload (``[{index, value, token}, ...]``) is converted to Qdrant
``SparseVector`` indices/values, dropping the display-only ``token`` strings.

Contract (verified against the Aliyun Model Studio docs):
- ``POST {base_url}/api/v1/services/embeddings/text-embedding/text-embedding``
- body ``{"model", "input": {"texts": [...]}, "parameters": {"dimension",
  "output_type": "dense&sparse", "text_type": "document"|"query"}}``
- rows per call are capped **per model** (10 for most, 20 for ``qwen3.7-text-embedding``) →
  client-side batching, defaulting to the lowest measured cap; retrieval tasks distinguish
  ``query`` vs ``document`` text types.
- Failures: non-2xx HTTP, or a 2xx body with a non-empty ``code``.

The API key always comes from ``DASHSCOPE_EMBEDDING_API_KEY`` — never from the
caller (consistent with the MinerU token rule).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from qdrant_client.models import SparseVector

from deerflow.config.rag_config_file import SECRET_ENV_VARS, configured_rag_secret

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"
_EMBEDDING_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"
_KEY_ENV_VAR = SECRET_ENV_VARS["embedding_api_key"]

#: The lowest per-call row cap measured on the platform, and therefore what every model gets by
#: default. Unknown models stay on the safe side on purpose: the worst case is one extra round trip,
#: not a batch the platform refuses wholesale (2026-09-17: 20 rows against v3/v4 answers HTTP 400
#: `batch size is invalid, it should not be larger than 10`). This only affects how many requests an
#: ingest makes — never correctness, and never retrieval latency (queries are single rows).
DASHSCOPE_SAFE_BATCH_SIZE = 10

#: Models measured to accept more rows per call than the safe default. The table only ever *raises*
#: the cap, so adding a model here is an optimisation while omitting one is merely conservative.
DASHSCOPE_BATCH_SIZES: dict[str, int] = {
    # 20 rows answered 200 for this model (2026-09-17 probe).
    "qwen3.7-text-embedding": 20,
}


def dashscope_batch_size(model: str | None) -> int:
    """Rows per embedding call for this model (see the table above for why this is not one number)."""
    return DASHSCOPE_BATCH_SIZES.get(str(model or ""), DASHSCOPE_SAFE_BATCH_SIZE)


class EmbedderError(Exception):
    """Any DashScope embedding failure after retries are exhausted."""


class EmbedderAuthError(EmbedderError):
    """Missing or rejected API key (never retried)."""


class RagConfigurationError(ValueError):
    """The configuration cannot describe a usable leg — refused rather than retried.

    Every leg's configuration-class refusal uses this type, not only the embedding half: the
    rerank factory and the local parser raise it too (spec 2026-09-17 alignment §3 D1). That is
    what makes one gateway handler enough, and it keeps every refusal readable instead of
    arriving as a bare 500 or a wrapped tool error.

    Deliberately a ``ValueError``, not an ``EmbedderError``: ``index_chunks`` treats the
    latter as a *soft* per-batch failure and would bury a configuration mistake as "some
    chunks failed". And deliberately its own type so the gateway can map exactly this class
    to a readable 400 (spec 2026-09-16 §3 D4) without doing the same to every ``ValueError``.
    """


class SparseHalfMissingError(RagConfigurationError):
    """The provider answered, and the sparse half was empty.

    A distinct type because the capability probe has to tell this apart from every other
    refusal: here the model has *answered* "I do not do sparse" (``unsupported``), while an
    unreachable endpoint or a rejected key only means "could not check" (``unverifiable``).
    Both leave the same call as exceptions, so without a type the probe would have to read
    the message. Inherits the gateway's 400 mapping unchanged.
    """


@dataclass(slots=True)
class EmbeddingResult:
    """One text's dense+sparse vector pair from a single DashScope call."""

    dense: list[float]
    sparse: SparseVector


class Embedder(Protocol):
    """What every embedding provider — and the composition adapter — exposes (spec §4.2).

    Structural on purpose: the worker, the indexer, the retrieval tools and the eval
    wrappers only ever touch these two members, so a duck-typed object (real or a test
    stub) keeps working.
    """

    batch_size: int

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]: ...


class SparseEncoder(Protocol):
    """The sparse half, when it comes from somewhere other than the dense provider."""

    async def encode(self, texts: Sequence[str], *, text_type: str = "document") -> list[SparseVector]: ...


class ComposedEmbedder:
    """甲 (spec §4.2): hold a dense source and a sparse source, return one pair per text.

    Callers see exactly what they saw before — one ``embed()`` returning
    ``EmbeddingResult(dense, sparse)`` — which is what keeps the retrieval code, the worker
    and the eval wrappers unchanged when a deployment splits the two halves. The dense
    source may well issue its own batching; this layer only pairs the results.
    """

    def __init__(self, *, dense: Embedder, sparse: SparseEncoder) -> None:
        self._dense = dense
        self._sparse = sparse

    @property
    def batch_size(self) -> int:
        return self._dense.batch_size

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]:
        if not texts:
            return []
        dense_results = await self._dense.embed(texts, text_type=text_type)
        sparse_vectors = await self._sparse.encode(list(texts), text_type=text_type)
        if len(dense_results) != len(sparse_vectors):
            raise EmbedderError(f"sparse encoder returned {len(sparse_vectors)} vectors for {len(dense_results)} texts")
        return [EmbeddingResult(dense=dense.dense, sparse=sparse) for dense, sparse in zip(dense_results, sparse_vectors, strict=True)]


class DashScopeEmbedder:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = DASHSCOPE_BASE_URL,
        dimension: int = 1024,
        batch_size: int | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if model is None:
            from deerflow.config.app_config import get_app_config

            model = get_app_config().rag.embedding_model
        self._model = model
        self._api_key = api_key  # resolved lazily so env-only usage never passes keys around
        self._base_url = base_url.rstrip("/")
        self._dimension = dimension
        # Rows per call follow the *model*: an explicit value wins (tests, custom transports), and
        # otherwise the model's own cap decides — see `dashscope_batch_size`.
        self.batch_size = batch_size if batch_size is not None else dashscope_batch_size(model)
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str:
        key = self._api_key or configured_rag_secret("embedding_api_key") or os.environ.get(_KEY_ENV_VAR)
        if not key:
            raise EmbedderAuthError(f"{_KEY_ENV_VAR} is not set; add it to .env (see .env.example)")
        return key

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]:
        """Embed texts in input order; batches over the limit are split sequentially."""
        if not texts:
            return []
        results: list[EmbeddingResult] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            results.extend(await self._embed_batch(batch, text_type=text_type))
        return results

    async def _embed_batch(self, texts: list[str], *, text_type: str) -> list[EmbeddingResult]:
        payload = {
            "model": self._model,
            "input": {"texts": texts},
            "parameters": {"dimension": self._dimension, "output_type": "dense&sparse", "text_type": text_type},
        }
        body = await self._post_with_retry(payload)
        items = body.get("output", {}).get("embeddings") or []
        by_index = {int(item.get("text_index", i)): item for i, item in enumerate(items)}
        results: list[EmbeddingResult] = []
        for i in range(len(texts)):
            item = by_index.get(i)
            if item is None:
                raise EmbedderError(f"DashScope response missing embedding for text_index {i}")
            sparse_items = item.get("sparse_embedding") or []
            results.append(
                EmbeddingResult(
                    dense=[float(v) for v in (item.get("embedding") or [])],
                    sparse=SparseVector(
                        indices=[int(entry["index"]) for entry in sparse_items],
                        values=[float(entry["value"]) for entry in sparse_items],
                    ),
                )
            )
        return results

    async def _post_with_retry(self, payload: dict) -> dict:
        url = f"{self._base_url}{_EMBEDDING_PATH}"
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
                    last_error = EmbedderError(f"DashScope request failed: {exc}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error from exc
                body = self._decode_body(response)
                if response.status_code in (401, 403):
                    raise EmbedderAuthError(self._error_message(response.status_code, body))
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = EmbedderError(self._error_message(response.status_code, body))
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error
                if response.status_code != 200:
                    raise EmbedderError(self._error_message(response.status_code, body))
                code = str(body.get("code") or "")
                if code:
                    message = self._error_message(response.status_code, body)
                    if "apikey" in code.lower().replace("_", ""):
                        raise EmbedderAuthError(message)
                    raise EmbedderError(message)
                return body
            raise last_error or EmbedderError("DashScope embedding failed")
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
        return f"DashScope embedding failed (HTTP {status_code}): {detail}"
