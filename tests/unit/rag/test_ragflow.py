# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock
from src.rag.ragflow import RAGFlowProvider, parse_uri


# Dummy classes to mock dependencies
class DummyResource:
    def __init__(self, uri, title="", description=""):
        self.uri = uri
        self.title = title
        self.description = description


class DummyChunk:
    def __init__(self, content, similarity):
        self.content = content
        self.similarity = similarity


class DummyDocument:
    def __init__(self, id, title, chunks=None):
        self.id = id
        self.title = title
        self.chunks = chunks or []


# Patch imports in ragflow.py to use dummy classes
@pytest.fixture(autouse=True)
def patch_imports(monkeypatch):
    import src.rag.ragflow as ragflow

    ragflow.Resource = DummyResource
    ragflow.Chunk = DummyChunk
    ragflow.Document = DummyDocument
    yield


def test_parse_uri_valid():
    uri = "rag://dataset/123#abc"
    dataset_id, document_id = parse_uri(uri)
    assert dataset_id == "123"
    assert document_id == "abc"


def test_parse_uri_invalid():
    with pytest.raises(ValueError):
        parse_uri("http://dataset/123#abc")


def test_init_env_vars(monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    monkeypatch.delenv("RAGFLOW_PAGE_SIZE", raising=False)
    provider = RAGFlowProvider()
    assert provider.api_url == "http://api"
    assert provider.api_key == "key"
    assert provider.page_size == 10


def test_init_page_size(monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    monkeypatch.setenv("RAGFLOW_PAGE_SIZE", "5")
    provider = RAGFlowProvider()
    assert provider.page_size == 5


def test_init_missing_env(monkeypatch):
    monkeypatch.delenv("RAGFLOW_API_URL", raising=False)
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    with pytest.raises(ValueError):
        RAGFlowProvider()
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    with pytest.raises(ValueError):
        RAGFlowProvider()


@patch("src.rag.ragflow.requests.post")
def test_query_relevant_documents_success(mock_post, monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    provider = RAGFlowProvider()
    resource = DummyResource("rag://dataset/123#doc456")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "doc_aggs": [{"doc_id": "doc456", "doc_name": "Doc Title"}],
            "chunks": [
                {"document_id": "doc456", "content": "chunk text", "similarity": 0.9}
            ],
        }
    }
    mock_post.return_value = mock_response
    docs = provider.query_relevant_documents("query", [resource])
    assert len(docs) == 1
    assert docs[0].id == "doc456"
    assert docs[0].title == "Doc Title"
    assert len(docs[0].chunks) == 1
    assert docs[0].chunks[0].content == "chunk text"
    assert docs[0].chunks[0].similarity == 0.9


@patch("src.rag.ragflow.requests.post")
def test_query_relevant_documents_error(mock_post, monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    provider = RAGFlowProvider()
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "error"
    mock_post.return_value = mock_response
    with pytest.raises(Exception):
        provider.query_relevant_documents("query", [])


@patch("src.rag.ragflow.requests.get")
def test_list_resources_success(mock_get, monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    provider = RAGFlowProvider()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "123", "name": "Dataset1", "description": "desc1"},
            {"id": "456", "name": "Dataset2", "description": "desc2"},
        ]
    }
    mock_get.return_value = mock_response
    resources = provider.list_resources()
    assert len(resources) == 2
    assert resources[0].uri == "rag://dataset/123"
    assert resources[0].title == "Dataset1"
    assert resources[0].description == "desc1"
    assert resources[1].uri == "rag://dataset/456"
    assert resources[1].title == "Dataset2"
    assert resources[1].description == "desc2"


@patch("src.rag.ragflow.requests.get")
def test_list_resources_error(mock_get, monkeypatch):
    monkeypatch.setenv("RAGFLOW_API_URL", "http://api")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    provider = RAGFlowProvider()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "fail"
    mock_get.return_value = mock_response
    with pytest.raises(Exception):
        provider.list_resources()
