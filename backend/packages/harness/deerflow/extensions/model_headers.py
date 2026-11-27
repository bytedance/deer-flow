"""Apply extension-supplied transport headers to the final model request.

An extension contributes a :class:`~deerflow_extension_api.ModelHeadersProvider`
through ``registry.model_headers()``. This host-owned middleware sits innermost
in the lead-agent and subagent model chains — after every request-transforming
middleware — so a provider sees the request the provider is about to receive.

The middleware is host code, not an extension contribution: it is never wrapped
by ``IsolatedMiddleware``, it cannot change messages or tools, and it writes only
``request.model_settings["extra_headers"]``. A failing or malformed provider is
skipped with a warning; headers are advisory and must never fail a model call.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from deerflow_extension_api import ModelHeadersProvider, ModelRequestView, ReadOnlyDict
from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

#: LangChain uses middleware names as trace identities and graph node ids, so it
#: must not collide with a core middleware or an extension contribution.
MIDDLEWARE_NAME = "extension_model_headers"


def _model_name(model: Any) -> str | None:
    for attribute in ("model_name", "model", "model_id"):
        value = getattr(model, attribute, None)
        if isinstance(value, str) and value:
            return value
    return type(model).__name__ if model is not None else None


def build_view(request: Any) -> ModelRequestView:
    """Snapshot the final request into the public, read-only view."""
    state = getattr(request, "state", None)
    return ModelRequestView(
        model_name=_model_name(getattr(request, "model", None)),
        model=getattr(request, "model", None),
        messages=tuple(getattr(request, "messages", None) or ()),
        system_message=getattr(request, "system_message", None),
        tools=tuple(getattr(request, "tools", None) or ()),
        state=ReadOnlyDict(state if isinstance(state, Mapping) else {}),
        runtime=getattr(request, "runtime", None),
    )


def collect_headers(providers: Sequence[tuple[str, ModelHeadersProvider]], view: ModelRequestView) -> dict[str, str]:
    """Call every provider in registration order; later providers win."""
    headers: dict[str, str] = {}
    for source, provider in providers:
        try:
            supplied = provider.provide_model_headers(view)
        except Exception as exc:
            # Mirrors the isolation layer's wording so one grep finds both.
            logger.warning("Extension %s: provide_model_headers failed and was skipped: %s", source, exc)
            continue
        if supplied is None:
            continue
        if not isinstance(supplied, Mapping):
            logger.warning(
                "Extension %s: provide_model_headers returned %s, expected a mapping; skipped",
                source,
                type(supplied).__name__,
            )
            continue
        for key, value in supplied.items():
            if isinstance(key, str) and key and isinstance(value, str):
                headers[key] = value
            else:
                logger.warning(
                    "Extension %s: provide_model_headers dropped a non-string header pair (%r, %r)",
                    source,
                    key,
                    value,
                )
    return headers


def apply_model_headers(providers: Sequence[tuple[str, ModelHeadersProvider]], request: Any) -> None:
    """Merge provider headers into ``request.model_settings["extra_headers"]``."""
    if not providers:
        return
    headers = collect_headers(providers, build_view(request))
    if not headers:
        return
    settings = getattr(request, "model_settings", None)
    if not isinstance(settings, dict):
        logger.warning("agent model request has no mutable model_settings; extension headers skipped")
        return
    existing = settings.get("extra_headers")
    if not isinstance(existing, dict):
        existing = {}
    settings["extra_headers"] = {**existing, **headers}


class ModelHeadersMiddleware(AgentMiddleware):
    """Host-owned middleware that applies provider headers innermost."""

    name = MIDDLEWARE_NAME

    def __init__(self, providers: Sequence[tuple[str, ModelHeadersProvider]]) -> None:
        super().__init__()
        self._providers = tuple(providers)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        apply_model_headers(self._providers, request)
        return handler(request)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        apply_model_headers(self._providers, request)
        return await handler(request)
