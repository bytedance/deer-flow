"""Sparse encoders for the two routes that are not the dense provider (spec §4.2).

``bm25`` — local, zero-model, deterministic: the safest choice for an air-gapped
deployment, at the cost of semantic quality. **It has no idf and no length
normalisation**, because the index is built chunk-by-chunk with no corpus in sight; what
remains is BM25's term-frequency saturation curve, which makes the query and document
sides exactly symmetric. That symmetry is not a nicety: §4.2 requires both sides to use
the same algorithm, or the scores would not be comparable.

Chinese text is tokenised as **deterministic character bigrams**, deliberately *not* an
optional jieba. The memory/FTS5 precedent makes jieba optional; here that would make the
index space depend on which environment indexed the document, and §4.2 pins the opposite
("稀疏的 index 空间必须统一"). Bigrams need no dictionary, no model, and no download.

``external`` — a dedicated sparse service. The shape is pinned from upstream source
(``huggingface/text-embeddings-inference``, ``router/src/http/types.rs`` + ``server.rs``):
``POST /embed_sparse`` with ``{"inputs": [...]}`` → ``[[{"index", "value"}, ...], ...]``.
TEI serves one model per instance, so no model field is sent; ``sparse_model`` stays in
the config contract for services that need one.

Both encoders return Qdrant ``SparseVector``s, which is what keeps the collection schema
and the retrieval code untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from collections import Counter
from collections.abc import Sequence

import httpx
from qdrant_client.models import SparseVector

from deerflow.knowledge.embedder import EmbedderAuthError, EmbedderError, RagConfigurationError
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.providers import secret_env_var

logger = logging.getLogger(__name__)

_SPARSE_PATH = "/embed_sparse"
_KEY_ENV_VAR = secret_env_var("sparse", "tei-sparse")
DEFAULT_BATCH_LIMIT = 32

#: BM25's saturation constant (the standard default); no idf, so no k1/b pairing.
_BM25_K1 = 1.2
#: Hashed term indices stay well inside Qdrant's uint32 range.
_INDEX_MODULUS = 2**31 - 1

#: One alphanumeric run (ASCII) or one CJK run — everything else is a separator.
_TOKEN_RUN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """Deterministic tokens: ASCII words as-is, CJK runs as character bigrams.

    A single-character CJK run stays itself (there is no bigram to form); longer runs
    contribute every adjacent pair.
    """
    tokens: list[str] = []
    for run in _TOKEN_RUN_RE.findall(text.lower()):
        if run.isascii():
            tokens.append(run)
        elif len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _index_of(token: str) -> int:
    """Stable token → index (blake2b, so the mapping never depends on PYTHONHASHSEED)."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % _INDEX_MODULUS


class BM25SparseEncoder:
    """Term-frequency sparse encoder with BM25 saturation (no corpus, no idf)."""

    def __init__(self, *, k1: float = _BM25_K1) -> None:
        self._k1 = k1

    async def encode(self, texts: Sequence[str], *, text_type: str = "document") -> list[SparseVector]:
        """``text_type`` is accepted for interface parity — BM25 treats both sides alike."""
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> SparseVector:
        frequencies = Counter(_index_of(token) for token in _tokenize(text))
        weights = {index: count * (self._k1 + 1) / (count + self._k1) for index, count in frequencies.items()}
        indices = sorted(weights)
        return SparseVector(indices=indices, values=[weights[index] for index in indices])


class TEISparseEncoder:
    """Sparse encoder for a Text Embeddings Inference ``/embed_sparse`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None = None,
        batch_size: int = DEFAULT_BATCH_LIMIT,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not (base_url or "").strip():
            raise RagConfigurationError(bilingual("external 稀疏来源需要服务地址：请设置 rag.sparse_base_url", "The external sparse source needs a service address: set rag.sparse_base_url"))
        self._base_url = base_url.strip().rstrip("/")
        self._api_key = api_key
        self.batch_size = max(1, batch_size)
        self._max_retries = max(1, max_retries)
        self._retry_backoff = retry_backoff_seconds
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        return os.environ.get(_KEY_ENV_VAR) if _KEY_ENV_VAR else None

    async def encode(self, texts: Sequence[str], *, text_type: str = "document") -> list[SparseVector]:
        """``text_type`` is accepted for parity; TEI applies prompts server-side, not per request."""
        if not texts:
            return []
        vectors: list[SparseVector] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            vectors.extend(await self._encode_batch(batch))
        return vectors

    async def _encode_batch(self, texts: list[str]) -> list[SparseVector]:
        payload = {"inputs": texts}
        rows = await self._post_with_retry(payload)
        if len(rows) != len(texts):
            raise EmbedderError(f"sparse service returned {len(rows)} vectors for {len(texts)} texts")
        return [SparseVector(indices=[int(entry["index"]) for entry in row], values=[float(entry["value"]) for entry in row]) for row in rows]

    async def _post_with_retry(self, payload: dict) -> list[list[dict]]:
        url = f"{self._base_url}{_SPARSE_PATH}"
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
                    last_error = EmbedderError(f"sparse service request failed: {exc}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error from exc
                if response.status_code in (401, 403):
                    raise EmbedderAuthError(f"sparse service rejected the API key (HTTP {response.status_code})")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = EmbedderError(f"sparse service HTTP {response.status_code}: {response.text[:200]}")
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
                    raise last_error
                if response.status_code != 200:
                    raise EmbedderError(f"sparse service HTTP {response.status_code}: {response.text[:200]}")
                try:
                    rows = response.json()
                except ValueError as exc:
                    raise EmbedderError(f"sparse service returned non-JSON: {response.text[:200]}") from exc
                if not isinstance(rows, list):
                    raise EmbedderError(f"sparse service returned a non-array payload: {str(rows)[:200]}")
                return rows
            raise last_error or EmbedderError("sparse service request failed")
        finally:
            if close_client:
                await client.aclose()
