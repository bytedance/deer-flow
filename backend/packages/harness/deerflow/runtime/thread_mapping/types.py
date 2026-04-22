"""Types for user↔thread mapping persistence (independent of LangGraph :class:`BaseStore`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ThreadMappingItem:
    """One row returned from :meth:`ThreadMappingStore.asearch` or logical equivalent of ``aget``."""

    key: str
    value: dict[str, Any]


class ThreadMappingStore(ABC):
    """Abstract async mapping store for Gateway ``user_thread_mapping``.

    Concrete backends subclass this in :mod:`deerflow.runtime.thread_mapping.stores` and are
    opened via :func:`~deerflow.runtime.thread_mapping.factory.native_thread_mapping_store`.
    """

    __slots__ = ()

    @abstractmethod
    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        """Load one mapping document; ``None`` if missing."""
        ...

    @abstractmethod
    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        """Upsert one mapping document."""
        ...

    @abstractmethod
    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        """List mappings under the namespace prefix."""
        ...

    @abstractmethod
    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Remove one mapping."""
        ...
