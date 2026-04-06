"""Prompt templates for memory update and injection."""

import math
import re
from collections import Counter
from typing import Any

from deerflow.agents.memory.layers import group_facts_by_layer, layer_label, layer_order_for_context, ensure_layer_index

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

_SIMILARITY_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-/][A-Za-z0-9_]+)*")
_CJK_RANGE = ("\u4e00", "\u9fff")
_STOPWORDS = {
    "a",
    "about",
    "after",
    "again",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "but",
    "by",
    "can",
    "could",
    "do",
    "does",
    "doing",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "more",
    "my",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "such",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "too",
    "up",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
}

# Prompt template for updating memory based on conversation
MEMORY_UPDATE_PROMPT = """You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.

Current Memory State:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the user
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the memory sections as needed following the detailed length guidelines below

Memory Section Guidelines:

**User Context** (Current state - concise summaries):
- workContext: Professional role, company, key projects, main technologies (2-3 sentences)
  Example: Core contributor, project names with metrics (16k+ stars), technical stack
- personalContext: Languages, communication preferences, key interests (1-2 sentences)
  Example: Bilingual capabilities, specific interest areas, expertise domains
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences, detailed paragraph)
  Example: Primary project work, parallel technical investigations, ongoing learning/tracking
  Include: Active implementation work, troubleshooting issues, market/research interests
  Note: This captures SEVERAL concurrent focus areas, not just one task

**History** (Temporal context - rich paragraphs):
- recentMonths: Detailed summary of recent activities (4-6 sentences or 1-2 paragraphs)
  Timeline: Last 1-3 months of interactions
  Include: Technologies explored, projects worked on, problems solved, interests demonstrated
- earlierContext: Important historical patterns (3-5 sentences or 1 paragraph)
  Timeline: 3-12 months ago
  Include: Past projects, learning journeys, established patterns
- longTermBackground: Persistent background and foundational context (2-4 sentences)
  Timeline: Overall/foundational information
  Include: Core expertise, longstanding interests, fundamental working style

**Facts Extraction**:
- Extract specific, quantifiable details (e.g., "16k+ GitHub stars", "200+ datasets")
- Include proper nouns (company names, project names, technology names)
- Preserve technical terminology and version numbers
- Categories:
  * preference: Tools, styles, approaches user prefers/dislikes
  * knowledge: Specific expertise, technologies mastered, domain knowledge
  * context: Background facts (job title, projects, locations, languages)
  * behavior: Working patterns, communication habits, problem-solving approaches
  * goal: Stated objectives, learning targets, project ambitions
- Confidence levels:
  * 0.9-1.0: Explicitly stated facts ("I work on X", "My role is Y")
  * 0.7-0.8: Strongly implied from actions/discussions
  * 0.5-0.6: Inferred patterns (use sparingly, only for clear patterns)

**What Goes Where**:
- workContext: Current job, active projects, primary tech stack
- personalContext: Languages, personality, interests outside direct work tasks
- topOfMind: Multiple ongoing priorities and focus areas user cares about recently (gets updated most frequently)
  Should capture 3-5 concurrent themes: main work, side explorations, learning/tracking interests
- recentMonths: Detailed account of recent technical explorations and work
- earlierContext: Patterns from slightly older interactions still relevant
- longTermBackground: Unchanging foundational facts about the user

**Multilingual Content**:
- Preserve original language for proper nouns and company names
- Keep technical terms in their original form (DeepSeek, LangGraph, etc.)
- Note language capabilities in personalContext

Output Format (JSON):
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Remove facts that are contradicted by new information
- When updating topOfMind, integrate new focus areas while removing completed/abandoned ones
  Keep 3-5 concurrent focus themes that are still active and relevant
- For history sections, integrate new information chronologically into appropriate time period
- Preserve technical accuracy - keep exact names of technologies, companies, projects
- Focus on information useful for future interactions and personalization
- IMPORTANT: Do NOT record file upload events in memory. Uploaded files are
  session-specific and ephemeral — they will not be accessible in future sessions.
  Recording upload events causes confusion in subsequent conversations.

Return ONLY valid JSON, no explanation or markdown."""


