"""Resolve the caption VLM's (model, endpoint, key) triple, and the protocol it speaks.

Both caption legs are raw HTTP calls, and what they send depends on the entry's provider:
the OpenAI shape (``POST {base_url}/chat/completions``) or Anthropic's Messages shape
(``POST {base_url}/v1/messages``). Naming a configured ``models:`` entry supplies the triple
from that entry — which is what lets the settings UI offer a plain model picker instead of
asking for an endpoint and a key that the entry already carries — and the entry's ``use:``
class is what decides the dialect.

There is no second path any more (spec 2026-09-23 D10.3): a value that names no entry is a
configuration error raised by the resolver, not a bare model id pointed at a retired
endpoint, and an entry's address is its own or the one its SDK ships (D10.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deerflow.config.app_config import AppConfig
from deerflow.config.models_config import reverse_lookup_provider

#: Provider-side endpoint keys an entry may carry (OpenAI-compatible vs the DeepSeek adapter).
_ENDPOINT_KEYS: tuple[str, ...] = ("base_url", "api_base")

Dialect = Literal["openai", "anthropic"]

#: Which protocol a caption call speaks, read off the entry's ``use:`` class through the
#: same allowlist ``/api/models`` reports — never a field of its own, because the entry
#: already names the client that serves it. A class the allowlist cannot place is *not*
#: evidence of a third shape, so it keeps the OpenAI one these legs have always sent.
_DIALECT_BY_PROVIDER: dict[str, Dialect] = {"anthropic": "anthropic"}


def _dialect_for(use: str) -> Dialect:
    return _DIALECT_BY_PROVIDER.get(reverse_lookup_provider(use) or "", "openai")


def _sdk_default_endpoint(provider: str | None) -> str | None:
    """The address an entry borrows when it declares none (spec 2026-09-23 D10.2/R1).

    Read from the SDK that will make the call, lazily and without constructing anything, so
    the borrow cannot drift: anthropic exposes its own field default, deepseek a module
    constant. The OpenAI-compatible cell has no such default — its blank would mean OpenAI's
    public cloud — so it answers ``None`` and the caller refuses instead of guessing.
    """
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # `.default_factory()` is the only readable spelling: the field's `.default` is
        # PydanticUndefined (spec R23).
        return ChatAnthropic.model_fields["anthropic_api_url"].default_factory()
    if provider == "deepseek":
        from langchain_deepseek.chat_models import DEFAULT_API_BASE

        return DEFAULT_API_BASE
    return None


@dataclass(frozen=True, slots=True)
class VlmTarget:
    """Where a caption call goes, what it authenticates with, and which protocol it speaks.

    The thinking declarations ride along because the request body's thinking spelling is the
    entry's own (spec 2026-10-02 D1=甲′): ``disable_shape`` / ``enable_shape`` are its declared
    ``when_thinking_*`` shapes, and the two flags mirror the chat-side gate and effort rules
    (``supports_thinking`` downgrades "on" to "off", ``supports_reasoning_effort`` says
    whether the entry takes ``reasoning_effort`` at all). Undeclared means not sent.
    """

    model: str
    base_url: str
    api_key: str | None
    dialect: Dialect
    source: Literal["model_entry"]
    disable_shape: dict | None = None
    supports_reasoning_effort: bool = False
    enable_shape: dict | None = None
    supports_thinking: bool = False


def resolve_vlm_target(config: AppConfig, model: str | None = None) -> VlmTarget:
    """Resolve the caption target for ``model``, defaulting to ``rag.vlm_model``.

    ``model`` names a ``models:`` entry; the video leg passes nothing and shares the chain.
    """
    from deerflow.knowledge.model_target import require_usable_rag_target

    # The declaration is the caller's argument, else ``rag.vlm_model``; everything below that
    # (the RAG default, then the first model) is the shared chain, so both caption legs and
    # the two LLM roles answer the same way. No models at all is a configuration error rather
    # than an empty ``model`` in the request, and a *declared* target whose entry is
    # incomplete is refused here — outside the per-image recovery, so it cannot degrade into
    # placeholders (spec 2026-09-23 D10.1).
    declared = require_usable_rag_target(config, (model or config.rag.vlm_model or "").strip() or None, role="文档图片配文")
    entry = config.get_model_config(declared)

    if entry is not None:
        dumped = entry.model_dump()
        endpoint = next((dumped[key] for key in _ENDPOINT_KEYS if dumped.get(key)), None)
        provider = reverse_lookup_provider(entry.use)
        base_url = endpoint or _sdk_default_endpoint(provider)
        if not base_url:
            # The one cell with no default to borrow: refusing beats posting the document's
            # images to a public cloud nobody named (spec D10.2).
            from deerflow.knowledge.embedder import RagConfigurationError
            from deerflow.knowledge.model_target import missing_address_reason

            raise RagConfigurationError(missing_address_reason(declared))
        return VlmTarget(
            model=entry.model,
            base_url=base_url,
            api_key=dumped.get("api_key") or None,
            dialect=_dialect_for(entry.use),
            source="model_entry",
            disable_shape=dumped.get("when_thinking_disabled") or None,
            supports_reasoning_effort=bool(dumped.get("supports_reasoning_effort")),
            enable_shape=dumped.get("when_thinking_enabled") or None,
            supports_thinking=bool(dumped.get("supports_thinking")),
        )

    # A name with no entry used to be a bare provider id pointed at the retired RAG endpoint.
    # D10.3 deleted that path: it is a configuration error, and the resolver that resolved the
    # name is the one that reports it (spec §4.9).
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.model_target import model_not_found_message

    raise RagConfigurationError(f"文档图片配文：{model_not_found_message(declared)}")
