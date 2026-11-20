"""Noop memory backend -- functional empty adapter (pluggability proof + template)."""

from .noop_manager import NoopMemoryManager

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``noop``.
MANAGER_CLASS = NoopMemoryManager
