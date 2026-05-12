from __future__ import annotations

import logging
from typing import Any

from deerflow.vectorDB.base import Document, VectorStore

logger = logging.getLogger(__name__)


class ChromaVectorStore(VectorStore):
    def __init__(self, config, path: str, collection_name: str):
        self.config = config
        self.path = path
        self.collection_name = collection_name
        self._client = None
        self._collection = None

        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise ImportError("The 'chromadb' package is required to use the Chroma backend. Please install it using: uv sync --extra chroma")

        self._client = chromadb.PersistentClient(path=self.path, settings=Settings(allow_reset=True))

        self._collection = self._client.get_or_create_collection(name=self.collection_name)

    async def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None, ids: list[str] | None = None) -> list[str]:
        """Add documents to the chroma collection."""
        import uuid

        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]

        self._collection.add(ids=ids, documents=texts, metadatas=metadatas)
        return ids

    async def get_by_ids(self, ids: list[str]) -> list[Document]:
        """Get specific documents by ids."""
        results = self._collection.get(ids=ids)

        documents = []
        if results and results["ids"]:
            for i in range(len(results["ids"])):
                documents.append(Document(id=results["ids"][i], page_content=results["documents"][i], metadata=results["metadatas"][i] or {}))
        return documents

    async def similarity_search(self, query: str, k: int = 5, filter_dict: dict[str, Any] | None = None) -> list[Document]:
        """Perform a sementic search in Chroma."""

        results = self._collection.query(query_texts=[query], n_results=k, where=filter_dict)

        documents = []

        if results and results["ids"] and len(results["ids"]) > 0:
            for i in range(len(results["ids"][0])):
                documents.append(Document(id=results["ids"][0][i], page_content=results["documents"][0][i], metadata=results["metadatas"][0][i] or {}))
        return documents

    async def delete_by_ids(self, ids: list[str]) -> None:
        """Remove specific documents from the collection."""
        self._collection.delete(ids=ids)

    async def delete_collection(self) -> None:
        """Delete the entire collection from the database."""
        self._client.delete_collection(name=self.collection_name)
