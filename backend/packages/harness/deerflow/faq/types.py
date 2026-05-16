"""FAQ module structured types — zero external dependencies."""

from dataclasses import dataclass, field
from typing import Any, Literal

FaqMatchLevel = Literal["high", "medium", "low", "none", "error"]
FaqRouteDecision = Literal["faq_only", "faq_plus_rag", "rag_only"]


@dataclass
class FaqQuery:
    """Structured input for FAQ search."""

    question: str  # User question (required)
    dataset_ids: list[str]  # FAQ knowledge base IDs (required)
    context: str | None = None  # Optional context for enhanced matching
    top_k: int = 3  # Number of candidate results
    metadata: dict[str, Any] | None = None  # Optional: user_id, session_id, etc.
    # Per-query RAGFlow search parameters
    doc_ids: list[str] | None = None  # Limit search to specific document IDs
    page: int = 1  # Page number
    size: int = 5  # Page size (max results returned)
    use_kg: bool = False  # Use knowledge graph
    cross_languages: list[str] = field(default_factory=list)  # Cross-language search
    keyword: bool = False  # Enable keyword search
    search_id: str | None = None  # Search model ID


@dataclass
class FaqItem:
    """A single matched FAQ entry."""

    question: str  # Matched FAQ question
    answer: str  # FAQ answer content
    score: float  # Similarity score (0~1)
    faq_id: str  # FAQ entry ID


@dataclass
class FaqResult:
    """Structured output from FAQ search."""

    user_question: str  # Original question echo
    best_faq: FaqItem | None = None  # Best match
    all_matches: list[FaqItem] = field(default_factory=list)  # Top-K candidates
    match_level: FaqMatchLevel = "none"  # high, medium, low, none, or error
    route_decision: FaqRouteDecision = "rag_only"  # faq_only, faq_plus_rag, or rag_only
    should_call_rag: bool = True  # Whether the caller should retrieve broader RAG context
    metadata: dict[str, Any] = field(default_factory=dict)  # retrieval_time_ms etc.
