"""Abstract interface for Vector Database storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class Document(BaseModel):
    """A standard representation of a retrieved document."""

    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class VectorStore(ABC):
    """Abstract base class for vector storage operations."""

    @abstractmethod
    async def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None, ids: list[str] | None = None, **kwargs) -> list[str]:
        """Embed and store a list of texts.

        Args:
            texts: The raw string content to store.
            metadatas: Optional list of metadata dicts corresponding to the texts.
            ids: Optional list of unique IDs for the documnts.

        Returns:
            A list of document IDs.
        """
        pass

    @abstractmethod
    async def get_by_ids(self, ids: list[str]) -> list[Document]:
        """Fetch specific documents and their metadata by ID.

        Args:
            ids: List of IDs of documents to fetch.

        Returns:
            A List of Document objects.
        """
        pass

    @abstractmethod
    async def similarity_search(self, query: str, k: int = 5, filter_dict: dict[str, Any] | None = None, **kwargs) -> list[Document]:
        """Retrieve documents most similar to the query string.

        Args:
            query: The search string.
            k: The number of documents to return.
            filter_dict: Optional metadata filters to apply before searching.

        Returns:
            A list of Document objects representing the closest matches.
        """
        pass

    @abstractmethod
    async def delete_collection(self) -> None:
        """Delete the entire collection and all its documents."""
        pass

    @abstractmethod
    async def delete_by_ids(self, ids: list[str]) -> None:
        """Delete specific documents by their unique IDs.

        Args:
            ids: List of IDs of documents to delete.
        """
        pass

    # Optional
    async def hybrid_search(self, query: str, k: int = 5, alpha: float = 0.5, filter_dict: dict[str, Any] | None = None, **kwargs) -> list[Document]:

        # fallback
        return await self.similarity_search(query, k=k, filter_dict=filter_dict)
