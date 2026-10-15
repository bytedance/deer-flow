"""Pluggable memory backends.

Each subpackage is a self-contained backend that exposes
``MANAGER_CLASS`` (a :class:`~deerflow.agents.memory.manager.MemoryManager`
subclass) in its ``__init__``. The drop-in contract: folder name ==
backend name == ``MemoryConfig.manager_class`` value.

Add a new backend by dropping a new folder here and setting
``manager_class: <name>`` -- no other deer-flow code changes.
"""
