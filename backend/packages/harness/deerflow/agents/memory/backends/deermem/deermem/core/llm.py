"""DeerMem's own LLM construction (no deer-flow ``create_chat_model``).

``build_llm(model_config)`` builds a langchain ``ChatModel`` from DeerMem's
model sub-config (provider/model/api_key/base_url/temperature) via
``langchain.chat_models.init_chat_model``. DeerMem owns the resulting instance
(``self._llm``) and injects it into ``MemoryUpdater`` (dependency injection).

``DeerMem.__init__`` prefers a host-injected ``host_llm`` (the deer-flow
factory injects the app default model there when ``model`` is empty, mirroring
pre-abstraction ``model_name: null``); this ``build_llm`` is the fallback that
builds from the ``model`` sub-config. Returns ``None`` when ``model`` is empty
- standalone DeerMem then has no LLM (non-LLM ops still work; an update
raises), but via the factory ``host_llm`` covers the zero-config case. Any
provider langchain's ``init_chat_model`` supports works (OpenAI, Anthropic,
OpenAI-compatible gateways like DeepSeek, ...).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import DeerMemModelConfig

logger = logging.getLogger(__name__)


def build_llm(model_config: DeerMemModelConfig | None) -> Any:
    """Build a langchain ChatModel from DeerMem's model config (DI).

    Returns ``None`` if ``model_config`` is None, has no ``model`` set
    (zero-config: no LLM; non-LLM ops still work, an update will raise), OR if
    ``init_chat_model`` fails (misconfigured provider/api_key/base_url). The
    failure path degrades to ``None`` with a WARNING -- mirroring
    :func:`_host_default_llm` -- so a bad explicit ``model`` does not crash app
    startup: memory CRUD/read/search still work, extraction is disabled, and an
    update raises at runtime with the underlying error logged.
    """
    if model_config is None or not model_config.model:
        return None
    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = {}
    if model_config.api_key is not None:
        kwargs["api_key"] = model_config.api_key
    if model_config.base_url is not None:
        kwargs["base_url"] = model_config.base_url
    if model_config.temperature is not None:
        kwargs["temperature"] = model_config.temperature
    try:
        return init_chat_model(
            model=model_config.model,
            model_provider=model_config.provider or "openai",
            **kwargs,
        )
    except Exception as e:  # noqa: BLE001 - degrade like _host_default_llm (don't crash startup)
        logger.warning(
            "build_llm failed for model=%r (provider=%r): %s; memory extraction disabled (non-LLM ops still work; an update will raise).",
            model_config.model,
            model_config.provider or "openai",
            e,
        )
        return None
