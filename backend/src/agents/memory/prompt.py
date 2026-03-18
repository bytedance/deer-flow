"""Prompt templates for memory update and injection."""

import re
from typing import Any

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

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
    """Count tokens in text using tiktoken."""
    if not TIKTOKEN_AVAILABLE:
        return len(text) // 4
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4


def _rank_facts_by_relevance(
    facts: list[dict[str, Any]],
    current_context: str | None,
    similarity_weight: float = 0.6,
    confidence_weight: float = 0.4,
) -> list[dict[str, Any]]:
    """Rank facts using TF-IDF similarity to context and confidence score."""
    if not facts:
        return []

    if not current_context or not SKLEARN_AVAILABLE:
        # Fallback to confidence-only ranking if context or sklearn is unavailable
        return sorted(facts, key=lambda x: x.get("confidence", 0.0), reverse=True)

    try:
        fact_contents = [f.get("content", "") for f in facts]
        
        # Combine fact contents and current context for TF-IDF
        vectorizer = TfidfVectorizer().fit(fact_contents + [current_context])
        fact_vectors = vectorizer.transform(fact_contents)
        context_vector = vectorizer.transform([current_context])
        
        # Calculate cosine similarities
        similarities = cosine_similarity(fact_vectors, context_vector).flatten()
        
        # Calculate final scores without mutating the original fact dicts
        scored_facts: list[tuple[float, dict[str, Any]]] = []
        for i, fact in enumerate(facts):
            similarity = float(similarities[i])
            confidence = float(fact.get("confidence", 0.0))
            final_score = (similarity * similarity_weight) + (confidence * confidence_weight)
            scored_facts.append((final_score, fact))

        scored_facts.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in scored_facts]
    except Exception:
        # Graceful fallback to confidence-only
        return sorted(facts, key=lambda x: x.get("confidence", 0.0), reverse=True)


def format_memory_for_injection(
    memory_data: dict[str, Any],
    max_tokens: int = 2000,
    current_context: str | None = None,
) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).
        current_context: Optional current conversation context for fact ranking.

    Returns:
        Formatted memory string for system prompt injection.
    """
    if not memory_data:
        return ""

    sections = []
    total_tokens = 0

    # Format user context (high priority)
    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []
        for key, label in [("workContext", "Work"), ("personalContext", "Personal"), ("topOfMind", "Current Focus")]:
            ctx = user_data.get(key, {})
            if ctx.get("summary"):
                user_sections.append(f"{label}: {ctx['summary']}")

        if user_sections:
            section_content = "User Context:\n" + "\n".join(f"- {s}" for s in user_sections)
            section_tokens = _count_tokens(section_content)
            if total_tokens + section_tokens <= max_tokens:
                sections.append(section_content)
                total_tokens += section_tokens

    # Format facts (dynamic priority based on relevance)
    facts = memory_data.get("facts", [])
    if facts:
        ranked_facts = _rank_facts_by_relevance(facts, current_context)
        fact_list = []
        fact_header = "Relevant Facts:\n"
        fact_header_tokens = _count_tokens(fact_header)
        
        if total_tokens + fact_header_tokens <= max_tokens:
            current_fact_tokens = fact_header_tokens
            for fact in ranked_facts:
                content = fact.get("content", "")
                if not content:
                    continue
                
                fact_line = f"- {content}\n"
                fact_tokens = _count_tokens(fact_line)
                
                if total_tokens + current_fact_tokens + fact_tokens <= max_tokens:
                    fact_list.append(fact_line)
                    current_fact_tokens += fact_tokens
                else:
                    break
            
            if fact_list:
                sections.append(fact_header + "".join(fact_list).strip())
                total_tokens += current_fact_tokens

    # Format history (lower priority, fills remaining budget)
    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []
        for key, label in [("recentMonths", "Recent"), ("earlierContext", "Earlier")]:
            ctx = history_data.get(key, {})
            if ctx.get("summary"):
                history_sections.append(f"{label}: {ctx['summary']}")

        if history_sections:
            section_content = "History:\n" + "\n".join(f"- {s}" for s in history_sections)
            section_tokens = _count_tokens(section_content)
            if total_tokens + section_tokens <= max_tokens:
                sections.append(section_content)
                total_tokens += section_tokens
            else:
                # Try to fit at least the "Recent" part if full history doesn't fit
                recent_ctx = history_data.get("recentMonths", {})
                if recent_ctx.get("summary"):
                    recent_content = f"History (Recent):\n- {recent_ctx['summary']}"
                    recent_tokens = _count_tokens(recent_content)
                    if total_tokens + recent_tokens <= max_tokens:
                        sections.append(recent_content)
                        total_tokens += recent_tokens

    if not sections:
        return ""

    return "\n\n".join(sections)


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
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
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
