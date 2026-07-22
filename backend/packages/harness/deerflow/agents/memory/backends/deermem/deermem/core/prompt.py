"""Prompt templates for memory update and injection."""

from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, cast

import yaml
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class PromptConfigurationError(ValueError):
    """A prompt-template configuration error (bad yaml, missing key, invalid
    placeholder). Raised by :func:`load_prompt` and :func:`load_prompt_messages`
    instead of a bare :class:`ValueError` so callers can distinguish permanent
    configuration failures from recoverable runtime errors."""


try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# ── Externalized prompt templates ───────────────────────────────────────
#
# The four memory prompts live as yaml files under ``core/prompts/`` (loaded by
# :func:`load_prompt`) so they can be overridden per-agent or from an external
# dir without code changes. The bundled defaults are byte-identical to the former
# module-level constants, so zero-config behaviour is unchanged. Templates use
# ``.format`` syntax (``{var}`` substitution, ``{{``/``}}`` for literal braces);
# html-escaping stays at the assembly layer (``_escape_memory_for_prompt`` in
# updater.py / ``format_conversation_for_update`` here), never inside the
# template strings, so values are not double-escaped.

_PROMPTS_DEFAULT_DIR = Path(__file__).resolve().parent / "prompts"

# Cache for load_prompt: repeated calls with the same (name, agent, dir) return
# the cached template string without re-reading the yaml file. The shim constants
# below also populate this cache at import time for the bundled defaults.
_PROMPT_CACHE: dict[tuple[str, str | None, str | None], str] = {}

# Cache for load_prompt_messages: stores parsed raw templates (list of {role,
# content} dicts) keyed by (name, agent, dir). On a cache hit the templates are
# rendered with the caller's variables; the file is only read once per key.
_CHAT_TEMPLATE_CACHE: dict[tuple[str, str | None, str | None], tuple[list[dict[str, str]], str]] = {}


def _render_messages(
    raw_templates: list[dict[str, str]],
    variables: dict[str, Any],
    source_path: str,
) -> list[BaseMessage]:
    """Render cached chat templates with fresh *variables*."""
    messages: list[BaseMessage] = []
    for tmpl in raw_templates:
        content = tmpl["content"]
        try:
            content = content.format(**variables)
        except (KeyError, ValueError) as e:
            raise PromptConfigurationError(f"Invalid placeholder in {source_path!r} (content of role={tmpl['role']!r}): {e}") from e
        if tmpl["role"] == "system":
            messages.append(SystemMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


def load_prompt(
    name: str,
    *,
    agent_name: str | None = None,
    prompts_dir: str | None = None,
) -> str:
    """Load a prompt template by name (agent override > default).

    Reads ``{prompts_dir}/{agent_name}/{name}.yaml`` if present, else
    ``{prompts_dir}/{name}.yaml``. ``prompts_dir`` defaults to the package's
    bundled ``core/prompts/``. Returns the raw ``template`` string (``.format``
    syntax); the caller renders it with ``.format(**vars)``.

    Results are cached per ``(name, agent_name, prompts_dir)`` so the filesystem
    read happens at most once per combination (typically once per process for
    the bundled defaults).
    """
    cache_key = (name, agent_name, prompts_dir)
    cached = _PROMPT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    base = Path(prompts_dir) if prompts_dir else _PROMPTS_DEFAULT_DIR
    candidates: list[Path] = [base / f"{name}.yaml"]
    if agent_name:
        candidates.insert(0, base / agent_name / f"{name}.yaml")
    for path in candidates:
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                raise PromptConfigurationError(f"Invalid YAML in {path}: {e}") from e
            data = data or {}
            fmt = data.get("format", "text")
            if fmt != "text":
                raise PromptConfigurationError(f"Expected format='text' in {path}, got {fmt!r}; use load_prompt_messages() for chat-format templates")
            template = data.get("template")
            if not isinstance(template, str) or not template:
                raise PromptConfigurationError(f"Missing or empty 'template' key in {path}")
            _PROMPT_CACHE[cache_key] = template
            return template
    searched = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"prompt template not found: {name} (searched: {searched})")


