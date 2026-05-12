"""DeerFlow vector database infrastructure.

This module provides the factory and abstract interfaces for managing vector
databases (like Chroma) used for agent knowledge retrieval.
"""

from deerflow.vectorDB.base import Document, VectorStore
from deerflow.vectorDB.config import VectorStoreConfig
from deerflow.vectorDB.factory import make_vector_store

__all__ = ["Document", "VectorStore", "make_vector_store", "VectorStoreConfig"]
