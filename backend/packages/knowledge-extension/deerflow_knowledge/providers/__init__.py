"""Curated provider allowlist for the three pluggable RAG legs (spec 2026-09-14 §4.1).

Embedding, rerank, and document parsing are not LangChain models, so they cannot
reuse the ``models:`` entry mechanism (see spec §3.0 / §4.1). They pick their
provider by a **curated id** instead: the admin API submits the id, and this table
maps it to the implementation, the endpoint key, and the secret's environment
fallback. Same shape as :data:`deerflow.config.models_config.PROVIDER_ALLOWLIST`,
and the same reason — accepting a free-text class path here would be a
dynamic-import surface on par with ``plugins:``.

Implementations are stored as strings so this module stays import-light: the
provider classes arrive with their own tasks (P1 rerank, P2 parse, P3 embedding),
and nothing here imports them eagerly.
"""

from __future__ import annotations

from dataclasses import dataclass

from deerflow_knowledge.messages import bilingual


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """One allowlisted provider: what to build, where to point it, how to authenticate."""

    leg: str
    provider_id: str
    #: ``module.path:ClassName`` — resolved lazily by the leg that owns it.
    implementation: str
    #: Which field of the target names the endpoint (mirrors the model-provider
    #: convention: OpenAI-compatible and Anthropic clients take ``base_url``).
    endpoint_key: str = "base_url"
    #: Request path, when the provider's shape is fixed.
    path: str | None = None
    #: Environment variable backing this provider's secret, or ``None`` when it needs none.
    secret_env_var: str | None = None
    #: Whether one call returns dense *and* sparse. Only such a provider may be paired
    #: with ``embedding_sparse_source=provider`` (spec §4.2 cross-check).
    emits_sparse: bool = False
    #: Whether the implementation pins the dense width in its own request, so it never
    #: needs the runtime dimension probe (spec §4.2 维度 #1). DashScope sends
    #: ``parameters.dimension``; a generic ``/v1/embeddings`` endpoint does not.
    pins_dimension: bool = False
    #: Whether the implementation takes (and sends) a model name at all. A TEI service serves
    #: exactly one model per instance and has no ``model`` field in its request, so its clients
    #: take no such argument — the leg's factory reads this flag instead of matching on the
    #: provider id (spec 2026-09-24 §4.3).
    takes_model: bool = True
    #: Whether the vendor fixes the endpoint itself (spec 2026-09-17 §3 D1). Always agrees with
    #: :attr:`default_endpoint` being set — the two are one rule, pinned by a single test. The
    #: *retrieval* rows report it to the UI; the ASR row deliberately does not, because the lock
    #: it used to drive was retired by the 2026-09-25 endpoint unlock (the address stays the
    #: admin's to set, and the flag's only remaining effect there is the grey placeholder).
    has_fixed_endpoint: bool = False
    #: The vendor's own endpoint, used when ``rag.embedding_base_url`` is empty. A plain
    #: string on purpose: importing an implementation module for the constant would defeat
    #: this module's import-light contract, so a test pins it against the class constant
    #: instead (see ``test_the_dashscope_default_endpoint_has_not_drifted``).
    default_endpoint: str | None = None


