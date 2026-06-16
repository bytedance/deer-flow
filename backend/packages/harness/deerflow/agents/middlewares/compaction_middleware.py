"""Headroom context compaction middleware.

Compresses the message history handed to the LLM — primarily large tool
outputs, logs, and search results — at the model-call boundary, using the
optional `Headroom <https://github.com/chopratejas/headroom>`_ library.

Design notes
------------
* **Non-destructive.** Compaction happens inside ``wrap_model_call`` via
  ``request.override(messages=...)``. Only the *request copy* of the messages is
  shrunk; the persisted ``ThreadState`` keeps the full originals, so the
  operation is reversible and never loses tool provenance. This is the opposite
  of :class:`DeerFlowSummarizationMiddleware`, which rewrites state. The two are
  complementary.

* **Content-only, structure-preserving.** We hand Headroom a flat
  ``{role, content}`` view of the messages and map any compressed *string*
  content back onto the original LangChain message objects by position
  (``model_copy(update=...)``). Message IDs, ``tool_calls``, and
  ``additional_kwargs`` are therefore preserved exactly, keeping AI/Tool call
  pairing intact for the provider. If Headroom ever returns a different message
  count (e.g. a history-dropping transform), we conservatively fall back to the
  originals — DeerFlow's own summarization owns history reduction.

* **Optional dependency.** When ``headroom-ai`` is not installed the middleware
  is a transparent pass-through (warned once). Enabling the config on a host
  without Headroom is safe and simply does nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.config.compaction_config import CompactionConfig

logger = logging.getLogger(__name__)

# Resolved lazily on first use: (compress_callable, CompressConfig_type) or (None, None).
_HEADROOM: tuple[Callable[..., Any] | None, type | None] | None = None

_DEFAULT_MODEL = "gpt-4o"
_CHARS_PER_TOKEN = 4  # Coarse estimate, only used to gate cheap/expensive work.


def _load_headroom() -> tuple[Callable[..., Any] | None, type | None]:
    """Import Headroom's ``compress`` API lazily, caching the (failed) result.

    Returns ``(None, None)`` and warns once when ``headroom-ai`` is not
    installed so that an enabled config degrades to a no-op instead of crashing.
    """
    global _HEADROOM
    if _HEADROOM is not None:
        return _HEADROOM
    try:
        from headroom import CompressConfig, compress

        _HEADROOM = (compress, CompressConfig)
    except Exception as exc:  # ImportError or transitive import failures
        logger.warning(
            "Context compaction is enabled but the 'headroom-ai' package could not be imported (%s). Compaction is disabled for this process; install it with `pip install headroom-ai`.",
            exc,
        )
        _HEADROOM = (None, None)
    return _HEADROOM


def _role_of(message: BaseMessage) -> str:
    """Map a LangChain message to a Headroom/OpenAI role string."""
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    return getattr(message, "type", "user")


def _estimate_tokens(messages: list[BaseMessage]) -> int:
    """Cheap char-based token estimate used only to gate compaction work."""
    chars = 0
    for msg in messages:
        content = msg.content
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    chars += len(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    return chars // _CHARS_PER_TOKEN


class HeadroomCompactionMiddleware(AgentMiddleware[AgentState]):
    """Compress message content with Headroom just before each model call."""

    def __init__(
        self,
        config: CompactionConfig | None = None,
        *,
        compress_fn: Callable[..., Any] | None = None,
        compress_config_cls: type | None = None,
    ) -> None:
        """Create the middleware.

        Parameters
        ----------
        config:
            Compaction settings. Defaults to a disabled :class:`CompactionConfig`.
        compress_fn / compress_config_cls:
            Dependency-injection seam for tests — supply a fake ``compress``
            callable (and optional config type) so the middleware can be
            exercised without the heavy ``headroom-ai`` ML stack installed.
        """
        super().__init__()
        self._config = config if config is not None else CompactionConfig()
        self._compress_fn = compress_fn
        self._compress_config_cls = compress_config_cls

    @classmethod
    def from_app_config(cls, app_config: Any) -> HeadroomCompactionMiddleware:
        compaction = getattr(app_config, "compaction", None)
        if isinstance(compaction, CompactionConfig):
            return cls(config=compaction)
        return cls()

    # -- model call hooks --------------------------------------------------

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        compacted = self._compact_request(request)
        return handler(compacted if compacted is not None else request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        # Headroom compression can be CPU-heavy (ML inference), so keep it off the
        # event loop. _compact_request only reads request.messages and builds new
        # message objects — no async state is touched — so a worker thread is safe.
        if self._config.enabled:
            compacted = await asyncio.to_thread(self._compact_request, request)
        else:
            compacted = None
        return await handler(compacted if compacted is not None else request)

    # -- internals ---------------------------------------------------------

    def _compact_request(self, request: ModelRequest) -> ModelRequest | None:
        """Return a request with compacted messages, or ``None`` to pass through."""
        if not self._config.enabled:
            return None

        messages = getattr(request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return None

        if _estimate_tokens(messages) < self._config.min_total_tokens:
            return None

        compress_fn, compress_config_cls = self._resolve_compress()
        if compress_fn is None:
            return None

        try:
            new_messages = self._compact_messages(messages, request, compress_fn, compress_config_cls)
        except Exception:
            if self._config.fail_open:
                logger.debug("Context compaction failed; sending original messages.", exc_info=True)
                return None
            raise

        if new_messages is None:
            return None
        return request.override(messages=new_messages)

    def _resolve_compress(self) -> tuple[Callable[..., Any] | None, type | None]:
        if self._compress_fn is not None:
            return self._compress_fn, self._compress_config_cls
        return _load_headroom()

    def _compact_messages(
        self,
        messages: list[BaseMessage],
        request: ModelRequest,
        compress_fn: Callable[..., Any],
        compress_config_cls: type | None,
    ) -> list[BaseMessage] | None:
        """Run Headroom and map compressed string content back onto originals."""
        payload = [{"role": _role_of(msg), "content": msg.content} for msg in messages]

        kwargs: dict[str, Any] = {
            "model": self._resolve_model_name(request),
            "model_limit": self._config.model_limit,
        }
        if compress_config_cls is not None:
            kwargs["config"] = compress_config_cls(
                compress_user_messages=self._config.compress_user_messages,
                compress_system_messages=self._config.compress_system_messages,
                protect_recent=self._config.protect_recent,
                min_tokens_to_compress=self._config.min_tokens_to_compress,
                target_ratio=self._config.target_ratio,
                savings_profile=self._config.savings_profile,
            )

        result = compress_fn(payload, **kwargs)
        compressed = getattr(result, "messages", None)
        if not isinstance(compressed, list) or len(compressed) != len(messages):
            # Different shape (e.g. history dropped) — leave history reduction to
            # summarization and pass the originals through unchanged.
            return None

        changed = False
        rebuilt: list[BaseMessage] = []
        for original, new in zip(messages, compressed, strict=True):
            new_content = new.get("content") if isinstance(new, dict) else None
            if isinstance(new_content, str) and isinstance(original.content, str) and new_content != original.content:
                rebuilt.append(original.model_copy(update={"content": new_content}))
                changed = True
            else:
                rebuilt.append(original)

        if not changed:
            return None

        saved = getattr(result, "tokens_saved", 0)
        if saved:
            logger.info("Context compaction saved ~%s tokens (ratio %.2f).", saved, getattr(result, "compression_ratio", 0.0))
        return rebuilt

    def _resolve_model_name(self, request: ModelRequest) -> str:
        """Best-effort model-name string for Headroom's tokenizer."""
        if self._config.model:
            return self._config.model
        model = getattr(request, "model", None)
        for attr in ("model_name", "model", "model_id", "deployment_name"):
            value = getattr(model, attr, None)
            if isinstance(value, str) and value:
                return value
        return _DEFAULT_MODEL
