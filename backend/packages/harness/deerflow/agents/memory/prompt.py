"""Prompt templates for memory update and injection."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

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

Before extracting facts, perform a structured reflection on the conversation:
1. Error/Retry Detection: Did the agent encounter errors, require retries, or produce incorrect results?
   If yes, record the root cause and correct approach as a high-confidence fact with category "correction".
2. User Correction Detection: Did the user correct the agent's direction, understanding, or output?
   If yes, record the correct interpretation or approach as a high-confidence fact with category "correction".
   Include what went wrong in "sourceError" only when category is "correction" and the mistake is explicit in the conversation.
3. Project Constraint Discovery: Were any project-specific constraints discovered during the conversation?
   If yes, record them as facts with the most appropriate category and confidence.

{correction_hint}

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
  * correction: Explicit agent mistakes or user corrections, including the correct approach
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
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Use category "correction" for explicit agent mistakes or user corrections; assign confidence >= 0.95 when the correction is explicit
- Include "sourceError" only for explicit correction facts when the prior mistake or wrong approach is clearly stated; omit it otherwise
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
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: User preferences (likes/dislikes, styles, tools)
- knowledge: User's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: User's goals or objectives
- correction: Explicit corrections or mistakes to avoid repeating

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY valid JSON."""


# Module-level tiktoken encoding cache.  Populated lazily on first use;
# subsequent calls are a dict lookup (no network I/O).  Pre-warming at
# startup via :func:`warm_tiktoken_cache` avoids blocking a request on the
# (potentially slow) first ``get_encoding`` call.
#
# A *failed* load is cached as a ``(None, monotonic_timestamp)`` tuple so that
# a network-restricted environment does not re-attempt the blocking BPE
# download on every subsequent call.  After ``_TIKTOKEN_RETRY_COOLDOWN_S`` the
# failure is allowed to expire so a transient network outage can self-heal back
# to accurate tiktoken counting without a process restart.  A load already in
# progress is cached as ``_TIKTOKEN_ENCODING_LOADING`` so concurrent callers
# fall back immediately instead of spawning more blocking
# ``tiktoken.get_encoding`` threads.  Use the ``memory.token_counting: char``
# config to skip tiktoken entirely.
_TIKTOKEN_ENCODING_MISSING = object()
_TIKTOKEN_ENCODING_LOADING = object()
# Cooldown before a *failed* tiktoken load is re-attempted. This is an internal
# tuning constant rather than a user-facing config: it only affects how quickly
# the default ``tiktoken`` mode self-heals after a transient network outage.
# Deployments that want to avoid tiktoken's network dependency entirely should
# set ``memory.token_counting: char`` instead of tuning this value.
_TIKTOKEN_RETRY_COOLDOWN_S = 600.0
_tiktoken_encoding_cache: dict[str, Any] = {}
_tiktoken_encoding_cache_lock = threading.Lock()


def _get_tiktoken_encoding(encoding_name: str = "cl100k_base") -> tiktoken.Encoding | None:
    """Return a cached tiktoken encoding, or ``None`` on failure / unavailability.

    On the very first call for a given *encoding_name*, tiktoken may need to
    download the BPE data from ``openaipublic.blob.core.windows.net``.  In
    network-restricted environments (e.g. deployments behind the GFW) this
    download can block for tens of minutes before the OS TCP timeout kicks in.
    The caller must therefore be prepared for this to block and should run it
    off the event loop (e.g. via ``asyncio.to_thread``).

    A failed load is remembered (with a timestamp) so subsequent calls fall
    back immediately to character-based estimation instead of re-triggering the
    blocking download. The failure expires after ``_TIKTOKEN_RETRY_COOLDOWN_S``
    so a transient outage can self-heal without a restart. A load already in
    progress is also remembered so that a timed-out caller does not leave a
    window where later requests start more blocking ``get_encoding`` calls.
    """
    if not TIKTOKEN_AVAILABLE:
        return None

    with _tiktoken_encoding_cache_lock:
        cached = _tiktoken_encoding_cache.get(encoding_name, _TIKTOKEN_ENCODING_MISSING)
        if cached is _TIKTOKEN_ENCODING_LOADING:
            return None
        if isinstance(cached, tuple):
            # Cached failure: (None, failed_at). Retry only after cooldown.
            _, failed_at = cached
            if time.monotonic() - failed_at < _TIKTOKEN_RETRY_COOLDOWN_S:
                return None
            cached = _TIKTOKEN_ENCODING_MISSING
        if cached is not _TIKTOKEN_ENCODING_MISSING:
            return cast("tiktoken.Encoding", cached)
        _tiktoken_encoding_cache[encoding_name] = _TIKTOKEN_ENCODING_LOADING

    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:
        logger.warning("Failed to load tiktoken encoding %r; falling back to char-based estimation", encoding_name, exc_info=True)
        with _tiktoken_encoding_cache_lock:
            _tiktoken_encoding_cache[encoding_name] = (None, time.monotonic())
        return None

    with _tiktoken_encoding_cache_lock:
        _tiktoken_encoding_cache[encoding_name] = encoding
    return encoding