# Prompt template for extracting facts from a single message
FACT_EXTRACTION_PROMPT = """Extract factual information about the user from this message.

Message:
{message}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: User preferences (likes/dislikes, styles, tools)
- knowledge: User's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: User's goals or objectives

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY valid JSON."""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to count tokens for.
        encoding_name: The encoding to use (default: cl100k_base for GPT-4/3.5).

    Returns:
        The number of tokens in the text.
    """
    if not TIKTOKEN_AVAILABLE:
        # Fallback to character-based estimation if tiktoken is not available
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # Fallback to character-based estimation on error
        return len(text) // 4


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    """Coerce a confidence-like value to a bounded float in [0, 1].

    Non-finite values (NaN, inf, -inf) are treated as invalid and fall back
    to the default before clamping, preventing them from dominating ranking.
    The ``default`` parameter is assumed to be a finite value.
    """
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))
    if not math.isfinite(confidence):
        return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, confidence))


def _normalize_text(value: Any) -> str:
    """Normalize arbitrary content into a plain text string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces: list[str] = []
        for part in value:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    pieces.append(text_val)
                else:
                    nested = part.get("content")
                    if isinstance(nested, str):
                        pieces.append(nested)
        return " ".join(piece for piece in pieces if piece)
    if isinstance(value, dict):
        text_val = value.get("text")
        if isinstance(text_val, str):
            return text_val
        nested = value.get("content")
        if isinstance(nested, str):
            return nested
    if value is None:
        return ""
    return str(value)


def _tokenize_for_similarity(text: str) -> list[str]:
    """Tokenize text for lightweight relevance scoring."""
    if not text:
        return []

    tokens = [token for token in _SIMILARITY_TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS and len(token) > 1]
    if tokens:
        return tokens

    cjk_tokens = [char for char in text if _CJK_RANGE[0] <= char <= _CJK_RANGE[1]]
    return [token for token in cjk_tokens if token.strip()]


def _build_document_frequencies(memory_data: dict[str, Any]) -> tuple[Counter[str], int]:
    """Build document frequencies across all stored memory text."""
    documents: list[str] = []

    user_data = memory_data.get("user", {})
    if isinstance(user_data, dict):
        for section in ("workContext", "personalContext", "topOfMind"):
            section_data = user_data.get(section, {})
            if isinstance(section_data, dict):
                summary = section_data.get("summary", "")
                if isinstance(summary, str) and summary.strip():
                    documents.append(summary)

    history_data = memory_data.get("history", {})
    if isinstance(history_data, dict):
        for section in ("recentMonths", "earlierContext", "longTermBackground"):
            section_data = history_data.get(section, {})
            if isinstance(section_data, dict):
                summary = section_data.get("summary", "")
                if isinstance(summary, str) and summary.strip():
                    documents.append(summary)

    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list):
        for fact in facts_data:
            if not isinstance(fact, dict):
                continue
            content = fact.get("content")
            if isinstance(content, str) and content.strip():
                documents.append(content)

    doc_freq: Counter[str] = Counter()
    for doc in documents:
        terms = set(_tokenize_for_similarity(doc))
        if not terms:
            continue
        doc_freq.update(terms)

    return doc_freq, max(len(documents), 1)


def _term_idf(term: str, doc_freq: Counter[str], total_docs: int) -> float:
    """Compute a lightweight inverse document frequency for a term."""
    return math.log((1.0 + total_docs) / (1.0 + doc_freq.get(term, 0))) + 1.0


def _score_fact_for_context(
    fact: dict[str, Any],
    context_terms: set[str],
    doc_freq: Counter[str],
    total_docs: int,
    similarity_weight: float,
    confidence_weight: float,
) -> float:
    """Blend fact confidence with relevance to the supplied context."""
    confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
    if not context_terms:
        return confidence

    content = fact.get("content")
    if not isinstance(content, str) or not content.strip():
        return confidence * confidence_weight

    fact_terms = set(_tokenize_for_similarity(content))
    if not fact_terms:
        return confidence * confidence_weight

    overlap = fact_terms & context_terms
    if not overlap:
        return confidence * confidence_weight

    context_weight = sum(_term_idf(term, doc_freq, total_docs) for term in context_terms)
    if context_weight <= 0:
        similarity = 0.0
    else:
        overlap_weight = sum(_term_idf(term, doc_freq, total_docs) for term in overlap)
        similarity = overlap_weight / context_weight

    total_weight = similarity_weight + confidence_weight
    if total_weight <= 0:
        return confidence
    return ((similarity * similarity_weight) + (confidence * confidence_weight)) / total_weight


