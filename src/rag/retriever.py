# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import abc

from pydantic import BaseModel, Field


class Chunk:
    content: str
    similarity: float

    def __init__(self, content: str, similarity: float):
        self.content = content
        self.similarity = similarity


class Document:
    """
    Document is a class that represents a document.
    """

    id: str
    url: str | None = None
    title: str | None = None
    chunks: list[Chunk] = []

    def __init__(
        self,
        id: str,
        url: str | None = None,
        title: str | None = None,
        chunks: list[Chunk] = [],
    ):
        self.id = id
        self.url = url
        self.title = title
        self.chunks = chunks

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "content": "\n\n".join([chunk.content for chunk in self.chunks]),
        }
        if self.url:
            d["url"] = self.url
        if self.title:
            d["title"] = self.title
        return d


class Resource(BaseModel):
    """
    Resource is a class that represents a resource.
    """

    uri: str = Field(..., description="The URI of the resource")
    title: str = Field(..., description="The title of the resource")
    description: str | None = Field("", description="The description of the resource")


class Retriever(abc.ABC):
    """
    Define a RAG provider, which can be used to query documents and resources.
    """

    @abc.abstractmethod
    def list_resources(self, query: str | None = None) -> list[Resource]:
        """
        List resources from the rag provider.
        """
        pass

    @abc.abstractmethod
    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        """
        Query relevant documents from the resources.
        """
        pass

    def ingest_file(self, file_content: bytes, filename: str, **kwargs) -> Resource:
        """
        Ingest a file into the RAG provider and register it as a :class:`Resource`.

        This method is intended to be overridden by concrete retriever implementations.
        The default implementation always raises :class:`NotImplementedError`.

        Parameters
        ----------
        file_content:
            Raw bytes of the file to ingest. For text-based formats, implementations
            will typically assume UTF-8 encoding unless documented otherwise. Binary
            formats (such as PDF, images, or office documents) should be passed as
            their original bytes.
        filename:
            The original filename, including extension (e.g. ``"report.pdf"``). This
            can be used by implementations to infer the file type, MIME type, or to
            populate the resulting resource's title.
        **kwargs:
            Additional, implementation-specific options. Examples may include:

            - Explicit MIME type or file type hints.
            - Additional metadata to associate with the resource.
            - Chunking, indexing, or preprocessing parameters.

            Unsupported or invalid keyword arguments may result in an exception being
            raised by the concrete implementation.

        Returns
        -------
        Resource
            A :class:`Resource` instance describing the ingested file, including its
            URI and title. The exact URI scheme and how the resource is stored are
            implementation-defined.

        Raises
        ------
        NotImplementedError
            Always raised by the base ``Retriever`` implementation. Concrete
            implementations should override this method to provide functionality.
        ValueError
            May be raised by implementations if the input bytes, filename, or
            provided options are invalid.
        RuntimeError
            May be raised by implementations to signal unexpected ingestion or
            storage failures (e.g. backend service errors).
        """
        raise NotImplementedError("ingest_file is not implemented")
