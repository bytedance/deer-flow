"""Build the configured rerank provider (spec 2026-09-14 §4.1).

Every construction site goes through here on purpose: the online retrieval paths and the
evaluation runner must use the *same* reranker, or an evaluation would grade a different
retriever than the one that serves queries.
"""

from __future__ import annotations

from typing import Any

from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.providers import resolve_provider


def build_reranker(config: Any | None = None, *, rag: Any | None = None) -> Any:
    """Instantiate the rerank provider the configuration selects.

    Raises ``RagConfigurationError`` when the selected provider needs an endpoint the
    configuration never supplied — only DashScope ships a default address. That type (not a bare
    ``ValueError``) is what the gateway maps to a readable 400, so the refusal reaches the caller
    on every path that builds a reranker, including the recall-test route and the eval runner
    (spec 2026-09-17 alignment §3 D1).

    ``rag`` overrides the RAG section for this call, exactly as ``build_embedder`` does: the
    save-time check constructs the legs from the configuration it is *about to write*, which is
    not the live one (spec 2026-09-17 alignment §3 D2).
    """
    if config is None:
        from deerflow.config.app_config import get_app_config

        config = get_app_config()
    section = config.rag if rag is None else rag
    spec = resolve_provider("rerank", section.rerank_provider)

    endpoint = (section.rerank_base_url or "").strip()
    if not endpoint:
        raise RagConfigurationError(
            bilingual(f"重排 provider {spec.provider_id!r} 需要 rag.rerank_base_url", f"rerank_provider={spec.provider_id!r} requires rag.rerank_base_url"),
        )
    if spec.takes_model and not (section.rerank_model or "").strip():
        # A-1 (spec 2026-09-30 D1): required only where the row takes a model — TEI serves its
        # own and must not be asked for one (the kwargs below are gated the same way).
        cn = f"重排 provider {spec.provider_id!r} 需要 rag.rerank_model（没有默认值，请在 rag: 段声明）"
        en = f"rerank_provider={spec.provider_id!r} requires rag.rerank_model (no default; declare it in the rag: section)"
        raise RagConfigurationError(bilingual(cn, en))

    from deerflow.reflection import resolve_variable

    implementation = resolve_variable(spec.implementation)
    kwargs: dict[str, Any] = {}
    if spec.takes_model:
        # The row says whether this client accepts a model at all: TEI's rerank service serves
        # one model per instance and its request has no model field, so handing it one would be
        # a `TypeError` before the first call (spec 2026-09-24 §4.3).
        kwargs["model"] = section.rerank_model
    kwargs["base_url"] = endpoint
    if section.rerank_api_key:
        kwargs["api_key"] = section.rerank_api_key
    return implementation(**kwargs)