def _char_based_token_estimate(text: str) -> int:
    """Network-free token estimate that accounts for CJK density.

    The plain ``len(text) // 4`` heuristic is reasonable for English/code
    (~4 chars per token) but significantly under-estimates token counts for
    Chinese, Japanese, and Korean text, where the ratio is closer to 1.5-2
    characters per token. Counting CJK characters separately (~2 chars per
    token) avoids over-filling the injection budget for CJK-heavy memory
    content.
    """
    cjk = sum(
        1
        for ch in text
        if "\u4e00" <= ch <= "\u9fff"  # CJK Unified Ideographs
        or "\u3040" <= ch <= "\u30ff"  # Hiragana + Katakana
        or "\uac00" <= ch <= "\ud7a3"  # Hangul syllables
    )
    return (len(text) - cjk) // 4 + cjk // 2


def _count_tokens(text: str, encoding_name: str = "cl100k_base", *, use_tiktoken: bool = True) -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to count tokens for.
        encoding_name: The encoding to use (default: cl100k_base for GPT-4/3.5).
        use_tiktoken: When ``False``, skip tiktoken entirely and use the
            network-free character-based estimate. This guarantees no BPE
            download is attempted (see ``memory.token_counting`` config).

    Returns:
        The number of tokens in the text.
    """
    if not use_tiktoken:
        return _char_based_token_estimate(text)

    encoding = _get_tiktoken_encoding(encoding_name)
    if encoding is None:
        # Fallback to CJK-aware character estimation if tiktoken is not
        # available or the encoding failed to load.
        return _char_based_token_estimate(text)

    try:
        return len(encoding.encode(text))
    except Exception:
        # Fallback to CJK-aware character estimation on error.
        return _char_based_token_estimate(text)


def warm_tiktoken_cache() -> bool:
    """Pre-warm the tiktoken encoding cache.

    Call at startup (off the event loop) so the first request never blocks
    on the BPE download.  Returns ``True`` if the encoding was loaded
    successfully (or was already cached), ``False`` if tiktoken is
    unavailable or the download failed.
    """
    return _get_tiktoken_encoding("cl100k_base") is not None


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


# Section identifiers recorded in an injection snapshot's ``sections`` list.
_SECTION_USER_CONTEXT = "user_context"
_SECTION_HISTORY = "history"
_SECTION_FACTS = "facts"


@dataclass(slots=True)
class _InjectionParts:
    """Result of the memory-injection selection pass.

    Single source of truth shared by :func:`format_memory_for_injection` (text
    only), :func:`build_injected_memory_snapshot`, and
    :func:`build_injection_text_and_snapshot` (provenance fields). Deriving every
    output from one pass keeps the injected text and its snapshot in lockstep —
    they can never disagree about which facts were selected, how large the result
    was, or whether the truncation safety-net fired. The last point is not merely
    cosmetic: token counting is non-deterministic across calls while the tiktoken
    encoding is still loading on another thread, so two separate passes could
    straddle that transition and clip differently.
    """

    text: str
    sections_present: tuple[str, ...]
    fact_ids: tuple[str, ...]
    total_facts: int
    # Token count of the final ``text`` (post-truncation when ``truncated``), so
    # the snapshot can reuse it instead of re-tokenizing the same string.
    token_count: int
    # True when the whole-text budget safety-net clipped ``text`` *after* fact
    # selection. ``fact_ids``/``sections_present`` then describe the selected
    # set, which may slightly overstate what survives in the clipped tail;
    # consumers needing an exact match should rely on ``text`` and its hash.
    truncated: bool


def _fact_identity(fact: dict[str, Any], content: str) -> str:
    """Return a stable identifier for an injected fact.

    Prefers the fact's own ``id``; falls back to a short content hash so the
    injected set stays meaningful even for legacy facts written without an id
    (or with a blank one).
    """
    fact_id = fact.get("id")
    if isinstance(fact_id, str):
        stripped = fact_id.strip()
        if stripped:
            return stripped
        # A blank/whitespace string is not a usable identity — fall through to
        # the content hash rather than recording an empty (and colliding) id.
    elif fact_id is not None:
        return str(fact_id)
    return "sha1:" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def _build_injection_parts(memory_data: dict[str, Any], max_tokens: int = 2000, *, use_tiktoken: bool = True) -> _InjectionParts:
    """Select and format memory for injection, capturing provenance alongside.

    The text-building logic is the authoritative implementation;
    :func:`format_memory_for_injection` is a thin wrapper over it. Provenance
    (which sections, which fact ids, how many candidates) is captured during the
    same pass so a snapshot can be produced without re-deriving the selection.
    """
    if not memory_data:
        return _InjectionParts(text="", sections_present=(), fact_ids=(), total_facts=0, token_count=0, truncated=False)

    sections: list[str] = []
    sections_present: list[str] = []
    selected_fact_ids: list[str] = []
    total_facts = 0

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
            sections_present.append(_SECTION_USER_CONTEXT)

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

        background = history_data.get("longTermBackground", {})
        if background.get("summary"):
            history_sections.append(f"Background: {background['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))
            sections_present.append(_SECTION_HISTORY)

    # Format facts (sorted by confidence; include as many as token budget allows)
    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list) and facts_data:
        ranked_facts = sorted(
            (f for f in facts_data if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content").strip()),
            key=lambda fact: _coerce_confidence(fact.get("confidence"), default=0.0),
            reverse=True,
        )
        total_facts = len(ranked_facts)

        # Compute token count for existing sections once, then account
        # incrementally for each fact line to avoid full-string re-tokenization.
        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text, use_tiktoken=use_tiktoken) if base_text else 0
        # Account for the separator between existing sections and the facts section.
        facts_header = "Facts:\n"
        separator_tokens = _count_tokens("\n\n" + facts_header, use_tiktoken=use_tiktoken) if base_text else _count_tokens(facts_header, use_tiktoken=use_tiktoken)
        running_tokens = base_tokens + separator_tokens

        fact_lines: list[str] = []
        for fact in ranked_facts:
            content_value = fact.get("content")
            if not isinstance(content_value, str):
                continue
            content = content_value.strip()
            if not content:
                continue
            category = str(fact.get("category", "context")).strip() or "context"
            confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
            source_error = fact.get("sourceError")
            if category == "correction" and isinstance(source_error, str) and source_error.strip():
                line = f"- [{category} | {confidence:.2f}] {content} (avoid: {source_error.strip()})"
            else:
                line = f"- [{category} | {confidence:.2f}] {content}"

            # Each additional line is preceded by a newline (except the first).
            line_text = ("\n" + line) if fact_lines else line
            line_tokens = _count_tokens(line_text, use_tiktoken=use_tiktoken)

            if running_tokens + line_tokens <= max_tokens:
                fact_lines.append(line)
                selected_fact_ids.append(_fact_identity(fact, content))
                running_tokens += line_tokens
            else:
                break

        if fact_lines:
            sections.append("Facts:\n" + "\n".join(fact_lines))
            sections_present.append(_SECTION_FACTS)

    if not sections:
        return _InjectionParts(text="", sections_present=(), fact_ids=(), total_facts=total_facts, token_count=0, truncated=False)

    result = "\n\n".join(sections)

    # Use accurate token counting with tiktoken (or the char-based estimate
    # when use_tiktoken is False).
    truncated = False
    token_count = _count_tokens(result, use_tiktoken=use_tiktoken)
    if token_count > max_tokens:
        # Truncate to fit within token limit
        # Estimate characters to remove based on token ratio
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95% to leave margin
        result = result[:target_chars] + "\n..."
        # The per-fact budget accounting (above) is non-additive vs the
        # whole-string count, so this safety net can fire even though each fact
        # "fit". Flag it: fact_ids/sections describe the pre-clip selection.
        truncated = True
        # Recount the clipped text so ``token_count`` describes what is actually
        # injected and the snapshot can reuse it rather than re-tokenizing.
        token_count = _count_tokens(result, use_tiktoken=use_tiktoken)

    return _InjectionParts(
        text=result,
        sections_present=tuple(sections_present),
        fact_ids=tuple(selected_fact_ids),
        total_facts=total_facts,
        token_count=token_count,
        truncated=truncated,
    )


def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000, *, use_tiktoken: bool = True) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).
        use_tiktoken: When ``False``, all token counting uses the network-free
            character-based estimate instead of tiktoken (see
            ``memory.token_counting`` config). Defaults to ``True``.

    Returns:
        Formatted memory string for system prompt injection.
    """
    return _build_injection_parts(memory_data, max_tokens, use_tiktoken=use_tiktoken).text


