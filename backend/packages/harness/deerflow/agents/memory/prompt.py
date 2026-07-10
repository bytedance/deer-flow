"""Prompt templates for memory update and injection."""

from __future__ import annotations

import logging
import math
import re
import threading
import time
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
  "factsToRemove": ["fact_id_1", "fact_id_2"],
  "staleFactsToRemove": [{{ "id": "fact_id", "reason": "brief explanation" }}],
  "factsToConsolidate": [
    {{
      "sourceIds": ["fact_id_1", "fact_id_2"],
      "consolidated": {{ "content": "synthesized fact", "category": "knowledge", "confidence": 0.9 }}
    }}
  ]
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

{staleness_review_section}

{consolidation_section}

Return ONLY valid JSON, no explanation or markdown."""


# Prompt section injected into MEMORY_UPDATE_PROMPT when staleness review triggers.
# Surfaces aged facts explicitly so the LLM can semantically judge each one,
# rather than relying on passive contradiction from the current conversation.
STALENESS_REVIEW_PROMPT = """## Staleness Review

The following facts were created more than {age_days} days ago and may no longer
accurately reflect the user's current situation. Review each one against the full
conversation context and your understanding of the user.

<stale_facts>
{stale_facts}
</stale_facts>

For each fact, decide KEEP or REMOVE:
- KEEP: Still likely valid — even if not mentioned in this conversation.
  Stable attributes (native language, core expertise, personality traits) often
  remain true indefinitely.
- REMOVE: Outdated, contradicted by recent context, or no longer relevant.
  Examples: tech-stack migrations, job changes, relocated offices, abandoned projects.

Add REMOVE decisions to "staleFactsToRemove" in your output JSON.
Each entry must be {{"id": "fact_id", "reason": "brief explanation"}}.
The reason should cite what signal in the conversation (or absence thereof)
supports the removal.

Be conservative — when in doubt, KEEP. Removing a valid fact is worse than
keeping a slightly stale one, because the next review cycle will re-evaluate it."""


# Prompt section injected into MEMORY_UPDATE_PROMPT when consolidation triggers.
# Surfaces fact groups that have accumulated many entries in the same category
# so the LLM can synthesize them into fewer, richer facts.
CONSOLIDATION_PROMPT = """## Memory Consolidation

The following fact categories have accumulated many individual entries.
Review each group and identify facts that can be synthesized into a single,
richer consolidated fact that preserves all key information.

{consolidation_groups}

For each group, decide:
- CONSOLIDATE: Multiple facts can be merged into one richer fact.
  Specify the source fact IDs and the consolidated content.
- SKIP: Facts are distinct enough to remain separate.

Add consolidation decisions to "factsToConsolidate" in your output JSON.
Each entry: {{"sourceIds": ["fact_id_1", "fact_id_2"], "consolidated": {{"content": "...", "category": "...", "confidence": 0.9}}}}

