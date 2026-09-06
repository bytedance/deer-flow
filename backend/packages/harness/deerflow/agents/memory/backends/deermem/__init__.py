"""DeerMem backend -- the default memory manager (self-contained).

Holds its own manager class (:mod:`deer_mem`) plus a ``core/`` folder with
the five functional modules (storage / queue / updater / prompt /
message_processing). All DeerMem-private logic lives here; the shared
package top only carries the contract + factory + thin entry points.
"""

from .deer_mem import DeerMem

#: The :class:`~deerflow.agents.memory.manager.MemoryManager` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``deermem``.
MANAGER_CLASS = DeerMem
