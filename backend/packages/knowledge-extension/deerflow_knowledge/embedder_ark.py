"""Volcengine Ark embedding client — the second provider that returns both halves in one call.

Ark's multimodal embedding endpoint answers ``data.embedding`` (dense) **and**
``data.sparse_embedding`` (``[{index, value}]``) for the same item, which is what lets a
deployment name it as ``embedding_sparse_source=provider`` instead of standing up a separate
sparse service (spec 2026-09-17). Three things make this shape unlike DashScope's:

- **One item per call.** ``input`` carries one item's *content parts* (text/image/video), not
  a list of texts, so ``batch_size`` is 1 and N texts cost N round trips. Measured on
  2026-09-17 that is about 1.3x the wall clock of DashScope's 20-rows-per-call, not 20x: the
  per-item compute dominates and this endpoint's round trip is ~0.19 s.
- **The width must be declared.** The model is born at 2048 while the collections are fixed at
  1024, so ``dimensions`` goes out on every request. It arrives as a constructor argument and
  is never decided here (spec §3 D3) — the factory injects it.
- **No query/document knob.** ``text_type`` is accepted for interface parity and *not*
  transmitted; both sides have to share one sparse index space anyway.

Failures reuse the shared ``EmbedderError`` / ``EmbedderAuthError`` so the worker's "one bad
batch never aborts the document" contract behaves identically across providers. The key's
environment fallback comes from the curated allowlist, so the name this client reads and the
name the settings API reports cannot drift.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence

import httpx
from qdrant_client.models import SparseVector

from deerflow_knowledge.embedder import EmbedderAuthError, EmbedderError, EmbeddingResult
from deerflow_knowledge.providers import secret_env_var

logger = logging.getLogger(__name__)

#: The vendor's own host; the allowlist carries the same string as ``default_endpoint`` and a
#: test keeps the two equal (this module must not be imported *from* the allowlist).
ARK_BASE_URL = "https://ark.cn-beijing.volces.com"
_MULTIMODAL_PATH = "/api/v3/embeddings/multimodal"
_KEY_ENV_VAR = secret_env_var("embedding", "volcengine-ark")


class ArkEmbedder:
    """Dense+sparse embedder for Volcengine Ark's multimodal embedding endpoint."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = ARK_BASE_URL,
        dimension: int,
        batch_size: int = 1,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        """``dimension`` has no default on purpose: the target width belongs to the factory,
        which always injects it (spec §3 D3). A built-in fallback would make "the factory
        injected it" and "the adapter guessed" indistinguishable — and the request still
        carries the same number, so no test could tell them apart."""
        if model is None:
            from deerflow.config.app_config import get_app_config

            model = get_app_config().rag.embedding_model
        self._model = model
        self._api_key = api_key  # resolved lazily so env-only usage never passes keys around
        self._base_url = base_url.rstrip("/")
        self._dimension = dimension
        #: One item per request is the endpoint's shape, not a tuning choice.
        self.batch_size = max(1, batch_size)
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]:
        """Embed texts in input order; ``text_type`` is not transmitted (the shape has no knob)."""
        if not texts:
            return []
        results: list[EmbeddingResult] = []
        for start in range(0, len(texts), self.batch_size):
            for text in texts[start : start + self.batch_size]:
                results.append(await self._embed_one(text))
        return results

    async def _embed_one(self, text: str) -> EmbeddingResult:
        payload = {
            "model": self._model,
            "input": [{"type": "text", "text": text}],
            "dimensions": self._dimension,
            "sparse_embedding": {"type": "enabled"},
        }
        item = (await self._post_with_retry(payload)).get("data")
        if not isinstance(item, dict):
            raise EmbedderError(f"embedding response is missing the 'data' object: {str(item)[:200]}")
        dense = [float(value) for value in (item.get("embedding") or [])]
        if len(dense) != self._dimension:
            raise EmbedderError(f"embedding response is {len(dense)} wide, expected {self._dimension}")
        entries = item.get("sparse_embedding") or []
        return EmbeddingResult(
            dense=dense,
            sparse=SparseVector(
                indices=[int(entry["index"]) for entry in entries],
                values=[float(entry["value"]) for entry in entries],
            ),
        )

    async def _post_with_retry(self, payload: dict) -> dict:
        url = f"{self._base_url}{_MULTIMODAL_PATH}"
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
                    raise EmbedderError(f"embedding endpoint HTTP {response.status_code}: {response.text[:200]}")
                try:
                    return response.json()
                except ValueError as exc:
                    raise EmbedderError(f"embedding endpoint returned non-JSON: {response.text[:200]}") from exc
            raise last_error or EmbedderError("embedding request failed")
        finally:
            if close_client:
                await client.aclose()

    def _read_api_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        return os.environ.get(_KEY_ENV_VAR) if _KEY_ENV_VAR else None
