from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.runtime.events.store.base import RunEventStore, RunEventStoreNotCommittedError
from deerflow.runtime.events.store.memory import MemoryRunEventStore

if TYPE_CHECKING:
    from deerflow.extensions.registry import LoadedExtensions

#: Backends the core builds itself; every other name is extension-provided.
BUILTIN_RUN_EVENT_BACKENDS = ("memory", "db", "jsonl")


def make_run_event_store(config=None, *, extensions: LoadedExtensions | None = None) -> RunEventStore:
    """Create a RunEventStore based on run_events.backend configuration.

    Built-in backends never consult ``extensions``. Any other name resolves
    against the given loaded-extension snapshot only -- never a process-global
    one -- so each Gateway app resolves against its own extensions. There is no
    fallback: run events are persistent state, so an unresolvable name raises.
    """
    if config is None or config.backend == "memory":
        return MemoryRunEventStore()
    if config.backend == "db":
        from deerflow.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            if getattr(config, "producer_fencing", "off") == "strict":
                raise RuntimeError("Strict producer fencing requires a persistent PostgreSQL RunStore")
            # database.backend=memory but run_events.backend=db -> fallback
            return MemoryRunEventStore()
        from deerflow.runtime.events.store.db import DbRunEventStore

        return DbRunEventStore(sf, max_trace_content=config.max_trace_content, producer_fencing=getattr(config, "producer_fencing", "off"), producer_cutover_id=getattr(config, "producer_cutover_id", None))
    if config.backend == "jsonl":
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        return JsonlRunEventStore()
    return _make_extension_store(config, extensions)


def _make_extension_store(config, extensions: LoadedExtensions | None) -> RunEventStore:
    backend = config.backend
    if extensions is None:
        raise ValueError(f"run_events.backend {backend!r} is provided by an extension; pass the loaded extensions")
    factories = extensions.run_event_store_factories
    for source, (name, factory) in factories:
        if name == backend:
            store = factory(config)
            if not isinstance(store, RunEventStore):
                raise TypeError(f"run_events.backend {backend!r} factory from extension {source} returned {type(store).__name__}, not a RunEventStore")
            return store
    provided = ", ".join(f"{name} (from {source})" for source, (name, _) in factories) or "none"
    raise ValueError(f"Unknown run_events backend: run_events.backend {backend!r} is not a built-in ({', '.join(BUILTIN_RUN_EVENT_BACKENDS)}) and no loaded extension provides it; extension-provided backends: {provided}")


__all__ = ["BUILTIN_RUN_EVENT_BACKENDS", "MemoryRunEventStore", "RunEventStore", "RunEventStoreNotCommittedError", "make_run_event_store"]
