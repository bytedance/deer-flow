from unittest.mock import MagicMock
from governance_kb_mcp.config import KBConfig
from governance_kb_mcp.chunking import DocumentChunk
from governance_kb_mcp.store import KBStore, SearchResult


def _make_config(tmp_path):
    return KBConfig(
        volcengine_api_key="test-key",
        embedding_model="doubao-embedding-text-240715",
        embedding_api_base="https://example.com",
        chroma_path=tmp_path / "chroma_db",
        host="0.0.0.0",
        port=8101,
        embedding_timeout=10.0,
    )


def _make_mock_embedding():
    mock = MagicMock()
    mock.embed.return_value = [0.1, 0.2, 0.3]
    mock.embed_batch.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    return mock


def test_add_documents_company_level(tmp_path):
    config = _make_config(tmp_path)
    store = KBStore(config, _make_mock_embedding())
    chunks = [
        DocumentChunk("Company policy text", "policy.txt", "1-1", 0),
        DocumentChunk("Another policy", "policy.txt", "3-3", 50),
    ]
    ids = store.add_documents(chunks, level="company", metadata={})
    assert len(ids) == 2


def test_search_returns_results(tmp_path):
    config = _make_config(tmp_path)
    store = KBStore(config, _make_mock_embedding())
    chunks = [
        DocumentChunk("Company policy about remote work", "policy.txt", "1-1", 0),
    ]
    store.add_documents(chunks, level="company", metadata={"author": "hr"})
    results = store.search("remote work policy", level="company", top_k=5)
    assert len(results) >= 1
    assert isinstance(results[0], SearchResult)
    assert results[0].source_file == "policy.txt"
    assert results[0].line_range == "1-1"
    assert results[0].level == "company"


def test_list_collections(tmp_path):
    config = _make_config(tmp_path)
    store = KBStore(config, _make_mock_embedding())
    store.add_documents(
        [DocumentChunk("doc1", "f.txt", "1-1", 0)], level="company", metadata={}
    )
    store.add_documents(
        [DocumentChunk("doc2", "f.txt", "1-1", 0)],
        level="position:developer",
        metadata={},
    )
    store.add_documents(
        [DocumentChunk("doc3", "f.txt", "1-1", 0)],
        level="personal:wangguodong",
        metadata={},
    )
    collections = store.list_collections()
    assert len(collections) == 3
    names = [c.collection_name for c in collections]
    assert "company" in names
    assert "position:developer" in names
    assert "personal:wangguodong" in names


def test_search_empty_embedding_returns_empty(tmp_path):
    config = _make_config(tmp_path)
    mock_embedding = MagicMock()
    mock_embedding.embed.return_value = []  # timeout / no key
    store = KBStore(config, mock_embedding)
    results = store.search("query", level="company", top_k=5)
    assert results == []


def test_collection_isolation(tmp_path):
    config = _make_config(tmp_path)
    store = KBStore(config, _make_mock_embedding())
    store.add_documents(
        [DocumentChunk("company secret", "secret.txt", "1-1", 0)],
        level="company",
        metadata={},
    )
    store.add_documents(
        [DocumentChunk("personal note", "note.txt", "1-1", 0)],
        level="personal:wangguodong",
        metadata={},
    )
    results = store.search("secret", level="personal:wangguodong", top_k=5)
    assert all(r.level == "personal:wangguodong" for r in results)
