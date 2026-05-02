"""Tests for RAG chunking strategies."""

import pytest

from deerflow.rag.chunking import (
    Chunk,
    MarkdownChunkStrategy,
    RecursiveChunkStrategy,
    SemanticChunkStrategy,
    get_chunk_strategy,
)


class TestRecursiveChunkStrategy:
    def test_splits_short_text_into_single_chunk(self):
        strategy = RecursiveChunkStrategy(chunk_size=1000, chunk_overlap=200)
        chunks = strategy.split("Hello world")
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world"

    def test_splits_long_text(self):
        strategy = RecursiveChunkStrategy(chunk_size=100, chunk_overlap=20)
        text = "This is sentence one. " * 50
        chunks = strategy.split(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= 120  # chunk_size + some margin

    def test_preserves_metadata(self):
        strategy = RecursiveChunkStrategy(chunk_size=1000, chunk_overlap=200)
        chunks = strategy.split("Hello world", {"source": "test.txt"})
        assert chunks[0].metadata["source"] == "test.txt"

    def test_empty_text(self):
        strategy = RecursiveChunkStrategy()
        chunks = strategy.split("")
        assert len(chunks) == 0


class TestMarkdownChunkStrategy:
    def test_splits_markdown_with_headers(self):
        strategy = MarkdownChunkStrategy(chunk_size=1000, chunk_overlap=200)
        text = "# Title\n\nSome content here.\n\n## Section 1\n\nMore content.\n\n## Section 2\n\nEven more."
        chunks = strategy.split(text)
        assert len(chunks) >= 1

    def test_preserves_header_metadata(self):
        strategy = MarkdownChunkStrategy(chunk_size=1000, chunk_overlap=200)
        text = "# Main\n\nIntro.\n\n## Sub\n\nDetails."
        chunks = strategy.split(text)
        # At least one chunk should have heading metadata
        has_header = any("h1" in c.metadata or "h2" in c.metadata for c in chunks)
        assert has_header


class TestSemanticChunkStrategy:
    def test_falls_back_to_recursive_without_embedder(self):
        strategy = SemanticChunkStrategy(chunk_size=1000, chunk_overlap=200)
        chunks = strategy.split("Hello world. This is a test.")
        assert len(chunks) >= 1

    def test_falls_back_with_none_embedder(self):
        strategy = SemanticChunkStrategy(chunk_size=1000, chunk_overlap=200, embedder=None)
        chunks = strategy.split("Hello world. This is a test.")
        assert len(chunks) >= 1


class TestGetChunkStrategy:
    def test_recursive(self):
        s = get_chunk_strategy("recursive", 500, 100)
        assert isinstance(s, RecursiveChunkStrategy)

    def test_markdown(self):
        s = get_chunk_strategy("markdown", 500, 100)
        assert isinstance(s, MarkdownChunkStrategy)

    def test_semantic(self):
        s = get_chunk_strategy("semantic", 500, 100)
        assert isinstance(s, SemanticChunkStrategy)

    def test_unknown_falls_back_to_recursive(self):
        s = get_chunk_strategy("unknown", 500, 100)
        assert isinstance(s, RecursiveChunkStrategy)
