"""Build the configured embedder — dense provider, sparse route, and their wiring (spec §4.2).

Four things are decided here, and they are the reason this is a module rather than a call
to one class:

1. **Who embeds.** ``rag.embedding_provider`` resolves through the curated allowlist (same
   rule as the rerank and parse legs: a caller never supplies a class path).
2. **Who supplies the sparse half.** ``rag.embedding_sparse_source`` picks the provider
   itself, a separate sparse service, or local BM25. When it is not the provider, 甲's
   composition adapter holds both halves and still returns one ``EmbeddingResult`` per text,
   so no caller changes.
3. **Which dimension we are in.** The Qdrant collections are created at 1024 and are not
   recreated on a dimension change (§4.2 维度 #2), so the width must be certified. A provider
   that pins the dimension in its request (DashScope) needs nothing; any other provider is
   measured once per process — reused from the first real embedding, so the certification
   costs no extra round trip — and a non-1024 width is refused with a pointer at the rebuild
   entry, which is the documented way out (§4.2 维度 #4).
4. **Whether the sparse half actually arrived.** ``sparse_source=provider`` trusts the
   allowlist and the model-level probe, but a probe cannot cover every call, so the same
   build wraps the result in a check that refuses an empty sparse vector (D5).
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.config.app_config import get_app_config
from deerflow.knowledge.embed_identity import identity_from_rag
from deerflow.knowledge.embedder import ComposedEmbedder, Embedder, RagConfigurationError, SparseHalfMissingError
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.providers import resolve_provider
from deerflow.knowledge.sparse import BM25SparseEncoder

logger = logging.getLogger(__name__)

#: The width every deployment starts at, and the one the unsuffixed collections were built
#: with. A declaration replaces it per deployment (spec 2026-09-26 D1 乙); an undeclared one
#: keeps it, which is what makes an untouched deployment byte-for-byte what it always was.
DEFAULT_COLLECTION_DIMENSION = 1024

#: (provider id, base_url, model) → measured dense width. Process-local on purpose: it
#: certifies *this* deployment's endpoint, and a config change alters the key anyway.
_PROBED_DIMENSIONS: dict[tuple[str, str, str], int] = {}

_REBUILD_HINT = bilingual(
    "请改用该模型支持的维度（到「设置 → 模型 → 功能模型 → 高级设置 → 维度」改，改值会触发全库重建），或换模型。",
    "Use a model that returns the width in force (change it under Settings → Models → Functional models → Advanced → Dimension; a change rebuilds every collection), or switch models.",
)


def effective_dimension(rag: Any | None = None) -> int:
    """The width this deployment's vectors are written at: the declared one, else the default.

    One reader for the whole runtime — the store's collection names, the guards below and the
    save-time probe all have to answer "how wide is the library" the same way, or a save would
    be judged against a width the writer never uses.
    """
    if rag is None:
        rag = get_app_config().rag
    return rag.embedding_dimension or DEFAULT_COLLECTION_DIMENSION


def dimension_mismatch_message(measured: int, expected: int) -> str:
    """The one wording for a wrong dense width.

    Two callers refuse on this fact — the once-per-process runtime guard here and the save-time
    probe (``app.gateway.routers.rag_config``) — and they must not word it twice: the admin sees
    the same sentence while editing as the ingest would have shown days later.
    """
    return f"{bilingual(f'嵌入模型返回 {measured} 维，而当前生效宽度是 {expected} 维 ⇒ 拒绝启用。', f'The embedding model returned {measured} dimensions while the width in force is {expected} — refusing to enable it.')} {_REBUILD_HINT}"


class _DimensionCheckedEmbedder:
    """Measure the dense width once per process; refuse anything but the deployment's width.

    The refusal is a ``ValueError``, never an ``EmbedderError``: ``index_chunks`` treats
    ``EmbedderError`` as a soft, per-batch failure and would otherwise bury a configuration
    mistake as "some chunks failed".
    """

    def __init__(self, inner: Embedder, *, key: tuple[str, str, str], expected: int) -> None:
        self._inner = inner
        self._key = key
        self._expected = expected

    @property
    def batch_size(self) -> int:
        return self._inner.batch_size

    async def embed(self, texts, *, text_type: str = "document"):
        results = await self._inner.embed(texts, text_type=text_type)
        if results and self._key not in _PROBED_DIMENSIONS:
            measured = len(results[0].dense)
            _PROBED_DIMENSIONS[self._key] = measured
            logger.info("embedding provider %s measured at %d dimensions", self._key[0], measured)
            if measured != self._expected:
                raise RagConfigurationError(dimension_mismatch_message(measured, self._expected))
        return results


class _SparseHalfCheckedEmbedder:
    """Refuse a provider that promised the sparse half and returned an empty one.

    Semantically the *opposite* of ``_DimensionCheckedEmbedder``, and deliberately not
    modelled on its once-per-process verdict. That precedent caches **before** it raises
    (``_PROBED_DIMENSIONS[key] = measured`` sits above ``if measured != 1024``), which is
    only safe because a wrong width is refused downstream anyway: Qdrant rejects the write.
    An empty sparse vector is a *legitimate value* — letting it through once means it is
    really stored, and a "judged already" cache would skip the check on every later call,
    i.e. shout once and stay silent forever, which is worse than the silence we started
    with. So the check runs on every embedding and keeps raising while the answer holds.

    The refusal is a ``SparseHalfMissingError`` so the capability probe can read an empty
    sparse half as the model's answer (``unsupported``) rather than as "could not check".
    """

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner

    @property
    def batch_size(self) -> int:
        return self._inner.batch_size

    async def embed(self, texts, *, text_type: str = "document"):
        results = await self._inner.embed(texts, text_type=text_type)
        if results and not results[0].sparse.indices:
            raise SparseHalfMissingError("嵌入 provider 返回了空的稀疏向量 ⇒ embedding_sparse_source 不能是 'provider'；请改为「独立稀疏服务」（external）或「本地 BM25」（bm25）。")
        return results


def build_embedder(config: Any | None = None, *, rag: Any | None = None, client: Any | None = None) -> Embedder:
    """Instantiate the configured embedder (dense + sparse route).

    ``client`` is forwarded to whichever HTTP clients are built (tests and deployments with
    custom transports/proxies pass one); the providers create their own when it is omitted.

    ``rag`` overrides the RAG section for this call. The settings PUT validates a configuration
    it has *not written yet*, so it passes the merge it is about to persist — reusing the live
    ``config.rag`` there would answer for the file being replaced (spec 2026-09-16 §3 D3).

    The returned embedder carries ``.identity`` (spec 2026-10-04 D2): which coordinate space
    its vectors land in, taken from ``rag`` here rather than re-read from config later.

    Raises ``ValueError`` when the configuration cannot describe a usable embedder: a
    dense-only provider paired with ``sparse_source=provider``, a missing sparse endpoint,
    a missing address, or a declared dimension the model cannot honour (caught on the first
    real call, not here).
    """
    if config is None:
        config = get_app_config()
    if rag is None:
        rag = config.rag
    provider_id = rag.embedding_provider
    sparse_source = rag.embedding_sparse_source
    spec = resolve_provider("embedding", provider_id)

    if sparse_source == "provider" and not spec.emits_sparse:
        cn = f"嵌入 provider {provider_id!r} 只输出稠密向量 ⇒ embedding_sparse_source 不能是 'provider'；请改为「独立稀疏服务」（external）或「本地 BM25」（bm25）。"
        en = f"Provider {provider_id!r} emits dense only ⇒ embedding_sparse_source cannot be 'provider'; use a separate sparse service ('external') or local BM25 ('bm25')."
        raise RagConfigurationError(bilingual(cn, en))

    expected = effective_dimension(rag)
    dense = _build_dense(spec, rag, expected, client)
    identity = identity_from_rag(rag)
    if sparse_source == "provider":
        # The provider was trusted to supply both halves (allowlist + the model-level probe);
        # this is the fallback for the corners the probe could not reach (D5).
        checked = _SparseHalfCheckedEmbedder(dense)
        checked.identity = identity
        return checked

    sparse = _build_sparse(rag, sparse_source, client)
    composed = ComposedEmbedder(dense=dense, sparse=sparse)
    composed.identity = identity
    return composed


def _build_dense(spec, rag, expected: int, client: Any | None) -> Embedder:
    """Build the dense half. The allowlist row says whether this vendor ships a default hint.

    A stored ``rag.embedding_base_url`` is the one and only address (spec 2026-09-25
    rag-endpoint-unlock D1 乙: the silent ``spec.default_endpoint`` fallback is gone — the
    settings UI shows the default as a grey hint and requires an address).
    """
    from deerflow.reflection import resolve_variable

    kwargs: dict = {"client": client}
    base_url = (rag.embedding_base_url or "").strip()
    if not base_url:
        raise RagConfigurationError(bilingual(f"嵌入 provider {spec.provider_id!r} 需要 rag.embedding_base_url", f"Embedding provider {spec.provider_id!r} requires rag.embedding_base_url"))
    if not (rag.embedding_model or "").strip():
        # A-1 (spec 2026-09-30 D1): the model name has no default any more — an undeclared one is
        # refused here, before the adapter's own None-fallback could silently re-read the config.
        cn = f"嵌入 provider {spec.provider_id!r} 需要 rag.embedding_model（没有默认值，请在 rag: 段声明）"
        en = f"Embedding provider {spec.provider_id!r} requires rag.embedding_model (no default; declare it in the rag: section)"
        raise RagConfigurationError(bilingual(cn, en))
    kwargs["base_url"] = base_url
    if rag.embedding_model:
        kwargs["model"] = rag.embedding_model
    if rag.embedding_api_key:
        kwargs["api_key"] = rag.embedding_api_key
    if spec.pins_dimension:
        # The width is injected, never inferred by the implementation (spec 2026-09-17 §3 D3):
        # a vendor whose model is born wider than our collections must be *told* the target,
        # and the guard that would catch a wrong width only fires on a real call.
        kwargs["dimension"] = expected
    elif rag.embedding_dimension is not None:
        # A declaration is also *sent* on the generic leg (spec 2026-09-26 D2 甲a): asking for
        # the width is what makes a model whose default is not 1024 usable at all. Undeclared
        # stays undeclared — that request body is byte for byte what it always was.
        kwargs["dimension"] = rag.embedding_dimension
    return _guard(resolve_variable(spec.implementation)(**kwargs), spec, rag, expected=expected)


def _guard(embedder: Embedder, spec, rag, *, expected: int) -> Embedder:
    """Wrap a provider that cannot self-certify its width in the one-shot probe.

    The judgement comes from the allowlist row, not from the constructed object: a test
    double (or any duck-typed embedder) must not be mistaken for an unverified endpoint.
    """
    if spec.pins_dimension or rag.embedding_dimension is not None:
        return embedder
    return _DimensionCheckedEmbedder(embedder, key=(spec.provider_id, str(rag.embedding_base_url or ""), str(rag.embedding_model or "")), expected=expected)


def _build_sparse(rag, sparse_source: str, client: Any | None) -> Any:
    if sparse_source == "bm25":
        return BM25SparseEncoder()
    spec = resolve_provider("sparse", rag.sparse_provider) if rag.sparse_provider else None
    if spec is None:
        raise RagConfigurationError(bilingual("embedding_sparse_source='external' 需要 rag.sparse_provider（受控 allowlist）", "embedding_sparse_source='external' requires rag.sparse_provider (curated allowlist)"))
    from deerflow.reflection import resolve_variable

    kwargs: dict = {"base_url": rag.sparse_base_url, "client": client}
    if rag.sparse_api_key:
        kwargs["api_key"] = rag.sparse_api_key
    return resolve_variable(spec.implementation)(**kwargs)
