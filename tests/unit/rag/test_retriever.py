# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest

from src.rag.retriever import Chunk, Document, Resource, Retriever


def test_chunk_init():
    chunk = Chunk(content="test content", similarity=0.9)
    assert chunk.content == "test content"
    assert chunk.similarity == 0.9


def test_document_init_and_to_dict():
    chunk1 = Chunk(content="chunk1", similarity=0.8)
    chunk2 = Chunk(content="chunk2", similarity=0.7)
    doc = Document(
        id="doc1", url="http://example.com", title="Title", chunks=[chunk1, chunk2]
    )
    assert doc.id == "doc1"
    assert doc.url == "http://example.com"
    assert doc.title == "Title"
    assert doc.chunks == [chunk1, chunk2]
    d = doc.to_dict()
    assert d["id"] == "doc1"
    assert d["content"] == "chunk1\n\nchunk2"
    assert d["url"] == "http://example.com"
    assert d["title"] == "Title"


def test_document_to_dict_optional_fields():
    chunk = Chunk(content="only chunk", similarity=1.0)
    doc = Document(id="doc2", chunks=[chunk])
    d = doc.to_dict()
    assert d["id"] == "doc2"
    assert d["content"] == "only chunk"
    assert "url" not in d
    assert "title" not in d


def test_resource_model():
    resource = Resource(uri="uri1", title="Resource Title")
    assert resource.uri == "uri1"
    assert resource.title == "Resource Title"
    assert resource.description == ""


def test_resource_model_with_description():
    resource = Resource(uri="uri2", title="Resource2", description="desc")
    assert resource.description == "desc"


def test_retriever_abstract_methods():
    class DummyRetriever(Retriever):
        def list_resources(self, query=None):
            return [Resource(uri="uri", title="title")]

        def query_relevant_documents(self, query, resources=[]):
            return [Document(id="id", chunks=[])]

    retriever = DummyRetriever()
    resources = retriever.list_resources()
    assert isinstance(resources, list)
    assert isinstance(resources[0], Resource)
    docs = retriever.query_relevant_documents("query", resources)
    assert isinstance(docs, list)
    assert isinstance(docs[0], Document)


def test_retriever_cannot_instantiate():
    with pytest.raises(TypeError):
        Retriever()
