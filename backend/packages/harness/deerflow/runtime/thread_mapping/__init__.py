"""User↔thread mapping storage (Gateway ``mapping_store``)."""

from .factory import native_thread_mapping_store
from .stores.memory import MemoryThreadMappingStore
from .types import ThreadMappingItem, ThreadMappingStore
from .provider import make_mapping_store


def __getattr__(name: str):
    if name == "PersistenceThreadMappingStore":
        from .stores.persistence_adapter import PersistenceThreadMappingStore

        return PersistenceThreadMappingStore
    raise AttributeError(name)

__all__ = [
    "MemoryThreadMappingStore",
    "PersistenceThreadMappingStore",
    "ThreadMappingItem",
    "ThreadMappingStore",
    "native_thread_mapping_store",
    "make_mapping_store"
]
