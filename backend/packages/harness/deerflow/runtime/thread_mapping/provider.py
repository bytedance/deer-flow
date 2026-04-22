"""Gateway lifespan: construct the configured model feedback store."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from deerflow.config.app_config import get_app_config
from deerflow.runtime.thread_mapping import ThreadMappingStore
from deerflow.runtime.thread_mapping.factory import native_thread_mapping_store
from deerflow.runtime.thread_mapping.stores.memory import MemoryThreadMappingStore

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def make_mapping_store() -> AsyncIterator[ThreadMappingStore]:
    """Yield a native :class:`~deerflow.runtime.thread_mapping.types.ThreadMappingStore` from ``user_thread_mapping``.

    This does **not** use LangGraph's Store; backends are implemented under
    :mod:`deerflow.runtime.thread_mapping.stores`.

    Yields :class:`~deerflow.runtime.thread_mapping.stores.memory.MemoryThreadMappingStore` when
    ``user_thread_mapping`` is omitted (WARNING logged).
    """

    config = get_app_config()

    if config.user_thread_mapping is None:
        logger.warning(
            "No 'user_thread_mapping' section in config — using in-memory thread mapping. "
            "Thread list is lost on restart; configure sqlite, postgres, mongo, or redis for persistence."
        )
        yield MemoryThreadMappingStore()
        return

    async with native_thread_mapping_store(config.user_thread_mapping) as store:
        yield store