@dataclass(slots=True)
class InjectedMemorySnapshot:
    """Minimal, always-on provenance of one memory injection.

    Records *what* memory injection placed into the model context — which facts,
    how big, which sections, and a content hash of the injected text — without
    storing the full text. Produced from the same selection pass as
    :func:`format_memory_for_injection`, so it always matches what was actually
    injected. Independent of any optional ranking-debug tracing: it is emitted
    even when tracing is disabled.

    This is the M1 unit of the context-observability ledger. Memory is injected
    once per conversation (frozen-snapshot pattern), so a snapshot is recorded
    once per thread, on its first turn.
    """

    fact_ids: tuple[str, ...]
    fact_count: int
    total_facts: int
    sections: tuple[str, ...]
    token_count: int
    max_tokens: int
    content_hash: str
    # True when the injected text was clipped by the budget safety-net after
    # fact selection. ``content_hash`` always matches the exact injected text;
    # when this is set, ``fact_ids`` may overstate the clipped tail.
    truncated: bool = False

    # Payload schema version. Bump when the shape of ``to_event_payload`` changes
    # so rows already persisted in ``run_events`` can be distinguished from new
    # ones during replay/aggregation.
    PAYLOAD_SCHEMA_VERSION = 1

    def to_event_payload(self) -> dict[str, Any]:
        """Return a small, JSON-serializable payload for the run-event ledger.

        Bounded by construction (fact ids + counts + budget + hash); it never
        carries the full injected text, which belongs in dev-debug sinks rather
        than the shared event store. Carries an explicit ``schema_version`` so
        the persisted record format can evolve safely.
        """
        return {
            "schema_version": self.PAYLOAD_SCHEMA_VERSION,
            "fact_ids": list(self.fact_ids),
            "fact_count": self.fact_count,
            "total_facts": self.total_facts,
            "sections": list(self.sections),
            "token_count": self.token_count,
            "max_tokens": self.max_tokens,
            "content_hash": self.content_hash,
            "truncated": self.truncated,
        }


