# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

import src.rag.qdrant as qdrant_mod
from src.rag.qdrant import QdrantProvider


class DummyEmbedding:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def embed_query(self, text: str):
        return [0.1] * 1536

    def embed_documents(self, texts):
        return [[0.1] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "text-embedding-ada-002")
    monkeypatch.setenv("QDRANT_COLLECTION", "documents")
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    monkeypatch.setattr(qdrant_mod, "OpenAIEmbeddings", DummyEmbedding)
    monkeypatch.setattr(qdrant_mod, "DashscopeEmbeddings", DummyEmbedding)
    yield


@pytest.fixture
def project_root():
    return Path(qdrant_mod.__file__).parent.parent.parent


@pytest.fixture
def temp_examples_dir(project_root):
    temp_dir_name = f"examples_test_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


@pytest.fixture
def temp_error_examples_dir(project_root):
    temp_dir_name = f"examples_error_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


@pytest.fixture
def temp_load_skip_examples_dir(project_root):
    temp_dir_name = f"examples_load_skip_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


def test_init_openai_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "openai")
    provider = QdrantProvider()
    assert provider.embedding_provider == "openai"
    assert isinstance(provider.embedding_model, DummyEmbedding)


def test_init_dashscope_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "dashscope")
    provider = QdrantProvider()
    assert provider.embedding_provider == "dashscope"
    assert isinstance(provider.embedding_model, DummyEmbedding)


def test_init_invalid_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "invalid_provider")
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        QdrantProvider()


def test_get_embedding_dimension_explicit(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_DIM", "2048")
    provider = QdrantProvider()
    assert provider.embedding_dim == 2048


def test_get_embedding_dimension_default(monkeypatch):
    monkeypatch.delenv("QDRANT_EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "text-embedding-ada-002")
    provider = QdrantProvider()
    assert provider.embedding_dim == 1536


def test_get_embedding_dimension_unknown_model(monkeypatch):
    monkeypatch.delenv("QDRANT_EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "unknown-model")
    provider = QdrantProvider()
    assert provider.embedding_dim == 1536


def test_connect_memory_mode(monkeypatch):
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    provider = QdrantProvider()
    provider._connect()
    assert provider.client is not None


def test_create_collection(monkeypatch):
    provider = QdrantProvider()
    provider.create_collection()
    assert provider.client is not None


def test_extract_title_from_markdown():
    provider = QdrantProvider()
    content = "# Test Title\n\nSome content"
    title = provider._extract_title_from_markdown(content, "test.md")
    assert title == "Test Title"


def test_extract_title_fallback():
    provider = QdrantProvider()
    content = "No title here"
    title = provider._extract_title_from_markdown(content, "test_file.md")
    assert title == "Test File"


def test_split_content_short():
    provider = QdrantProvider()
    content = "Short content"
    chunks = provider._split_content(content)
    assert len(chunks) == 1
    assert chunks[0] == content


def test_split_content_long(monkeypatch):
    monkeypatch.setenv("QDRANT_CHUNK_SIZE", "20")
    provider = QdrantProvider()
    content = "Paragraph one here\n\nParagraph two here\n\nParagraph three here\n\nParagraph four here"
    chunks = provider._split_content(content)
    assert len(chunks) > 1


def test_string_to_uuid():
    provider = QdrantProvider()
    uuid1 = provider._string_to_uuid("test")
    uuid2 = provider._string_to_uuid("test")
    assert uuid1 == uuid2


def test_get_embedding():
    provider = QdrantProvider()
    embedding = provider._get_embedding("test text")
    assert len(embedding) == 1536
    assert all(isinstance(x, float) for x in embedding)


def test_load_examples_no_directory(monkeypatch, project_root):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", "nonexistent_dir")
    provider = QdrantProvider()
    provider.load_examples()


def test_load_examples_empty_directory(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)
    provider = QdrantProvider()
    provider.load_examples()


def test_load_examples_with_files(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1
    assert loaded[0]["title"] == "Test"


def test_load_examples_skip_existing(monkeypatch, temp_load_skip_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_load_skip_examples_dir.name)

    md_file = temp_load_skip_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1


def test_load_examples_force_reload(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()
    provider.load_examples(force_reload=True)

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1


def test_load_examples_error_handling(monkeypatch, temp_error_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_error_examples_dir.name)

    good_file = temp_error_examples_dir / "good.md"
    good_file.write_text("# Good\n\nContent", encoding="utf-8")

    bad_file = temp_error_examples_dir / "bad.md"
    bad_file.write_text("# Bad\n\n", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) >= 1


def test_list_resources_no_query(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources()
    assert len(resources) >= 1


def test_list_resources_with_query(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources(query="test")
    assert isinstance(resources, list)


def test_query_relevant_documents(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent about testing", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    documents = provider.query_relevant_documents("testing")
    assert isinstance(documents, list)


def test_query_relevant_documents_with_resources(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources()
    documents = provider.query_relevant_documents("test", resources=resources)
    assert isinstance(documents, list)


def test_close():
    provider = QdrantProvider()
    provider._connect()
    provider.close()
    assert provider.client is None


def test_del():
    provider = QdrantProvider()
    provider._connect()
    del provider


def test_top_k_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "20")
    provider = QdrantProvider()
    assert provider.top_k == 20


def test_top_k_invalid(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "invalid")
    provider = QdrantProvider()
    assert provider.top_k == 10


def test_chunk_size_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_CHUNK_SIZE", "5000")
    provider = QdrantProvider()
    assert provider.chunk_size == 5000


def test_collection_name_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_COLLECTION", "custom_collection")
    provider = QdrantProvider()
    assert provider.collection_name == "custom_collection"


def test_auto_load_examples_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_AUTO_LOAD_EXAMPLES", "false")
    provider = QdrantProvider()
    assert provider.auto_load_examples is False