Rules:
- The consolidated fact must preserve ALL key details from source facts
- Only consolidate facts that describe the same aspect of the user
- Confidence of consolidated fact = max of source confidences
- Be conservative — when in doubt, keep facts separate
- Maximum {max_groups} consolidation groups per cycle"""


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


def _format_fact_line(fact: dict[str, Any]) -> str | None:
    """Build a single formatted fact line, or return ``None`` for invalid facts.

    Extracted as a shared helper so the guaranteed-injection and regular-injection
    paths produce identical line formatting.
    """
    content_value = fact.get("content")
    if not isinstance(content_value, str):
        return None
    content = content_value.strip()
    if not content:
        return None
    category = str(fact.get("category", "context")).strip() or "context"
    confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
    source_error = fact.get("sourceError")
    if category == "correction" and isinstance(source_error, str) and source_error.strip():
        return f"- [{category} | {confidence:.2f}] {content} (avoid: {source_error.strip()})"
    return f"- [{category} | {confidence:.2f}] {content}"


def _select_fact_lines(
    ranked_facts: list[dict[str, Any]],
    *,
    token_budget: int,
    use_tiktoken: bool,
) -> tuple[list[str], int]:
    """Greedily select formatted fact lines within a *line-only* token budget.

    This function is intentionally **header-agnostic**: it counts only the
    fact lines themselves (including ``\\n`` separators between lines).  The
    caller is responsible for reserving tokens for the ``"Facts:\\n"`` header
    and any inter-section ``"\\n\\n"`` separator *before* calling this
    function, and passing the remaining capacity as *token_budget*.

    Stops at the first fact that would exceed the budget so the caller's
    pre-sorted order (typically confidence-descending) is preserved strictly:
    a shorter lower-ranked fact can never slip ahead of a skipped
    higher-ranked one.

    Args:
        ranked_facts: Facts pre-sorted by the caller's preferred ranking.
        token_budget: Maximum tokens available for fact lines only.
        use_tiktoken: Whether to use tiktoken for counting.

    Returns:
        ``(selected_lines, consumed_tokens)`` — *consumed_tokens* is the
        exact token cost of the returned lines (including inter-line
        ``\\n`` separators, but *not* a leading header).
    """
    lines: list[str] = []
    consumed = 0
    for fact in ranked_facts:
        formatted = _format_fact_line(fact)
        if formatted is None:
            continue
        line_text = ("\n" + formatted) if lines else formatted
        line_tokens = _count_tokens(line_text, use_tiktoken=use_tiktoken)
        if consumed + line_tokens > token_budget:
            break
        lines.append(formatted)
        consumed += line_tokens
    return lines, consumed


def _fallback_format_facts(
    valid_facts: list[dict[str, Any]],
    *,
    preceding_section_cost: int,
    max_tokens: int,
    use_tiktoken: bool,
) -> tuple[str, list[str]] | tuple[None, None]:
    """Confidence-only ranking used when the primary path raises an exception.

    Returns a tuple ``(section_text, fact_lines)`` where ``section_text`` is the
    formatted ``"Facts:\\n..."`` section string (without any leading inter-section
    separator — the caller owns that), and ``fact_lines`` are the individual lines
    that make up the facts block.  Both elements are ``None`` if no facts survive.

    Returning the lines separately lets the caller track them for the
    structure-aware safety truncation so fallback facts enjoy the same
    protected-suffix treatment as facts emitted by the primary path.

    *valid_facts* is the already-filtered fact list built by the primary path so
    the fallback does not redo validation work.  *preceding_section_cost* is the
    tokens already consumed by user-context / history sections (used to derive
    the remaining budget).
    """
    ranked = sorted(valid_facts, key=lambda f: _coerce_confidence(f.get("confidence"), default=0.0), reverse=True)

    header = "Facts:\n"
    overhead = _count_tokens(header, use_tiktoken=use_tiktoken)
    line_budget = max_tokens - preceding_section_cost - overhead
    if line_budget <= 0:
        return None, None

    lines, _ = _select_fact_lines(ranked, token_budget=line_budget, use_tiktoken=use_tiktoken)
    if not lines:
        return None, None
    return header + "\n".join(lines), lines


def format_memory_for_injection(
    memory_data: dict[str, Any],
    max_tokens: int = 2000,
    *,
    use_tiktoken: bool = True,
    guaranteed_categories: list[str] | None = None,
    guaranteed_token_budget: int = 500,
) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).
        use_tiktoken: When ``False``, all token counting uses the network-free
            character-based estimate instead of tiktoken (see
            ``memory.token_counting`` config). Defaults to ``True``.
        guaranteed_categories: Fact categories that must always be injected
            regardless of the regular token budget. These facts draw from a
            separate *guaranteed_token_budget*. When ``None`` or empty, all
            facts compete for the same budget (original behaviour).
        guaranteed_token_budget: Token ceiling for the guaranteed section.
            In the common case the guaranteed lines *displace* regular lines
            within *max_tokens* (the total output stays ≤ ``max_tokens``);
            the budget becomes truly additive only when the guaranteed lines
            alone would push the assembled output past *max_tokens*, at which
            point the safety-truncation ceiling is raised to
            ``max_tokens + guaranteed_actual_usage`` to protect them.
            Ignored when *guaranteed_categories* is ``None`` or empty.

    Returns:
        Formatted memory string for system prompt injection.
    """
    if not memory_data:
        return ""

    # Reject a bare string explicitly: iterating a ``str`` yields single
    # characters, which would silently produce a meaningless frozenset of
    # letters and turn the guarantee off without any warning.  Config-layer
    # callers go through Pydantic (which enforces ``list[str]``), so this
    # only guards the public helper surface.
    if isinstance(guaranteed_categories, str):
        raise TypeError("guaranteed_categories must be an iterable of strings, not a bare str")
    effective_guaranteed: frozenset[str] = frozenset(c.strip() for c in guaranteed_categories if isinstance(c, str) and c.strip()) if guaranteed_categories else frozenset()

    sections: list[str] = []

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

        background = history_data.get("longTermBackground", {})
        if background.get("summary"):
            history_sections.append(f"Background: {background['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    # ── Facts ────────────────────────────────────────────────────────────────
    #
    # Design notes
    # ~~~~~~~~~~~~
    # • A single ``"Facts:\\n"`` header is emitted at most once.
    # • Guaranteed-category facts are selected first from their own
    #   *guaranteed_token_budget* and placed at the front of the Facts block,
    #   so they cannot be evicted by regular facts.  In the common case the
    #   total output still fits within *max_tokens* (guaranteed lines displace
    #   regular ones); the budget becomes truly additive only when the
    #   guaranteed lines alone push the output past *max_tokens*, in which
    #   case the safety-truncation ceiling is raised accordingly.
    # • Regular facts draw from *max_tokens* only.
    # • All token accounting (header, separators, lines) is performed here
    #   in the caller; the ``_select_fact_lines`` helper is header-agnostic.
    # • When the primary path raises any exception, ``_fallback_format_facts``
    #   performs a single-pass confidence-only ranking.
    facts_data = memory_data.get("facts", [])
    guaranteed_line_tokens = 0  # used later for the effective truncation limit
    # Initialise the facts-block markers at function scope (alongside
    # ``guaranteed_line_tokens`` above) so the structure-aware truncation at the
    # bottom can reference them even when there are no facts and the block below
    # never runs. Otherwise the overflow path raises ``UnboundLocalError`` when a
    # user has sizeable context/history but an empty ``facts`` list.
    facts_header = "Facts:\n"
    all_fact_lines: list[str] = []
    if isinstance(facts_data, list) and facts_data:
        # Token cost of sections built above (user context, history).
        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text, use_tiktoken=use_tiktoken) if base_text else 0

        # Pre-filter valid facts *before* entering the try so the except
        # path can pass the same list straight into the fallback without
        # redoing validation work on the hot prompt-injection path.
        valid_facts = [f for f in facts_data if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content", "").strip()]

        try:
            # Partition valid facts into guaranteed vs regular groups.
            # Use the *raw* category field (no ``or "context"`` default) so
            # a category-less legacy fact is never silently promoted into
            # a guaranteed pool whose operator configured
            # ``guaranteed_categories=["context"]``.  Missing-category facts
            # always fall through to the regular path.
            def _confidence_key(fact: dict[str, Any]) -> float:
                return _coerce_confidence(fact.get("confidence"), default=0.0)

            if effective_guaranteed:

                def _category_match(fact: dict[str, Any]) -> bool:
                    raw = fact.get("category")
                    if not isinstance(raw, str):
                        return False
                    cat = raw.strip()
                    return bool(cat) and cat in effective_guaranteed

                guaranteed = sorted(
                    [f for f in valid_facts if _category_match(f)],
                    key=_confidence_key,
                    reverse=True,
                )
                regular = sorted(
                    [f for f in valid_facts if not _category_match(f)],
                    key=_confidence_key,
                    reverse=True,
                )
            else:
                guaranteed = []
                regular = sorted(valid_facts, key=_confidence_key, reverse=True)

            # ── Phase 1: select guaranteed lines ──────────────────────────
            header_cost = _count_tokens(facts_header, use_tiktoken=use_tiktoken)

            guaranteed_lines: list[str] = []
            if guaranteed:
                guaranteed_line_budget = guaranteed_token_budget
                guaranteed_lines, guaranteed_line_tokens = _select_fact_lines(
                    guaranteed,
                    token_budget=guaranteed_line_budget,
                    use_tiktoken=use_tiktoken,
                )

            # ── Phase 2: select regular lines ────────────────────────────
            # Regular facts compete for *max_tokens* (the main budget).
            # Subtract everything already accounted for:
            #   base sections + inter-section separator + header
            #   + guaranteed lines + the inter-group ``\n`` that joins the
            #   regular block to the guaranteed block (when both are present).
            regular_lines: list[str] = []
            if regular:
                inter_group_newline_tokens = _count_tokens("\n", use_tiktoken=use_tiktoken) if guaranteed_lines else 0
                used_before_regular = base_tokens + header_cost + guaranteed_line_tokens + inter_group_newline_tokens
                regular_line_budget = max_tokens - used_before_regular
                if regular_line_budget > 0:
                    regular_lines, _ = _select_fact_lines(
                        regular,
                        token_budget=regular_line_budget,
                        use_tiktoken=use_tiktoken,
                    )

            # ── Emit a single "Facts:" section ───────────────────────────
            # Leading inter-section separator is NOT embedded here; the
            # final ``"\n\n".join(sections)`` is the single source of truth
            # for section-to-section spacing, preventing the prior
            # double-``\n\n`` bug.
            all_fact_lines = guaranteed_lines + regular_lines
            if all_fact_lines:
                section_text = facts_header + "\n".join(all_fact_lines)
                sections.append(section_text)

        except Exception:
            # ── Fallback: confidence-only ranking, single budget ─────────
            # Any unexpected error in the partition / guaranteed path must
            # not prevent memory injection entirely.  Fall back to the
            # original single-pass confidence ranking.  Re-use the
            # pre-filtered ``valid_facts`` so we don't redo validation work
            # on the hot fallback path.
            logger.warning(
                "Memory injection: guaranteed-category path failed, falling back to confidence-only ranking",
                exc_info=True,
            )
            fallback, fallback_lines = _fallback_format_facts(
                valid_facts,
                preceding_section_cost=base_tokens,
                max_tokens=max_tokens,
                use_tiktoken=use_tiktoken,
            )
            if fallback:
                sections.append(fallback)
                # Surface the fallback's lines to ``all_fact_lines`` so the
                # structure-aware truncation below treats fallback facts as a
                # protected suffix too.  Without this, a large user-context
                # prefix could silently clip fallback facts via the original
                # prefix-cut.
                all_fact_lines = fallback_lines

    if not sections:
        return ""

    result = "\n\n".join(sections)

    token_count = _count_tokens(result, use_tiktoken=use_tiktoken)
    effective_limit = max_tokens + guaranteed_line_tokens
    if token_count > effective_limit:
        # Structure-aware truncation: the ``Facts:\n...`` block is treated as
        # a *protected suffix* so guaranteed-category facts — the very facts
        # this PR exists to preserve — can never be silently discarded by a
        # prefix-cut on overflow.  Only the preceding (user-context / history)
        # sections are eligible for truncation; if they alone exceed the
        # budget available after reserving the Facts block, they are clipped
        # from the tail.  When *guaranteed_line_tokens* is zero (no
        # guaranteed categories configured or no facts survived), the
        # equation collapses to the original prefix-truncation against
        # ``max_tokens``, so backward compatibility is preserved.
        facts_block = (facts_header + "\n".join(all_fact_lines)) if all_fact_lines else ""
        facts_block_tokens = _count_tokens(facts_block, use_tiktoken=use_tiktoken)
        separator_tokens = _count_tokens("\n\n", use_tiktoken=use_tiktoken)
        budget_for_non_facts = max(
            0,
            effective_limit - facts_block_tokens - (separator_tokens if facts_block else 0),
        )

        # Build the preceding (non-facts) portion from *sections* excluding
        # the trailing Facts block.
        preceding_sections = sections[:-1] if all_fact_lines else sections
        preceding = "\n\n".join(preceding_sections)

        if preceding:
            preceding_tokens = _count_tokens(preceding, use_tiktoken=use_tiktoken)
            if preceding_tokens > budget_for_non_facts:
                char_per_token = len(preceding) / max(preceding_tokens, 1)
                target_chars = int(budget_for_non_facts * char_per_token * 0.95)
                preceding = preceding[:target_chars].rstrip() + "\n..."
            result = (preceding + "\n\n" + facts_block) if facts_block else preceding
        else:
            result = facts_block

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