def _snapshot_from_parts(parts: _InjectionParts, max_tokens: int) -> InjectedMemorySnapshot | None:
    """Build a snapshot from an already-computed selection pass.

    Centralizing this keeps every snapshot — whether produced standalone via
    :func:`build_injected_memory_snapshot` or alongside the text via
    :func:`build_injection_text_and_snapshot` — hashed over the very bytes of
    ``parts.text`` and stamped with the token count that same pass measured.
    """
    if not parts.text:
        return None
    content_hash = "sha256:" + hashlib.sha256(parts.text.encode("utf-8")).hexdigest()
    return InjectedMemorySnapshot(
        fact_ids=parts.fact_ids,
        fact_count=len(parts.fact_ids),
        total_facts=parts.total_facts,
        sections=parts.sections_present,
        token_count=parts.token_count,
        max_tokens=max_tokens,
        content_hash=content_hash,
        truncated=parts.truncated,
    )


def build_injected_memory_snapshot(memory_data: dict[str, Any], max_tokens: int = 2000, *, use_tiktoken: bool = True) -> InjectedMemorySnapshot | None:
    """Build a provenance snapshot for what memory injection would inject.

    Returns ``None`` when nothing would be injected (no memory data or an empty
    selection), so callers can cheaply skip emitting an empty snapshot. The
    ``content_hash`` is over the exact injected text, making it a drift key for
    later milestones (did the injected context go stale against live memory?).

    Prefer :func:`build_injection_text_and_snapshot` when the caller also needs
    the injected text — it derives both from a single selection pass so the two
    cannot disagree (see that function's note on tiktoken non-determinism).
    """
    parts = _build_injection_parts(memory_data, max_tokens, use_tiktoken=use_tiktoken)
    return _snapshot_from_parts(parts, max_tokens)


def build_injection_text_and_snapshot(memory_data: dict[str, Any], max_tokens: int = 2000, *, use_tiktoken: bool = True) -> tuple[str, InjectedMemorySnapshot | None]:
    """Return the injected text and its snapshot from a single selection pass.

    The text and the snapshot are derived from **one** ``_build_injection_parts``
    call, so they describe exactly the same bytes. This matters beyond saving a
    redundant pass: ``_count_tokens`` is *not* deterministic across calls while
    the tiktoken encoding is loading on another thread — it falls back to the
    char estimate until the encoding is cached, then switches. Two separate
    passes could straddle that transition and disagree about whether the
    whole-text truncation safety-net fired, recording a ``content_hash`` for
    text that was never injected. One pass closes that window.

    Returns ``("", None)`` when nothing (or only whitespace) would be injected.
    """
    parts = _build_injection_parts(memory_data, max_tokens, use_tiktoken=use_tiktoken)
    if not parts.text.strip():
        return "", None
    return parts.text, _snapshot_from_parts(parts, max_tokens)


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
