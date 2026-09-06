"""Tracing callback wrappers that remove private knowledge-scope metadata."""

from __future__ import annotations

import inspect
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage

from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_KEY,
    KNOWLEDGE_SCOPE_RUNTIME_KEY,
    strip_message_knowledge_scope,
)


def redact_knowledge_scope(value: Any) -> Any:
    """Copy callback payload containers without scope IDs or display labels."""
    if isinstance(value, BaseMessage):
        return strip_message_knowledge_scope(value)
    if isinstance(value, dict):
        return {key: redact_knowledge_scope(item) for key, item in value.items() if key not in {KNOWLEDGE_SCOPE_KEY, KNOWLEDGE_SCOPE_RUNTIME_KEY}}
    if isinstance(value, list):
        return [redact_knowledge_scope(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_knowledge_scope(item) for item in value)
    return value


class KnowledgeScopeRedactingCallback(BaseCallbackHandler):
    """Transparent callback proxy with scope-free arguments.

    ``__getattribute__`` is intentional: BaseCallbackHandler supplies no-op
    ``on_*`` methods, so ordinary ``__getattr__`` would never reach a delegate.
    Returning a sync or async wrapper matching the delegate preserves callback
    manager scheduling semantics.
    """

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("on_"):
            delegate = object.__getattribute__(self, "delegate")
            method = getattr(delegate, name)
            if inspect.iscoroutinefunction(method):

                async def async_forward(*args: Any, **kwargs: Any) -> Any:
                    return await method(
                        *(redact_knowledge_scope(arg) for arg in args),
                        **{key: redact_knowledge_scope(value) for key, value in kwargs.items()},
                    )

                return async_forward

            def forward(*args: Any, **kwargs: Any) -> Any:
                return method(
                    *(redact_knowledge_scope(arg) for arg in args),
                    **{key: redact_knowledge_scope(value) for key, value in kwargs.items()},
                )

            return forward
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def __eq__(self, other: object) -> bool:
        # Preserve callback-list membership checks used by existing embedders.
        return self.delegate is other or self.delegate == other

    def __hash__(self) -> int:
        return hash(self.delegate)

    @property
    def ignore_agent(self) -> bool:
        return bool(getattr(self.delegate, "ignore_agent", False))

    @property
    def ignore_chain(self) -> bool:
        return bool(getattr(self.delegate, "ignore_chain", False))

    @property
    def ignore_chat_model(self) -> bool:
        return bool(getattr(self.delegate, "ignore_chat_model", False))

    @property
    def ignore_custom_event(self) -> bool:
        return bool(getattr(self.delegate, "ignore_custom_event", False))

    @property
    def ignore_llm(self) -> bool:
        return bool(getattr(self.delegate, "ignore_llm", False))

    @property
    def ignore_retriever(self) -> bool:
        return bool(getattr(self.delegate, "ignore_retriever", False))

    @property
    def ignore_retry(self) -> bool:
        return bool(getattr(self.delegate, "ignore_retry", False))

    @property
    def run_inline(self) -> bool:
        return bool(getattr(self.delegate, "run_inline", False))

    @property
    def raise_error(self) -> bool:
        return bool(getattr(self.delegate, "raise_error", False))


def redact_knowledge_scope_callbacks(callbacks: list[Any]) -> list[Any]:
    return [KnowledgeScopeRedactingCallback(callback) for callback in callbacks]