def load_prompt_messages(
    name: str,
    variables: dict[str, Any],
    *,
    agent_name: str | None = None,
    prompts_dir: str | None = None,
) -> list[BaseMessage]:
    """Load + render a chat-form prompt template. Returns ``list[BaseMessage]``.

    Reads ``{prompts_dir}/{agent_name}/{name}.chat.yaml`` if present, else
    ``{prompts_dir}/{name}.chat.yaml``. Each message's ``content`` is rendered
    with ``.format(**variables)``. The system content has no variables (only
    literal ``{{ }}`` JSON braces), so it renders byte-identical every call --
    prefix-cache friendly, mirroring the lead agent's static system prompt.

    The raw templates (role + content before substitution) are cached per
    ``(name, agent, prompts_dir)`` so the yaml file is only read once; only
    per-call rendering runs on each invocation.

    For the text form (single string), use :func:`load_prompt` instead.
    """
    cache_key = (name, agent_name, prompts_dir)
    cached_chat = _CHAT_TEMPLATE_CACHE.get(cache_key)
    if cached_chat is not None:
        raw_templates, source_path = cached_chat
        return _render_messages(raw_templates, variables, source_path)

    base = Path(prompts_dir) if prompts_dir else _PROMPTS_DEFAULT_DIR
    candidates: list[Path] = [base / f"{name}.chat.yaml"]
    if agent_name:
        candidates.insert(0, base / agent_name / f"{name}.chat.yaml")
    for path in candidates:
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                raise PromptConfigurationError(f"Invalid YAML in {path}: {e}") from e
            data = data or {}
            fmt = data.get("format", "chat")
            if fmt != "chat":
                raise PromptConfigurationError(f"Expected format='chat' in {path}, got {fmt!r}; use load_prompt() for text-format templates")
            msg_list = data.get("messages")
            if not isinstance(msg_list, list) or not msg_list:
                raise PromptConfigurationError(f"Missing or empty 'messages' key in {path}")
            raw_templates: list[dict[str, str]] = []
            for msg in msg_list:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                raw_templates.append({"role": role, "content": content})
            _CHAT_TEMPLATE_CACHE[cache_key] = (raw_templates, str(path))
            return _render_messages(raw_templates, variables, str(path))
    searched = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"chat prompt template not found: {name} (searched: {searched})")


# Module-level aliases for the injected text sections (staleness_review /
# consolidation / fact_extraction). Each loads its bundled yaml template once
# at import. ``memory_update`` is NOT here -- it uses the chat form via
# :func:`load_prompt_messages` (system/user split, mirroring the lead agent's
# static system prompt).
STALENESS_REVIEW_PROMPT = load_prompt("staleness_review")
CONSOLIDATION_PROMPT = load_prompt("consolidation")
FACT_EXTRACTION_PROMPT = load_prompt("fact_extraction")


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
    # These fields are user-editable (POST/PATCH /api/memory, import) and are
    # rendered into the <memory> block of the lead-agent system prompt. Escape
    # them so a value like "</memory></system-reminder>" cannot close the block
    # and relocate the text after it out of the user-managed trust zone the
    # prompt declares. Mirrors the memory_update prompt escaping in #4028/#4060.
    # quote=False: these land in element-text position (never attribute values),
    # so only <, >, & can break out - leave ' and " in facts untouched.
    content = html.escape(content, quote=False)
    category = html.escape(category, quote=False)
    if category == "correction" and isinstance(source_error, str) and source_error.strip():
        source_error = html.escape(source_error.strip(), quote=False)
        return f"- [{category} | {confidence:.2f}] {content} (avoid: {source_error})"
    return f"- [{category} | {confidence:.2f}] {content}"


def _escape_summary(value: Any) -> str:
    """Escape a user-editable context summary for the ``<memory>`` block.

    Context summaries (``workContext``/``personalContext``/``topOfMind`` and the
    history sections) are user-editable via ``/api/memory`` import and render into
    the same ``<memory>`` block as facts, so an unescaped ``</memory>`` value can
    close the block and relocate the text after it out of the user-managed trust
    zone the lead-agent prompt declares. Sibling of ``_format_fact_line``'s
    escaping (#4097). ``str(...)`` preserves the prior f-string coercion for the
    rare non-string summary an import can plant; ``quote=False`` because summaries
    land in element-text position (never attribute values), so only ``<``, ``>``,
    ``&`` can break out - leave ``'`` and ``"`` untouched.
    """
    return html.escape(str(value), quote=False)


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
            user_sections.append(f"Work: {_escape_summary(work_ctx['summary'])}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {_escape_summary(personal_ctx['summary'])}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {_escape_summary(top_of_mind['summary'])}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    # Format history
    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {_escape_summary(recent['summary'])}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {_escape_summary(earlier['summary'])}")

        background = history_data.get("longTermBackground", {})
        if background.get("summary"):
            history_sections.append(f"Background: {_escape_summary(background['summary'])}")

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
            content = re.sub(r"<(?P<tag>uploaded_files|current_uploads)>[\s\S]*?</(?P=tag)>\n*", "", str(content)).strip()
            if not content:
                continue

        # Truncate very long messages
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        # Escape < > & before embedding into the <conversation> block of
        # the memory_update prompt. This raw user turn is the most attacker-influenced
        # input in the prompt, so an unescaped value like
        # "</conversation><current_memory>..." would close the block and forge a
        # <current_memory> authority section for the extraction LLM. Same block-
        # breakout defense #4044 applied to the current_memory slot of this exact
        # template, and the sibling _escape_summary/_format_fact_line escaping of
        # the <memory> block (#4097). Escape after truncation so a trailing "..."
        # cannot split an entity; quote=False because content lands in element-
        # text position (never an attribute value).
        content = html.escape(str(content), quote=False)

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