def _rank_facts_for_context(
    facts: list[dict[str, Any]],
    context_terms: set[str],
    doc_freq: Counter[str],
    total_docs: int,
    similarity_weight: float,
    confidence_weight: float,
) -> list[dict[str, Any]]:
    """Rank facts by a blended context score and stored confidence."""
    return sorted(
        facts,
        key=lambda fact: (
            _score_fact_for_context(
                fact,
                context_terms,
                doc_freq,
                total_docs,
                similarity_weight,
                confidence_weight,
            ),
            _coerce_confidence(fact.get("confidence"), default=0.0),
            str(fact.get("content", "")).casefold(),
        ),
        reverse=True,
    )


def format_memory_for_injection(
    memory_data: dict[str, Any],
    max_tokens: int = 2000,
    current_context: str | None = None,
    similarity_weight: float = 0.35,
    confidence_weight: float = 0.65,
) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).
        current_context: Optional current conversation context used to rank
            facts by relevance instead of confidence alone.
        similarity_weight: Weight used for context similarity when ranking facts.
        confidence_weight: Weight used for stored fact confidence when ranking facts.

    Returns:
        Formatted memory string for system prompt injection.
    """
    if not memory_data:
        return ""

    memory_data = ensure_layer_index(memory_data)
    sections = []

    # Format user context
    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {work_ctx['summary']}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {personal_ctx['summary']}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {top_of_mind['summary']}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    # Format history
    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {recent['summary']}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {earlier['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    # Format facts grouped by memory layer; include as many as token budget allows
    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list) and facts_data:
        context_text = _normalize_text(current_context).strip()
        context_terms = set(_tokenize_for_similarity(context_text))
        doc_freq, total_docs = _build_document_frequencies(memory_data)
        grouped_facts = group_facts_by_layer(memory_data)
        preferred_layers = layer_order_for_context(context_text)
        preferred_index = {layer: idx for idx, layer in enumerate(preferred_layers)}

        layer_candidates: list[tuple[float, str, list[dict[str, Any]]]] = []
        for layer_name in preferred_layers:
            layer_facts = grouped_facts.get(layer_name, [])
            if not layer_facts:
                continue
            ranked_layer_facts = _rank_facts_for_context(
                layer_facts,
                context_terms,
                doc_freq,
                total_docs,
                similarity_weight,
                confidence_weight,
            )
            top_score = _score_fact_for_context(
                ranked_layer_facts[0],
                context_terms,
                doc_freq,
                total_docs,
                similarity_weight,
                confidence_weight,
            )
            layer_candidates.append((top_score, layer_name, ranked_layer_facts))

        layer_candidates.sort(key=lambda item: (-item[0], preferred_index.get(item[1], len(preferred_layers))))

        layer_blocks: list[str] = []
        for _layer_score, layer_name, ranked_layer_facts in layer_candidates:
            block_text = f"- {layer_label(layer_name)}:"
            block_updated = False

            for fact in ranked_layer_facts:
                content_value = fact.get("content")
                if not isinstance(content_value, str):
                    continue
                content = content_value.strip()
                if not content:
                    continue
                category = str(fact.get("category", "context")).strip() or "context"
                confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
                line = f"  - [{category} | {confidence:.2f}] {content}"
                candidate_block = f"{block_text}\n{line}"
                candidate_sections = sections + ["Layered Memory:\n" + "\n".join(layer_blocks + [candidate_block])]
                candidate_result = "\n\n".join(candidate_sections)

                if _count_tokens(candidate_result) <= max_tokens:
                    block_text = candidate_block
                    block_updated = True
                else:
                    break

            if block_updated:
                layer_blocks.append(block_text)

        if layer_blocks:
            sections.append("Layered Memory:\n" + "\n".join(layer_blocks))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    # Use accurate token counting with tiktoken
    token_count = _count_tokens(result)
    if token_count > max_tokens:
        # Truncate to fit within token limit
        # Estimate characters to remove based on token ratio
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95% to leave margin
        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """Format conversation messages for memory update prompt.

    Args:
        messages: List of conversation messages.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        # Handle content that might be a list (multimodal)
        if isinstance(content, list):
            text_parts = []
            for p in content:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict):
                    text_val = p.get("text")
                    if isinstance(text_val, str):
                        text_parts.append(text_val)
            content = " ".join(text_parts) if text_parts else str(content)

        # Strip uploaded_files tags from human messages to avoid persisting
        # ephemeral file path info into long-term memory.  Skip the turn entirely
        # when nothing remains after stripping (upload-only message).
        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        # Truncate very long messages
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
