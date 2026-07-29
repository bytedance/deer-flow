"""Pluggable memory for DeerFlow.

The shared, backend-agnostic core: the :class:`MemoryManager` contract, the
:func:`get_memory_manager` singleton factory, and :func:`reset_memory_manager`.
Backends live under :mod:`backends` (each self-contained, exposing
``MANAGER_CLASS``); the default DeerMem backend's functional modules live in
``backends/deermem/core/``. Swap backend = drop a ``backends/<name>/`` folder +
set ``MemoryConfig.manager_class`` -- nothing else in deer-flow changes.

DeerMem-private symbols (``format_memory_for_injection``, ``get_memory_data``,
``MemoryUpdater``, ``FileMemoryStorage``, ...) are NOT re-exported here -- import
them directly from ``deerflow.agents.memory.backends.deermem.deermem.core.*``.
"""

from deerflow.agents.memory.manager import (
    MemoryConflictError,
    MemoryCorruptionError,
    MemoryManager,
    MemoryManagerError,
    get_memory_manager,
    reset_memory_manager,
)

__all__ = [
    "MemoryManager",
    "MemoryManagerError",
    "MemoryConflictError",
    "MemoryCorruptionError",
    "get_memory_manager",
    "reset_memory_manager",
]
