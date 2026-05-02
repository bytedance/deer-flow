"""Document chunking strategies for RAG ingestion."""

import abc
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


@dataclass
class Chunk:
    """A text chunk with metadata."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0


class ChunkStrategy(abc.ABC):
    """Abstract base class for text chunking strategies."""

    @abc.abstractmethod
    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        raise NotImplementedError


class RecursiveChunkStrategy(ChunkStrategy):
    """Recursive character-based splitting using langchain_text_splitters."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        meta = metadata or {}
        docs = self._splitter.create_documents([text], [meta])
        return [
            Chunk(content=doc.page_content, metadata=dict(doc.metadata), chunk_index=i)
            for i, doc in enumerate(docs)
        ]


class MarkdownChunkStrategy(ChunkStrategy):
    """Markdown-aware splitting that preserves heading hierarchy."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        self._md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
                ("####", "h4"),
            ],
            strip_headers=False,
        )
        self._recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        meta = metadata or {}
        md_docs = self._md_splitter.split_text(text)
        chunks: list[Chunk] = []
        idx = 0
        for md_doc in md_docs:
            merged_meta = {**meta, **md_doc.metadata}
            sub_docs = self._recursive_splitter.create_documents([md_doc.page_content], [merged_meta])
            for sub_doc in sub_docs:
                chunks.append(Chunk(content=sub_doc.page_content, metadata=dict(sub_doc.metadata), chunk_index=idx))
                idx += 1
        return chunks


class SemanticChunkStrategy(ChunkStrategy):
    """Semantic chunking based on embedding similarity between adjacent sentences.

    Splits at points where the cosine similarity between consecutive sentences
    drops below a percentile threshold, indicating a topic shift.

    Requires an embedding provider. Falls back to recursive splitting when
    no embedder is provided.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedder: Any = None,
        similarity_percentile: float = 0.90,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._embedder = embedder
        self._similarity_percentile = similarity_percentile
        self._fallback = RecursiveChunkStrategy(chunk_size, chunk_overlap)

    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]:
        if self._embedder is None:
            return self._fallback.split(text, metadata)

        sentences = _split_sentences(text)
        if len(sentences) <= 1:
            return self._fallback.split(text, metadata)

        try:
            embeddings = self._embedder.embed(sentences)
        except Exception:
            return self._fallback.split(text, metadata)

        breakpoints = _find_semantic_breakpoints(
            sentences, embeddings, self._similarity_percentile
        )
        chunks = _group_sentences_by_breakpoints(
            sentences, breakpoints, self._chunk_size
        )
        meta = metadata or {}
        return [
            Chunk(content=chunk_text, metadata=dict(meta), chunk_index=i)
            for i, chunk_text in enumerate(chunks)
        ]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using a simple regex."""
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_semantic_breakpoints(
    sentences: list[str],
    embeddings: list[list[float]],
    percentile: float = 0.90,
) -> set[int]:
    """Find indices where semantic breaks occur based on low cosine similarity.

    Computes similarity between each adjacent sentence pair, then marks
    positions where similarity falls below the given percentile of all
    similarities as breakpoints.
    """
    if len(sentences) < 2:
        return set()

    similarities = [
        _cosine_similarity(embeddings[i], embeddings[i + 1])
        for i in range(len(sentences) - 1)
    ]
    if not similarities:
        return set()

    sorted_sims = sorted(similarities)
    threshold_idx = int(len(sorted_sims) * (1.0 - percentile))
    threshold = sorted_sims[max(0, min(threshold_idx, len(sorted_sims) - 1))]

    return {i + 1 for i, sim in enumerate(similarities) if sim < threshold}


def _group_sentences_by_breakpoints(
    sentences: list[str],
    breakpoints: set[int],
    max_chars: int,
) -> list[str]:
    """Group sentences into chunks at semantic breakpoints, respecting max_chars.

    Sentences are grouped until a breakpoint is hit or max_chars is exceeded.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0

    for i, sent in enumerate(sentences):
        sent_len = len(sent)
        # Split at breakpoints or when max_chars would be exceeded
        if current and (i in breakpoints or current_len + sent_len > max_chars):
            chunks.append(current)
            current = []
            current_len = 0
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(current)

    return [" ".join(group) for group in chunks]


def get_chunk_strategy(name: str, chunk_size: int = 1000, chunk_overlap: int = 200, embedder: Any = None) -> ChunkStrategy:
    """Factory for chunk strategies.

    Args:
        name: Strategy name — 'recursive', 'markdown', or 'semantic'.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Overlap between consecutive chunks.
        embedder: Optional embedding provider for semantic strategy.

    Returns:
        A ChunkStrategy instance.
    """
    if name == "markdown":
        return MarkdownChunkStrategy(chunk_size, chunk_overlap)
    if name == "semantic":
        return SemanticChunkStrategy(chunk_size, chunk_overlap, embedder)
    return RecursiveChunkStrategy(chunk_size, chunk_overlap)
