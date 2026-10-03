"""
Multi-Signal Memory Retrieval — TF-IDF keyword-based semantic retrieval.

Pattern from: Mem0 multi-signal retrieval (semantic + keyword + entity)
Implementation: TF-IDF vectorizer (no external API needed)
Scope: Episodic + Semantic memory with procedural memory classification.

Exports:
    MemoryRetrieval: Main retrieval class with build_index, search, add, stats
"""

from .retrieval import MemoryRetrieval

__all__ = ["MemoryRetrieval"]
