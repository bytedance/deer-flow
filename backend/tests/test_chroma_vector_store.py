import asyncio
from unittest.mock import MagicMock

import pytest

from deerflow.vectorDB import make_vector_store
from deerflow.vectorDB.config import ChromaConfig, VectorStoreConfig

try:
    import chromadb  # noqa: F401

    CHROMA_INSTALLED = True
except ImportError:
    CHROMA_INSTALLED = False


@pytest.fixture
def temp_chroma_path(tmp_path):
    """Provides a temporary directory for Chroma that is cleaned up after tests."""
    return str(tmp_path / "chroma_test")


@pytest.fixture
def mock_config(temp_chroma_path):
    config = MagicMock()
    config.vector_store = VectorStoreConfig(backend="chroma", embedding_model=None, chroma=ChromaConfig(path=temp_chroma_path, collection_name="test_collection"))
    return config


@pytest.mark.skipif(not CHROMA_INSTALLED, reason="chromadb not installed")
def test_chroma_lifecycle(mock_config):
    """Test the full lifecycle: Create, Add, Search, Get, Delete."""

    store = asyncio.run(make_vector_store(mock_config))
    assert store is not None

    texts = ["The quick brown fox", "Jumped over the lazy dog"]
    metadatas = [{"source": "test1"}, {"source": "test2"}]
    ids = asyncio.run(store.add_texts(texts=texts, metadatas=metadatas))

    assert len(ids) == 2

    results = asyncio.run(store.similarity_search("Who jumped?", k=1))
    assert len(results) == 1
    assert "lazy dog" in results[0].page_content

    doc = asyncio.run(store.get_by_ids([ids[0]]))
    assert len(doc) == 1
    assert doc[0].page_content == texts[0]

    asyncio.run(store.delete_by_ids([ids[0]]))
    remaining = asyncio.run(store.get_by_ids([ids[0]]))
    assert len(remaining) == 0

    asyncio.run(store.delete_collection())

    with pytest.raises(Exception):
        asyncio.run(store.similarity_search("Who jumped?", k=1))


def test_factory_none_backend():
    """Test that the factory gracefully returns None when backend is disabled."""
    config = MagicMock()
    config.vector_store.backend = "none"

    store = asyncio.run(make_vector_store(config))
    assert store is None


def test_factory_unsupported_backend():
    """Test that the factory catches typos or unsupported backends."""
    config = MagicMock()
    config.vector_store.backend = "pinecone"  # Not supported yet

    with pytest.raises(ValueError, match="Unsupported vector backend"):
        asyncio.run(make_vector_store(config))


@pytest.mark.skipif(not CHROMA_INSTALLED, reason="chromadb not installed")
def test_chroma_empty_and_missing(mock_config):
    """Test how Chroma behaves with empty searches and missing IDs."""
    store = asyncio.run(make_vector_store(mock_config))

    empty_results = asyncio.run(store.similarity_search("Hello?", k=2))
    assert len(empty_results) == 0

    missing_doc = asyncio.run(store.get_by_ids(["fake-id-123"]))
    assert len(missing_doc) == 0

    asyncio.run(store.delete_collection())

    with pytest.raises(Exception):
        asyncio.run(store.similarity_search("Who jumped?", k=1))