#: leg -> provider id -> spec. Adding a provider means adding a row here, never
#: accepting an id from the caller that is not in the table.
PROVIDER_ALLOWLIST: dict[str, dict[str, ProviderSpec]] = {
    "embedding": {
        "dashscope": ProviderSpec(
            leg="embedding",
            provider_id="dashscope",
            implementation="deerflow_knowledge.embedder:DashScopeEmbedder",
            path="/api/v1/services/embeddings/text-embedding/text-embedding",
            secret_env_var="DASHSCOPE_EMBEDDING_API_KEY",
            emits_sparse=True,
            pins_dimension=True,
            # The platform's address, not the admin's to set — so the UI shows it read-only.
            has_fixed_endpoint=True,
            default_endpoint="https://dashscope.aliyuncs.com",
        ),
        "volcengine-ark": ProviderSpec(
            leg="embedding",
            provider_id="volcengine-ark",
            implementation="deerflow_knowledge.embedder_ark:ArkEmbedder",
            # Only the multimodal endpoint exposes the sparse half; the text one
            # (`/api/v3/embeddings`, OpenAI-shaped and batchable) has no such parameter.
            path="/api/v3/embeddings/multimodal",
            secret_env_var="ARK_API_KEY",
            emits_sparse=True,
            # The adapter always sends `dimensions` (born at 2048, collections are 1024), so
            # the width is certified in the request and needs no runtime probe.
            pins_dimension=True,
            has_fixed_endpoint=True,
            default_endpoint="https://ark.cn-beijing.volces.com",
        ),
        "openai-compatible": ProviderSpec(
            leg="embedding",
            provider_id="openai-compatible",
            implementation="deerflow_knowledge.embedder_openai:OpenAICompatibleEmbedder",
            path="/v1/embeddings",
            secret_env_var="RAG_EMBEDDING_API_KEY",
        ),
    },
    "rerank": {
        "dashscope": ProviderSpec(
            leg="rerank",
            provider_id="dashscope",
            implementation="deerflow_knowledge.reranker:DashScopeReranker",
            path="/compatible-api/v1/reranks",
            secret_env_var="DASHSCOPE_RERANK_API_KEY",
            # The same rule as the embedding rows (spec 2026-09-17 alignment §3 D3): this vendor
            # fixes its own endpoint, so the settings row is locked by *capability*, not by name.
            # The literal is kept equal to `reranker.DASHSCOPE_RERANK_BASE_URL` by a test, because
            # this module is deliberately import-light.
            has_fixed_endpoint=True,
            default_endpoint="https://dashscope.aliyuncs.com",
        ),
        "generic-rerank": ProviderSpec(
            leg="rerank",
            provider_id="generic-rerank",
            implementation="deerflow_knowledge.reranker_generic:GenericReranker",
            path="/rerank",
            secret_env_var="RAG_RERANK_API_KEY",
        ),
        "tei-rerank": ProviderSpec(
            leg="rerank",
            provider_id="tei-rerank",
            implementation="deerflow_knowledge.reranker_tei:TEIReranker",
            # The one route TEI mounts; its request has no model field either (one instance
            # serves one model), hence the flag below.
            path="/rerank",
            secret_env_var="RAG_RERANK_API_KEY",
            takes_model=False,
        ),
    },
    "parse": {
        "mineru-cloud": ProviderSpec(
            leg="parse",
            provider_id="mineru-cloud",
            implementation="deerflow_knowledge.parser:MineruCloudParseProvider",
            path="/api/v4",
            secret_env_var="MINERU_API_TOKEN",
        ),
        "mineru-local": ProviderSpec(
            leg="parse",
            provider_id="mineru-local",
            implementation="deerflow_knowledge.parse_local:MineruLocalParseProvider",
            path="/v1/parse/jobs",
            # The local MinerU service ships without auth (spec §8.2), so there is no
            # environment fallback to fall back to.
            secret_env_var=None,
        ),
    },
    # Not a leg of its own in the retrieval sense — this is the *second* endpoint a
    # deployment may point at when `embedding_sparse_source=external`, i.e. a service
    # that returns sparse vectors only. The shape is pinned to Text Embeddings
    # Inference (`POST /embed_sparse`, `{"inputs": [...]}` → `[[{index, value}]]`,
    # verified against its router source), the one implementation we could check.
    "sparse": {
        "tei-sparse": ProviderSpec(
            leg="sparse",
            provider_id="tei-sparse",
            implementation="deerflow_knowledge.sparse:TEISparseEncoder",
            path="/embed_sparse",
            secret_env_var="RAG_SPARSE_API_KEY",
            # Same rule as the TEI rerank row: one instance serves one model, and the request
            # (`{"inputs": [...]}`) carries no model field.
            takes_model=False,
        ),
    },
}


def provider_ids(leg: str) -> tuple[str, ...]:
    """The allowlisted ids for *leg*, in declaration order (the UI renders these)."""
    if leg not in PROVIDER_ALLOWLIST:
        raise ValueError(bilingual(f"未知的 RAG provider 腿 {leg!r}；可选 {sorted(PROVIDER_ALLOWLIST)}", f"Unknown RAG provider leg {leg!r}; expected one of {sorted(PROVIDER_ALLOWLIST)}"))
    return tuple(PROVIDER_ALLOWLIST[leg])


def resolve_provider(leg: str, provider_id: str) -> ProviderSpec:
    """Resolve *provider_id* for *leg*, refusing anything outside the allowlist."""
    if leg not in PROVIDER_ALLOWLIST:
        raise ValueError(bilingual(f"未知的 RAG provider 腿 {leg!r}；可选 {sorted(PROVIDER_ALLOWLIST)}", f"Unknown RAG provider leg {leg!r}; expected one of {sorted(PROVIDER_ALLOWLIST)}"))
    spec = PROVIDER_ALLOWLIST[leg].get(provider_id)
    if spec is None:
        raise ValueError(bilingual(f"未知的 {leg} provider {provider_id!r}；可选 {provider_ids(leg)}", f"Unknown {leg} provider {provider_id!r}; expected one of {provider_ids(leg)}"))
    return spec


def secret_env_var(leg: str, provider_id: str) -> str | None:
    """The environment variable backing this provider's secret, or ``None`` if it needs none."""
    return resolve_provider(leg, provider_id).secret_env_var
