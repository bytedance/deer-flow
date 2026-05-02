"""Tests for RAG prompt formatting."""

from deerflow.rag.prompt import format_chunks_for_injection
from deerflow.rag.vector_store import SearchResult


class TestFormatChunksForInjection:
    def test_empty_chunks_returns_empty(self):
        result = format_chunks_for_injection([])
        assert result == ""

    def test_formats_single_chunk(self):
        chunks = [
            SearchResult(
                chunk_id="1",
                content="This is relevant content.",
                metadata={"source": "doc.md"},
                score=0.95,
            )
        ]
        result = format_chunks_for_injection(chunks)
        assert "<knowledge_base>" in result
        assert "This is relevant content." in result
        assert "doc.md" in result
        assert "</knowledge_base>" in result

    def test_formats_multiple_chunks(self):
        chunks = [
            SearchResult(chunk_id="1", content="First chunk.", metadata={"source": "a.md"}, score=0.9),
            SearchResult(chunk_id="2", content="Second chunk.", metadata={"source": "b.md"}, score=0.8),
        ]
        result = format_chunks_for_injection(chunks)
        assert "First chunk." in result
        assert "Second chunk." in result

    def test_respects_token_limit(self):
        chunks = [
            SearchResult(chunk_id=str(i), content="x" * 500, metadata={"source": "big.md"}, score=0.9)
            for i in range(20)
        ]
        result = format_chunks_for_injection(chunks, max_tokens=200)
        # Should truncate — not all 20 chunks will fit
        assert len(result) < 5000  # rough upper bound

    def test_unknown_source(self):
        chunks = [
            SearchResult(chunk_id="1", content="Content.", metadata={}, score=0.5)
        ]
        result = format_chunks_for_injection(chunks)
        assert "unknown" in result
