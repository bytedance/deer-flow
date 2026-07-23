"""Memory updater for reading, writing, and updating memory data."""

import asyncio
import atexit
import concurrent.futures
import copy
import html
import json
import logging
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import DeerMemConfig
from .prompt import (
    format_conversation_for_update,
    load_prompt,
    load_prompt_messages,
)
from .storage import (
    MemoryManifestRevisionConflict,
    MemoryStorage,
    create_empty_memory,
    utc_now_iso_z,
)

logger = logging.getLogger(__name__)


# Thread pool for offloading sync memory updates when called from an async
# context.  Unlike the previous asyncio.run() approach, this runs *sync*
# model.invoke() calls — no event loop is created, so the langchain async
# httpx client pool (globally cached via @lru_cache) is never touched and
# cross-loop connection reuse is impossible.
_SYNC_MEMORY_UPDATER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="memory-updater-sync",
)
atexit.register(lambda: _SYNC_MEMORY_UPDATER_EXECUTOR.shutdown(wait=False))


# Data-access + fact-CRUD functions (_save_memory_to_file / get_memory_data /
# reload_memory_data / import_memory_data / clear_memory_data / create_memory_fact /
# delete_memory_fact / update_memory_fact) moved into MemoryUpdater as instance
# methods (use self._storage). See the class below.
def _validate_confidence(confidence: float) -> float:
    """Validate persisted fact confidence so stored JSON stays standards-compliant."""
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence")
    return confidence


def _coerce_source_confidence(fact: dict[str, Any]) -> float:
    """Return a stored fact's confidence as a finite float in [0, 1], defaulting to 0.5.

    dict.get(key, default) returns the stored value (including None) when the key
    exists, so a fact written with "confidence": null would propagate None into
    arithmetic and crash max(). This helper guards against null, bool, non-numeric,
    and non-finite values from corrupted or manually edited memory files.
    """
    raw = fact.get("confidence")
    if raw is None or isinstance(raw, bool):
        return 0.5
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(val, 1.0)) if math.isfinite(val) else 0.5


def _trim_facts_to_max(facts: list[dict[str, Any]], max_facts: int) -> list[dict[str, Any]]:
    """Keep the highest-confidence facts within ``max_facts`` (confidence coerced).

    Confidence is read via :func:`_coerce_source_confidence` so legacy / imported
    facts with ``null`` or non-numeric confidence never crash the sort -- the
    pre-#4023 ``key=lambda f: f.get("confidence", 0)`` form compared ``None`` /
    ``str`` against ``float`` and raised ``TypeError`` once ``len(facts) >
    max_facts``. Mirrors upstream's ``_trim_facts_to_max`` (introduced in #4023)
    so the vendored copy no longer lags the coercion fix the
    monolithic->vendored rename silently dropped.
    """
    if len(facts) <= max_facts:
        return facts
    return sorted(facts, key=_coerce_source_confidence, reverse=True)[:max_facts]


def _extract_text(content: Any) -> str:
    """Extract plain text from LLM response content (str or list of content blocks).

    Modern LLMs may return structured content as a list of blocks instead of a
    plain string, e.g. [{"type": "text", "text": "..."}]. Using str() on such
    content produces Python repr instead of the actual text, breaking JSON
    parsing downstream.

    String chunks are concatenated without separators to avoid corrupting
    chunked JSON/text payloads. Dict-based text blocks are treated as full text
    blocks and joined with newlines for readability.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        pending_str_parts: list[str] = []

        def flush_pending_str_parts() -> None:
            if pending_str_parts:
                pieces.append("".join(pending_str_parts))
                pending_str_parts.clear()

        for block in content:
            if isinstance(block, str):
                pending_str_parts.append(block)
            elif isinstance(block, dict):
                flush_pending_str_parts()
                text_val = block.get("text")
                if isinstance(text_val, str):
                    pieces.append(text_val)

        flush_pending_str_parts()
        return "\n".join(pieces)
    return str(content)


_REQUIRED_MEMORY_UPDATE_TOP_LEVEL_KEYS = frozenset({"user", "history", "newFacts"})


def _normalize_memory_update_fact(fact: Any) -> dict[str, Any] | None:
    """Normalize a single fact entry from a model-produced memory update."""
    if not isinstance(fact, dict):
        return None

    raw_content = fact.get("content")
    if not isinstance(raw_content, str):
        return None
    content = raw_content.strip()
    if not content:
        return None

    raw_category = fact.get("category")
    category = raw_category.strip() if isinstance(raw_category, str) and raw_category.strip() else "context"

    raw_confidence = fact.get("confidence", 0.5)
    if isinstance(raw_confidence, bool):
        return None
    if isinstance(raw_confidence, str):
        raw_confidence = raw_confidence.strip()
        if not raw_confidence:
            return None
        try:
            raw_confidence = float(raw_confidence)
        except ValueError:
            return None
    elif isinstance(raw_confidence, (int, float)):
        raw_confidence = float(raw_confidence)
    else:
        return None

    if not math.isfinite(raw_confidence):
        return None

    normalized_fact = {
        "content": content,
        "category": category,
        "confidence": raw_confidence,
    }
    source_error = fact.get("sourceError")
    if isinstance(source_error, str):
        normalized_source_error = source_error.strip()
        if normalized_source_error:
            normalized_fact["sourceError"] = normalized_source_error

    # Fact lifetime (expected_valid_days): optional LLM-assigned review window.
    # Validated via the shared _read_expected_valid_days rule (reject bool, require
    # finite, coerce to int, keep only positive); cap applied in _apply_updates.
    evd = _read_expected_valid_days(fact)
    if evd is not None:
        normalized_fact["expected_valid_days"] = evd

    return normalized_fact


def _normalize_memory_update_data(update_data: dict[str, Any]) -> dict[str, Any]:
    """Coerce parsed memory update data into the shape consumed by _apply_updates."""
    user = update_data.get("user")
    history = update_data.get("history")
    new_facts = update_data.get("newFacts")
    facts_to_remove = update_data.get("factsToRemove")
    normalized_facts_to_remove = [fact_id for fact_id in facts_to_remove if isinstance(fact_id, str)] if isinstance(facts_to_remove, list) else []
    normalized_new_facts = []
    dropped_new_fact = not isinstance(new_facts, list)
    if isinstance(new_facts, list):
        for fact in new_facts:
            normalized_fact = _normalize_memory_update_fact(fact)
            if normalized_fact is not None:
                normalized_new_facts.append(normalized_fact)
            else:
                dropped_new_fact = True

    if normalized_facts_to_remove and dropped_new_fact:
        raise json.JSONDecodeError(
            "Unsafe partial memory update: factsToRemove with malformed newFacts",
            json.dumps(update_data, ensure_ascii=False),
            0,
        )

    # ── Normalize staleness review removals ──
    stale_removals_raw = update_data.get("staleFactsToRemove")
    normalized_stale_removals: list[dict[str, str]] = []
    if isinstance(stale_removals_raw, list):
        for entry in stale_removals_raw:
            if not isinstance(entry, dict):
                continue
            fact_id = entry.get("id")
            if not isinstance(fact_id, str) or not fact_id:
                continue
            reason = entry.get("reason", "")
            normalized_stale_removals.append(
                {
                    "id": fact_id,
                    "reason": reason if isinstance(reason, str) else "",
                }
            )

    # ── Normalize staleness review lifetime extensions ──
    stale_extensions_raw = update_data.get("staleFactsToExtend")
    normalized_stale_extensions: list[dict[str, Any]] = []
    if isinstance(stale_extensions_raw, list):
        for entry in stale_extensions_raw:
            if not isinstance(entry, dict):
                continue
            fact_id = entry.get("id")
            if not isinstance(fact_id, str) or not fact_id:
                continue
            # extend_by_days: accept int/float (reject bool), coerce to int, keep > 0.
            # A fractional value in (0, 1) coerces to 0 and is dropped here so the
            # apply path never silently writes a zero-delta extension.
            raw_extend = entry.get("extend_by_days")
            if isinstance(raw_extend, (int, float)) and not isinstance(raw_extend, bool):
                extend_by = int(raw_extend)
                if extend_by > 0:
                    reason = entry.get("reason", "")
                    normalized_stale_extensions.append(
                        {
                            "id": fact_id,
                            "extend_by_days": extend_by,
                            "reason": reason if isinstance(reason, str) else "",
                        }
                    )

    # ── Normalize consolidation decisions ──
    consolidation_raw = update_data.get("factsToConsolidate")
    normalized_consolidation: list[dict[str, Any]] = []
    if isinstance(consolidation_raw, list):
        for entry in consolidation_raw:
            if not isinstance(entry, dict):
                continue
            source_ids = entry.get("sourceIds")
            if not isinstance(source_ids, list) or not source_ids:
                continue
            # dict.fromkeys preserves order while deduplicating so ["f1","f1"]
            # collapses to ["f1"] and is correctly rejected as a single-source merge.
            clean_ids = list(dict.fromkeys(sid for sid in source_ids if isinstance(sid, str) and sid))
            if len(clean_ids) < 2:
                continue
            consolidated = entry.get("consolidated")
            if not isinstance(consolidated, dict):
                continue
            content = consolidated.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            # Normalize confidence: reject booleans (bool subclasses int, so the
            # isinstance check alone would silently accept True/False), coerce to float,
            # and reject non-finite values - matching _normalize_memory_update_fact.
            _raw_conf = consolidated.get("confidence", 0.9)
            if isinstance(_raw_conf, bool) or not isinstance(_raw_conf, (int, float)):
                _norm_conf = 0.9
            else:
                _f = float(_raw_conf)
                _norm_conf = _f if math.isfinite(_f) else 0.9
            _raw_cat = consolidated.get("category")
            _norm_cat = _raw_cat.strip() if isinstance(_raw_cat, str) and _raw_cat.strip() else "context"
            normalized_consolidation.append(
                {
                    "sourceIds": clean_ids,
                    "consolidated": {
                        "content": content.strip(),
                        "category": _norm_cat,
                        "confidence": _norm_conf,
                    },
                }
            )

    return {
        "user": user if isinstance(user, dict) else {},
        "history": history if isinstance(history, dict) else {},
        "newFacts": normalized_new_facts,
        "factsToRemove": normalized_facts_to_remove,
        "staleFactsToRemove": normalized_stale_removals,
        "staleFactsToExtend": normalized_stale_extensions,
        "factsToConsolidate": normalized_consolidation,
    }


def _parse_memory_update_response(response_content: Any) -> dict[str, Any]:
    """Parse the first valid memory-update JSON object from an LLM response.

    Some providers may wrap JSON in thinking traces, prose, or markdown fences
    even when prompted to return JSON only. This parser accepts safely
    extractable JSON objects but does not repair truncated or malformed JSON.
    """
    response_text = _extract_text(response_content).strip()
    decoder = json.JSONDecoder()

    for match in re.finditer(r"\{", response_text):
        try:
            parsed, _end = decoder.raw_decode(response_text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and _REQUIRED_MEMORY_UPDATE_TOP_LEVEL_KEYS.issubset(parsed):
            return _normalize_memory_update_data(parsed)

    raise json.JSONDecodeError("No valid memory update JSON object found", response_text, 0)


# Matches sentences that describe a file-upload *event* rather than general
# file-related work.  Deliberately narrow to avoid removing legitimate facts
# such as "User works with CSV files" or "prefers PDF export".
_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<(?:uploaded_files|current_uploads)>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    """Remove sentences about file uploads from all memory summaries and facts.

    Uploaded files are session-scoped; persisting upload events in long-term
    memory causes the agent to search for non-existent files in future sessions.
    """
    # Scrub summaries in user/history sections
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    # Also remove any facts that describe upload events
    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


def _fact_content_key(content: Any) -> str | None:
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    return stripped.casefold()


# ── Staleness review helpers ──────────────────────────────────────────────


def _parse_fact_datetime(raw: str) -> datetime | None:
    """Parse an ISO-8601 datetime string from a fact's createdAt field.

    Returns ``None`` on any parse failure so callers can safely skip malformed facts.
    """
    if not raw:
        return None
    try:
        result = datetime.fromisoformat(raw)
        # Naive datetimes (no tzinfo) would cause TypeError when compared
        # with the timezone-aware cutoff.  Assume UTC for safety.
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result
    except (ValueError, TypeError):
        return None


def _read_expected_valid_days(fact: dict[str, Any]) -> int | None:
    """Return a fact's ``expected_valid_days`` as a positive int, or ``None``.

    Accepts int/float (rejects ``bool``, which subclasses ``int``) and coerces
    to int *before* the positivity check, mirroring the original
    ``_normalize_memory_update_fact`` rule.  Coercing first matters for values
    in (0, 1): ``0.5`` passes a raw ``> 0`` check but truncates to ``0``, which
    would otherwise be returned as a (non-positive) lifetime instead of
    ``None``.  Non-finite floats (``NaN``, ``+/-inf``) are rejected, and huge
    ints are returned as-is rather than routed through ``float()`` (which
    raises ``OverflowError`` for ``10**400``): Python's JSON decoder parses an
    integer literal with no decimal point as an arbitrary-precision ``int``,
    so a hand-edited ``memory.json`` can carry one.  An int that is too large
    to participate in ``datetime`` arithmetic is bounded by the caller via
    :func:`_safe_add_days` - the helper's job is type/positivity validation,
    not datetime-range validation, because the safe bound depends on the
    ``datetime`` it is added to, not on the value alone.  Returning ``None``
    lets callers fall back to the global age or omit the field rather than
    silently writing a zero/negative/non-finite lifetime.
    """
    raw = fact.get("expected_valid_days")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        evd = raw  # arbitrary-precision int; never routed through float()
    elif isinstance(raw, float) and math.isfinite(raw):
        evd = int(raw)  # coerce before the positivity guard
    else:
        return None
    return evd if evd > 0 else None


def _safe_add_days(dt: datetime, days: int) -> datetime | None:
    """Return ``dt + timedelta(days=days)``, or ``None`` if it overflows.

    A huge persisted ``expected_valid_days`` (e.g. ``10**12``) can exceed
    ``timedelta.max.days`` or push the result past ``datetime.max`` / below
    ``datetime.min``.  Both raise ``OverflowError``.  The staleness and
    consolidation paths add an evd to a ``datetime`` to compute a review
    deadline; returning ``None`` lets the caller fall back to the configured
    global lifetime instead of aborting the whole update cycle.
    """
    try:
        return dt + timedelta(days=days)
    except (OverflowError, ValueError):
        return None


def _effective_fact_staleness_age(fact: dict[str, Any], config: Any) -> int:
    """Return the effective staleness review age in days for *fact*.

    Returns the stored ``expected_valid_days`` value directly when present and
    valid.  The ``staleness_max_lifetime_multiplier`` cap is applied once at
    *write time* (when a fact is first created) so the review window is bounded
    from the start.  Re-applying it here would prevent lifetime-extension
    operations from ever moving the review window beyond that initial cap,
    defeating the purpose of ``staleFactsToExtend``.  Falls back to the global
    ``staleness_age_days`` for facts that pre-date this feature or where the
    LLM did not provide an estimate.
    """
    evd = _read_expected_valid_days(fact)
    return evd if evd is not None else config.staleness_age_days


def _select_stale_candidates(
    current_memory: dict[str, Any],
    config: Any,
) -> list[dict[str, Any]]:
    """Return facts that have exceeded their individual review window.

    Each fact's effective review age is determined by
    ``_effective_fact_staleness_age``: facts with an LLM-assigned
    ``expected_valid_days`` use that value directly; facts without it fall back
    to the global ``staleness_age_days``.  Protected categories (default:
    ``correction``) are excluded because they represent explicit user feedback
    that should not be auto-pruned by age.
    """
    now = datetime.now(UTC)
    protected = frozenset(config.staleness_protected_categories)
    candidates: list[dict[str, Any]] = []
    for fact in current_memory.get("facts", []):
        if not isinstance(fact, dict):
            continue
        category = fact.get("category", "")
        if isinstance(category, str) and category in protected:
            continue
        created_at = _parse_fact_datetime(fact.get("createdAt", ""))
        if created_at is None:
            continue
        effective_age = _effective_fact_staleness_age(fact, config)
        # now - timedelta(days=effective_age) can overflow datetime.min when
        # effective_age is a huge persisted value; a window that large means the
        # fact cannot yet be stale, so skip it rather than aborting the cycle.
        cutoff = _safe_add_days(now, -effective_age)
        if cutoff is not None and created_at < cutoff:
            candidates.append(fact)
    return candidates


def _build_staleness_section(
    stale_candidates: list[dict[str, Any]],
    config: Any,
    *,
    prompts_dir: str | None = None,
    agent_name: str | None = None,
) -> str:
    """Format the staleness review prompt section from candidate facts.

    Each fact line includes a ``valid:Nd`` annotation - the effective review
    window for that fact - so the LLM can calibrate its conservatism: a fact
    reviewed after 30 days was considered volatile at creation; one reviewed
    after 365 days was considered stable.
    """
    if not stale_candidates:
        return ""
    lines: list[str] = []
    for fact in stale_candidates:
        fid = fact.get("id", "?")
        cat = html.escape(str(fact.get("category", "context")).strip() or "context", quote=False)
        conf = _coerce_source_confidence(fact)
        created_raw = fact.get("createdAt", "")
        created_short = created_raw[:10] if isinstance(created_raw, str) and len(created_raw) >= 10 else created_raw
        # quote=False: content is in element-text position (inside <stale_facts>
        # tags, never an attribute value), so only <, >, & can break structure -
        # leave ' and " untouched. Mirrors the convention in prompt.py #4028.
        content = html.escape(str(fact.get("content", "")), quote=False)
        effective_age = _effective_fact_staleness_age(fact, config)
        lines.append(f'- [{fid} | {cat} | {conf:.2f} | {created_short} | valid:{effective_age}d] "{content}"')
    return load_prompt("staleness_review", prompts_dir=prompts_dir, agent_name=agent_name).format(stale_facts="\n".join(lines))


# ── Consolidation helpers ───────────────────────────────────────────────


def _select_consolidation_candidates(
    current_memory: dict[str, Any],
    config: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Return fact categories that exceed the fragmentation threshold.

    Groups facts by category; only categories with at least
    ``consolidation_min_facts`` entries are returned.  Categories in
    ``staleness_protected_categories`` are exempt, mirroring the staleness
    contract so explicit user feedback is never surfaced for merging.
    """
    facts = current_memory.get("facts", [])
    if not facts:
        return {}
    by_category: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        cat = fact.get("category", "context")
        if isinstance(cat, str) and cat.strip():
            by_category.setdefault(cat.strip(), []).append(fact)
    threshold = config.consolidation_min_facts
    protected = set(config.staleness_protected_categories)
    return {cat: group for cat, group in by_category.items() if len(group) >= threshold and cat not in protected}


def _build_consolidation_section(
    candidates: dict[str, list[dict[str, Any]]],
    max_groups: int = 3,
    max_sources: int = 8,
    *,
    prompts_dir: str | None = None,
    agent_name: str | None = None,
) -> str:
    """Format consolidation candidate groups into the prompt section.

    Surfaces at most ``max_groups`` categories (largest fragmented groups first)
    and at most ``max_sources`` facts per group, matching the caps enforced at
    apply time so the LLM is never shown groups it cannot act on.
    """
    if not candidates:
        return ""
    # Prioritise the most fragmented categories; alphabetical tiebreak for stability.
    sorted_candidates = sorted(candidates.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    parts: list[str] = []
    for cat, group in sorted_candidates[:max_groups]:
        lines: list[str] = []
        for fact in group[:max_sources]:
            fid = fact.get("id", "?")
            conf = _coerce_source_confidence(fact)
            content = html.escape(str(fact.get("content", "")))
            lines.append(f'- [{fid} | {conf:.2f}] "{content}"')
        shown = min(len(group), max_sources)
        parts.append(f'<consolidation_candidates category="{html.escape(cat)}" count="{shown}">\n' + "\n".join(lines) + "\n</consolidation_candidates>")
    return load_prompt("consolidation", prompts_dir=prompts_dir, agent_name=agent_name).format(consolidation_groups="\n\n".join(parts), max_groups=max_groups)


def _escape_memory_for_prompt(memory: Any) -> Any:
    """Return a copy of ``memory`` with every string leaf HTML-escaped.

    The memory_update prompt embeds the full memory state as a ``json.dumps``
    blob inside a ``<current_memory>...</current_memory>`` block. ``json.dumps``
    escapes ``"`` and ``\\`` but leaves ``<``, ``>`` and ``&`` intact, so a
    user-influenced field - e.g. a fact ``content`` of
    ``</current_memory><evil>...`` - would otherwise reach the model verbatim
    and break out of the block (prompt injection, #4044).

    Escaping each string *value* before serialization (rather than the
    serialized blob) cannot corrupt the JSON structure, because ``json.dumps``
    re-quotes the already-safe values. Escaping every leaf - not just known
    fields - guarantees no current or future user-influenced field can carry a
    raw ``<``/``>``/``&``; controlled fields such as ids and timestamps contain
    none of those characters, so escaping them is a harmless no-op. This mirrors
    the ``html.escape`` treatment already applied to the staleness and
    consolidation sections (#4028).
    """
    if isinstance(memory, str):
        return html.escape(memory)
    if isinstance(memory, dict):
        return {key: _escape_memory_for_prompt(value) for key, value in memory.items()}
    if isinstance(memory, list):
        return [_escape_memory_for_prompt(item) for item in memory]
    return memory


class MemoryUpdater:
    """Updates memory using LLM based on conversation context."""

    def __init__(self, config: DeerMemConfig, storage: MemoryStorage, llm: Any = None, *, prompts_dir: str | None = None, callbacks: Any = None):
        """Initialize the memory updater with injected config + storage + llm (DI).

        Args:
            config: DeerMem private configuration.
            storage: Memory storage instance (owned by DeerMem, injected here).
            llm: The chat model for memory extraction (owned by DeerMem, injected
                here). None when no LLM is configured; an update raises in that case.
            prompts_dir: Optional custom prompt-template directory forwarded to
                ``load_prompt`` / ``load_prompt_messages``. None = bundled defaults.
            callbacks: Optional ``MemoryCallbacks`` (owned by DeerMem, injected
                here). ``on_memory_llm_call`` is invoked before the LLM call to
                merge trace metadata into ``invoke_config``; None = no tracing.
        """
        self._config = config
        self._storage = storage
        self._llm = llm
        self._prompts_dir = prompts_dir
        self._callbacks = callbacks

    # ── Data access + fact CRUD (formerly module-level functions; use self._storage) ──

    def _save_memory_to_file(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        """Persist memory data via the injected storage."""
        kwargs: dict[str, Any] = {"user_id": user_id}
        if expected_revision is not None:
            kwargs["expected_revision"] = expected_revision
        return self._storage.save(memory_data, agent_name, **kwargs)

    def get_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Get the current memory data via the injected storage."""
        return self._storage.load(agent_name, user_id=user_id)

    def reload_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Reload memory data via the injected storage."""
        return self._storage.reload(agent_name, user_id=user_id)

    def import_memory_data(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Persist imported memory data via the injected storage."""
        if not isinstance(memory_data, dict):
            raise ValueError("memory_data")
        memory_data = copy.deepcopy(memory_data)
        empty = create_empty_memory()
        for section in ("user", "history"):
            incoming_section = memory_data.get(section, {})
            if not isinstance(incoming_section, dict):
                raise ValueError(f"memory_data.{section}")
            complete_section = copy.deepcopy(empty[section])
            for key, value in incoming_section.items():
                if key in complete_section and isinstance(complete_section[key], dict) and isinstance(value, dict):
                    complete_section[key].update(copy.deepcopy(value))
                else:
                    complete_section[key] = copy.deepcopy(value)
            memory_data[section] = complete_section
        if agent_name is not None and getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            current = self.get_memory_data(agent_name, user_id=user_id)
            incoming_facts = copy.deepcopy(memory_data.get("facts", []))
            if not isinstance(incoming_facts, list) or any(not isinstance(fact, dict) for fact in incoming_facts):
                raise ValueError("memory_data.facts")
            for fact in incoming_facts:
                fact["id"] = str(fact.get("id") or f"fact_{uuid.uuid4().hex}")
                fact["confidence"] = _coerce_source_confidence(fact)
            current_by_id = {str(fact.get("id")): fact for fact in current.get("facts", []) if isinstance(fact, dict)}
            incoming_ids = {str(fact.get("id")) for fact in incoming_facts}
            self._storage.apply_changes(
                {
                    "upserts": incoming_facts,
                    "upsertRevisions": {str(fact.get("id")): (int(current_by_id[str(fact.get("id"))].get("revision") or 1) if str(fact.get("id")) in current_by_id else None) for fact in incoming_facts},
                    "deletes": [fact_id for fact_id in current_by_id if fact_id not in incoming_ids],
                    "deleteRevisions": {fact_id: int(fact.get("revision") or 1) for fact_id, fact in current_by_id.items() if fact_id not in incoming_ids},
                    "summaries": {"user": copy.deepcopy(memory_data.get("user", {})), "history": copy.deepcopy(memory_data.get("history", {}))},
                },
                agent_name=agent_name,
                user_id=user_id,
                expected_manifest_revision=int(current.get("revision") or 0),
            )
            return self._storage.load(agent_name, user_id=user_id)
        if agent_name is None:
            memory_data["facts"] = []
        if not self._storage.save(memory_data, agent_name, user_id=user_id):
            raise OSError("Failed to save imported memory data")
        return self._storage.load(agent_name, user_id=user_id)

    def clear_memory_data(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Clear one selected agent's facts without resetting shared summaries."""
        if agent_name is not None and getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            for attempt in range(3):
                current = self.get_memory_data(agent_name, user_id=user_id) if attempt == 0 else self.reload_memory_data(agent_name, user_id=user_id)
                facts = [fact for fact in current.get("facts", []) if isinstance(fact, dict)]
                try:
                    self._storage.apply_changes(
                        {
                            "deletes": [str(fact.get("id")) for fact in facts],
                            "deleteRevisions": {str(fact.get("id")): int(fact.get("revision") or 1) for fact in facts},
                        },
                        agent_name=agent_name,
                        user_id=user_id,
                        expected_manifest_revision=int(current.get("revision") or 0),
                    )
                    return self.reload_memory_data(agent_name, user_id=user_id)
                except MemoryManifestRevisionConflict:
                    if attempt == 2:
                        raise
                    logger.info("Retrying scoped memory clear from a fresh snapshot after a revision conflict")
            raise AssertionError("bounded scoped-clear retry did not return or raise")
        current = self.get_memory_data(agent_name, user_id=user_id)
        cleared_memory = copy.deepcopy(current)
        cleared_memory["facts"] = []
        if not self._save_memory_to_file(cleared_memory, agent_name, user_id=user_id, expected_revision=int(current.get("revision") or 0)):
            raise OSError("Failed to save cleared memory data")
        return cleared_memory

    def clear_all_memory_data(self, *, user_id: str | None = None) -> dict[str, Any]:
        """Clear global summaries and every agent fact bucket for one user."""
        if getattr(type(self._storage), "clear_all", None) is not MemoryStorage.clear_all:
            return self._storage.clear_all(user_id=user_id)
        current = self.get_memory_data(user_id=user_id)
        cleared_memory = create_empty_memory()
        if not self._save_memory_to_file(
            cleared_memory,
            user_id=user_id,
            expected_revision=int(current.get("revision") or 0),
        ):
            raise OSError("Failed to save cleared memory data")
        return cleared_memory

    def create_memory_fact(self, content: str, category: str = "context", confidence: float = 0.5, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[dict[str, Any], str | None]:
        """Create a new fact, persist it, and return ``(updated_memory, fact_id)``.

        The fact_id is returned directly so callers (e.g. the memory_add tool)
        don't have to re-derive it from the memory data by content matching --
        which would couple them to the backend's content normalization and could
        misreport a storage cap on backends that normalize differently.

        The new fact is then trimmed by :func:`_trim_facts_to_max` (highest-
        confidence wins, confidence coerced). If the cap evicts the just-added
        (lower-confidence) fact, ``fact_id`` is ``None`` so callers report
        "not stored - cap reached" instead of a dangling id with a false
        "added" status. This restores both the max_facts cap and the post-trim
        existence check (upstream's ``create_memory_fact_with_created_fact``),
        which the vendored copy had dropped together to avoid the dangling id.
        """
        if agent_name is None:
            raise ValueError("agent_name")
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("content")
        normalized_category = category.strip() or "context"
        validated_confidence = _validate_confidence(confidence)
        now = utc_now_iso_z()
        fact_id = f"fact_{uuid.uuid4().hex[:8]}"
        candidate = {
            "id": fact_id,
            "content": normalized_content,
            "category": normalized_category,
            "confidence": validated_confidence,
            "createdAt": now,
            "source": "manual",
        }
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            for attempt in range(3):
                memory_data = self.get_memory_data(agent_name, user_id=user_id) if attempt == 0 else self.reload_memory_data(agent_name, user_id=user_id)
                updated_memory = dict(memory_data)
                updated_memory["facts"] = _trim_facts_to_max([*memory_data.get("facts", []), copy.deepcopy(candidate)], self._config.max_facts)
                kept_ids = {str(fact.get("id")) for fact in updated_memory["facts"]}
                deletions = [str(fact.get("id")) for fact in memory_data.get("facts", []) if str(fact.get("id")) not in kept_ids]
                try:
                    self._storage.apply_changes(
                        {
                            "upserts": [fact for fact in updated_memory["facts"] if fact.get("id") == fact_id],
                            "upsertRevisions": {fact_id: None},
                            "deletes": deletions,
                            "deleteRevisions": {str(fact.get("id")): int(fact.get("revision") or 1) for fact in memory_data.get("facts", []) if str(fact.get("id")) in deletions},
                        },
                        agent_name=agent_name,
                        user_id=user_id,
                        expected_manifest_revision=int(memory_data.get("revision") or 0),
                    )
                    fresh_memory = self.reload_memory_data(agent_name, user_id=user_id)
                    stored = any(fact.get("id") == fact_id for fact in fresh_memory.get("facts", []))
                    return fresh_memory, (fact_id if stored else None)
                except MemoryManifestRevisionConflict:
                    if attempt == 2:
                        raise
                    logger.info("Retrying capped fact creation from a fresh snapshot after a revision conflict")
            raise AssertionError("bounded create retry did not return or raise")
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        updated_memory = dict(memory_data)
        updated_memory["facts"] = _trim_facts_to_max([*memory_data.get("facts", []), candidate], self._config.max_facts)
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id, expected_revision=int(memory_data.get("revision") or 0)):
            raise OSError("Failed to save memory data after creating fact")
        # If the cap evicted the just-added (lower-confidence) fact, signal via
        # None so callers don't report a dangling id as "added".
        stored = any(f.get("id") == fact_id for f in updated_memory["facts"])
        return updated_memory, (fact_id if stored else None)

    def delete_memory_fact(self, fact_id: str, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Delete a fact by its id and persist the updated memory data."""
        if agent_name is None:
            raise ValueError("agent_name")
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes and hasattr(self._storage, "get_fact"):
            deleted = self._storage.get_fact(fact_id, agent_name=agent_name, user_id=user_id)
            if deleted is None:
                raise KeyError(fact_id)
            global_memory = self.get_memory_data(user_id=user_id)
            self._storage.apply_changes(
                {"deletes": [fact_id], "deleteRevisions": {fact_id: int(deleted.get("revision") or 1)}},
                agent_name=agent_name,
                user_id=user_id,
                expected_manifest_revision=int(global_memory.get("revision") or 0),
                allow_manifest_rebase=True,
            )
            return self.get_memory_data(agent_name, user_id=user_id)
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        facts = memory_data.get("facts", [])
        updated_facts = [fact for fact in facts if fact.get("id") != fact_id]
        if len(updated_facts) == len(facts):
            raise KeyError(fact_id)
        deleted = next(fact for fact in facts if fact.get("id") == fact_id)
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            self._storage.apply_changes(
                {"deletes": [fact_id], "deleteRevisions": {fact_id: int(deleted.get("revision") or 1)}},
                agent_name=agent_name,
                user_id=user_id,
                expected_manifest_revision=int(memory_data.get("revision") or 0),
                allow_manifest_rebase=True,
            )
            return self.get_memory_data(agent_name, user_id=user_id)
        updated_memory = dict(memory_data)
        updated_memory["facts"] = updated_facts
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id, expected_revision=int(memory_data.get("revision") or 0)):
            raise OSError(f"Failed to save memory data after deleting fact '{fact_id}'")
        return updated_memory

    def update_memory_fact(self, fact_id: str, content: str | None = None, category: str | None = None, confidence: float | None = None, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Update an existing fact and persist the updated memory data."""
        if agent_name is None:
            raise ValueError("agent_name")
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes and hasattr(self._storage, "get_fact"):
            updated_fact = self._storage.get_fact(fact_id, agent_name=agent_name, user_id=user_id)
            if updated_fact is None:
                raise KeyError(fact_id)
            if content is not None:
                normalized_content = content.strip()
                if not normalized_content:
                    raise ValueError("content")
                updated_fact["content"] = normalized_content
            if category is not None:
                updated_fact["category"] = category.strip() or "context"
            if confidence is not None:
                updated_fact["confidence"] = _validate_confidence(confidence)
            global_memory = self.get_memory_data(user_id=user_id)
            self._storage.apply_changes(
                {"upserts": [updated_fact], "upsertRevisions": {fact_id: int(updated_fact.get("revision") or 1)}},
                agent_name=agent_name,
                user_id=user_id,
                expected_manifest_revision=int(global_memory.get("revision") or 0),
                allow_manifest_rebase=True,
            )
            return self.get_memory_data(agent_name, user_id=user_id)
        memory_data = self.get_memory_data(agent_name, user_id=user_id)
        updated_memory = dict(memory_data)
        updated_facts: list[dict[str, Any]] = []
        found = False
        for fact in memory_data.get("facts", []):
            if fact.get("id") == fact_id:
                found = True
                updated_fact = dict(fact)
                if content is not None:
                    normalized_content = content.strip()
                    if not normalized_content:
                        raise ValueError("content")
                    updated_fact["content"] = normalized_content
                if category is not None:
                    updated_fact["category"] = category.strip() or "context"
                if confidence is not None:
                    updated_fact["confidence"] = _validate_confidence(confidence)
                updated_facts.append(updated_fact)
            else:
                updated_facts.append(fact)
        if not found:
            raise KeyError(fact_id)
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            changed = next(fact for fact in updated_facts if fact.get("id") == fact_id)
            self._storage.apply_changes(
                {"upserts": [changed], "upsertRevisions": {fact_id: int(changed.get("revision") or 1)}},
                agent_name=agent_name,
                user_id=user_id,
                expected_manifest_revision=int(memory_data.get("revision") or 0),
                allow_manifest_rebase=True,
            )
            return self.get_memory_data(agent_name, user_id=user_id)
        updated_memory["facts"] = updated_facts
        if not self._save_memory_to_file(updated_memory, agent_name, user_id=user_id, expected_revision=int(memory_data.get("revision") or 0)):
            raise OSError(f"Failed to save memory data after updating fact '{fact_id}'")
        return updated_memory

    def _build_correction_hint(
        self,
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> str:
        """Build optional prompt hints for correction and reinforcement signals."""
        correction_hint = ""
        if correction_detected:
            correction_hint = (
                "IMPORTANT: Explicit correction signals were detected in this conversation. "
                "Pay special attention to what the agent got wrong, what the user corrected, "
                "and record the correct approach as a fact with category "
                '"correction" and confidence >= 0.95 when appropriate.'
            )
        if reinforcement_detected:
            reinforcement_hint = (
                "IMPORTANT: Positive reinforcement signals were detected in this conversation. "
                "The user explicitly confirmed the agent's approach was correct or helpful. "
                "Record the confirmed approach, style, or preference as a fact with category "
                '"preference" or "behavior" and confidence >= 0.9 when appropriate.'
            )
            correction_hint = (correction_hint + "\n" + reinforcement_hint).strip() if correction_hint else reinforcement_hint

        return correction_hint

    def _prepare_update_prompt(
        self,
        messages: list[Any],
        agent_name: str | None,
        correction_detected: bool,
        reinforcement_detected: bool,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], list[Any]] | None:
        """Load memory and build the update prompt for a conversation."""
        config = self._config
        if not messages:
            return None

        current_memory = self.get_memory_data(agent_name, user_id=user_id)
        conversation_text = format_conversation_for_update(messages)
        if not conversation_text.strip():
            return None

        correction_hint = self._build_correction_hint(
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

        # ── Build staleness review section ──
        staleness_section = ""
        if config.staleness_review_enabled:
            stale_candidates = _select_stale_candidates(current_memory, config)
            if len(stale_candidates) >= config.staleness_min_candidates:
                staleness_section = _build_staleness_section(stale_candidates, config, prompts_dir=self._prompts_dir, agent_name=agent_name)

        # ── Build consolidation section ──
        consolidation_section = ""
        if config.consolidation_enabled:
            consolidation_candidates = _select_consolidation_candidates(current_memory, config)
            if consolidation_candidates:
                consolidation_section = _build_consolidation_section(
                    consolidation_candidates,
                    max_groups=config.consolidation_max_groups_per_cycle,
                    max_sources=config.consolidation_max_sources,
                    prompts_dir=self._prompts_dir,
                    agent_name=agent_name,
                )

        variables = {
            "current_memory": json.dumps(_escape_memory_for_prompt(current_memory), indent=2, ensure_ascii=False),
            "conversation": conversation_text,
            "correction_hint": correction_hint,
            "staleness_review_section": staleness_section,
            "consolidation_section": consolidation_section,
        }
        prompt = load_prompt_messages("memory_update", variables, agent_name=agent_name, prompts_dir=self._prompts_dir)
        return current_memory, prompt

    def _finalize_update(
        self,
        current_memory: dict[str, Any],
        response_content: Any,
        thread_id: str | None,
        agent_name: str | None,
        user_id: str | None = None,
    ) -> bool:
        """Parse the model response, apply updates, and persist memory."""
        update_data = _parse_memory_update_response(response_content)
        if getattr(type(self._storage), "apply_changes", None) is not MemoryStorage.apply_changes:
            for attempt in range(3):
                # Deep-copy before in-place mutation so a failed commit cannot
                # corrupt the cached snapshot. On a manifest conflict the
                # complete extraction result is reapplied to a fresh document;
                # its trim/consolidation/delete decisions are snapshot-wide and
                # must never be replayed as disjoint point writes.
                updated_memory = self._apply_updates(copy.deepcopy(current_memory), update_data, thread_id)
                updated_memory = _strip_upload_mentions_from_memory(updated_memory)
                current_by_id = {str(fact.get("id")): fact for fact in current_memory.get("facts", [])}
                updated_by_id = {str(fact.get("id")): fact for fact in updated_memory.get("facts", [])}
                change_set = {
                    "upserts": [copy.deepcopy(fact) for fact_id, fact in updated_by_id.items() if current_by_id.get(fact_id) != fact],
                    "upsertRevisions": {fact_id: (int(current_by_id[fact_id].get("revision") or 1) if fact_id in current_by_id else None) for fact_id, fact in updated_by_id.items() if current_by_id.get(fact_id) != fact},
                    "deletes": [fact_id for fact_id in current_by_id if fact_id not in updated_by_id],
                    "deleteRevisions": {fact_id: int(current_by_id[fact_id].get("revision") or 1) for fact_id in current_by_id if fact_id not in updated_by_id},
                }
                summaries_changed = updated_memory.get("user", {}) != current_memory.get("user", {}) or updated_memory.get("history", {}) != current_memory.get("history", {})
                if summaries_changed:
                    change_set["summaries"] = {
                        "user": copy.deepcopy(updated_memory.get("user", {})),
                        "history": copy.deepcopy(updated_memory.get("history", {})),
                    }
                try:
                    self._storage.apply_changes(
                        change_set,
                        agent_name=agent_name,
                        user_id=user_id,
                        expected_manifest_revision=int(current_memory.get("revision") or 0),
                    )
                    return True
                except MemoryManifestRevisionConflict:
                    if attempt == 2:
                        raise
                    current_memory = self.reload_memory_data(agent_name, user_id=user_id)
                    logger.info("Retrying extracted memory update from a fresh snapshot after a revision conflict")
            raise AssertionError("bounded extracted-update retry did not return or raise")
        # Deep-copy before in-place mutation so a subsequent save() failure
        # cannot corrupt the still-cached original object reference.
        updated_memory = self._apply_updates(copy.deepcopy(current_memory), update_data, thread_id)
        updated_memory = _strip_upload_mentions_from_memory(updated_memory)
        return self._storage.save(
            updated_memory,
            agent_name,
            user_id=user_id,
            expected_revision=int(current_memory.get("revision") or 0),
        )

    async def aupdate_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Update memory asynchronously by delegating to the sync path.

        Uses ``asyncio.to_thread`` to run the *sync* ``model.invoke()`` path
        in a worker thread so no second event loop is created and the
        langchain async httpx client pool (shared with the lead agent) is
        never touched.  This eliminates the cross-loop connection-reuse bug
        described in issue #2615.
        """
        return await asyncio.to_thread(
            self._do_update_memory_sync,
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _do_update_memory_sync(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Pure-sync memory update; bind ``trace_id`` into the request-trace
        ContextVar for the worker thread, then delegate to the impl.

        The update runs on a Timer / executor thread with no request ContextVar
        inheritance, so log records emitted here would otherwise lose the
        request trace id (it only reached the pre-LLM-call tracing hook before). The
        host-injected ``trace_context_manager`` hook (``None`` when DeerMem runs
        standalone, outside the deer-flow factory) binds ``trace_id`` for the
        duration of the call and restores the prior binding on exit. A ``None``
        trace_id leaves the ContextVar untouched (no fabricated id).
        """
        cm = self._config.trace_context_manager
        if cm is not None and trace_id is not None:
            with cm(trace_id):
                return self._do_update_memory_sync_impl(
                    messages=messages,
                    thread_id=thread_id,
                    agent_name=agent_name,
                    correction_detected=correction_detected,
                    reinforcement_detected=reinforcement_detected,
                    user_id=user_id,
                    trace_id=trace_id,
                )
        return self._do_update_memory_sync_impl(
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _do_update_memory_sync_impl(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Pure-sync memory update using ``model.invoke()``.

        Uses the *sync* LLM call path so no event loop is created.  This
        guarantees that the langchain provider's globally cached async
        httpx ``AsyncClient`` / connection pool (the one shared with the
        lead agent) is never touched — no cross-loop connection reuse is
        possible.
        """
        try:
            prepared = self._prepare_update_prompt(
                messages=messages,
                agent_name=agent_name,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
                user_id=user_id,
            )
            if prepared is None:
                return False

            current_memory, prompt = prepared
            model_name = self._config.model.model
            model = self._llm
            if model is None:
                raise RuntimeError("DeerMem memory update requested but no LLM is configured (set memory.backend_config.model in config).")
            invoke_config: dict[str, Any] = {"run_name": "memory_agent"}
            # Pre-LLM-call observability hook (e.g. langfuse): merge trace
            # metadata into invoke_config before the call so a tracer emits a
            # span at the LLM boundary. None = no tracing (langfuse not
            # hard-required). Subsumes the former backend_config.tracing_callback.
            if self._callbacks is not None:
                self._callbacks.on_memory_llm_call(
                    invoke_config,
                    thread_id=thread_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    model_name=model_name,
                )
            logger.info("Invoking memory-update LLM (thread=%s trace_id=%s)", thread_id, trace_id)
            response = model.invoke(prompt, config=invoke_config)
            return self._finalize_update(
                current_memory=current_memory,
                response_content=response.content,
                thread_id=thread_id,
                agent_name=agent_name,
                user_id=user_id,
            )
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response for memory update: %s", e)
            return False
        except Exception as e:
            logger.exception("Memory update failed: %s", e)
            return False

    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Synchronously update memory using the sync LLM path.

        Uses ``model.invoke()`` (sync HTTP) which operates on a completely
        separate connection pool from the async ``AsyncClient`` shared by
        the lead agent.  This eliminates the cross-loop connection-reuse
        bug described in issue #2615.

        When called from within a running event loop (e.g. from a LangGraph
        node), the blocking sync call is offloaded to a thread pool so the
        caller's loop is not blocked.

        Args:
            messages: List of conversation messages.
            thread_id: Optional thread ID for tracking source.
            agent_name: If provided, updates per-agent memory. If None, updates global memory.
            correction_detected: Whether recent turns include an explicit correction signal.
            reinforcement_detected: Whether recent turns include a positive reinforcement signal.
            user_id: If provided, scopes memory to a specific user.

        Returns:
            True if update was successful, False otherwise.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            try:
                future = _SYNC_MEMORY_UPDATER_EXECUTOR.submit(
                    self._do_update_memory_sync,
                    messages=messages,
                    thread_id=thread_id,
                    agent_name=agent_name,
                    correction_detected=correction_detected,
                    reinforcement_detected=reinforcement_detected,
                    user_id=user_id,
                    trace_id=trace_id,
                )
                return future.result()
            except Exception:
                logger.exception("Failed to offload memory update to executor")
                return False

        return self._do_update_memory_sync(
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
            trace_id=trace_id,
        )

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply LLM-generated updates to memory.

        Args:
            current_memory: Current memory data.
            update_data: Updates from LLM.
            thread_id: Optional thread ID for tracking.

        Returns:
            Updated memory data.
        """
        config = self._config
        now = utc_now_iso_z()

        # Update user sections
        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # Update history sections
        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # Remove facts (contradiction-based)
        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        # ── Staleness review: removals + lifetime extensions ──
        # Both operations share one staleness-candidate guardrail pass and one
        # candidate_ids set. proposed_remove_ids is hoisted out of the removals
        # sub-block so it covers ALL LLM-proposed removals, not just the ones
        # the per-cycle cap actually deleted: a fact the LLM wanted to remove
        # must never be silently extended even when the cap spares it.
        stale_removals = update_data.get("staleFactsToRemove", [])
        stale_extensions = update_data.get("staleFactsToExtend", [])
        has_staleness_ops = (isinstance(stale_removals, list) and stale_removals) or (isinstance(stale_extensions, list) and stale_extensions)
        if has_staleness_ops:
            # Deterministic guardrail: intersect with actual staleness candidates
            # so an LLM slip that emits a protected-category or non-aged fact id
            # is silently rejected.  Runs unconditionally so the apply-layer
            # protection is independent of model behavior AND of the
            # staleness_review_enabled flag.  Guard against legacy / hand-edited
            # facts that predate the id field: an aged, non-protected fact with
            # no "id" is a valid staleness candidate but has no id to intersect
            # against, so skip it here instead of raising KeyError.
            candidate_ids = {f["id"] for f in _select_stale_candidates(current_memory, config) if f.get("id") is not None}

            # ── Removals ──
            proposed_remove_ids: set[str] = set()
            if isinstance(stale_removals, list) and stale_removals:
                proposed_remove_ids = {entry["id"] for entry in stale_removals if isinstance(entry, dict) and "id" in entry}
                stale_ids_to_remove = proposed_remove_ids & candidate_ids

                if not stale_ids_to_remove:
                    stale_removals = []
                else:
                    # Safety cap: limit max staleness removals per cycle.  When
                    # the LLM returns more than the cap, keep only the
                    # lowest-confidence entries up to the limit so the most
                    # questionable facts are removed first.
                    max_stale = config.staleness_max_removals_per_cycle
                    if len(stale_ids_to_remove) > max_stale:
                        stale_facts = [f for f in current_memory.get("facts", []) if f.get("id") in stale_ids_to_remove]
                        stale_facts.sort(key=_coerce_source_confidence)
                        stale_ids_to_remove = {f["id"] for f in stale_facts[:max_stale]}

                    current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in stale_ids_to_remove]

                # Log removals for observability
                for entry in stale_removals:
                    if isinstance(entry, dict) and entry.get("id") in stale_ids_to_remove:
                        logger.info(
                            "Staleness review removed fact %s: %s",
                            entry["id"],
                            entry.get("reason", "no reason provided"),
                        )

            # ── Lifetime extensions ──
            # Recalibrate expected_valid_days for facts the LLM chose to keep.
            # Eligible facts are stale candidates that the LLM did NOT propose
            # for removal - including those that survived only because the
            # per-cycle cap prevented their deletion.  The new window is
            # min(days_since + extend_by_days, staleness_max_extension_days).
            # Extensions use an absolute ceiling rather than the creation-time
            # multiplier cap: they are deliberate review decisions and must be
            # able to advance the window beyond the original creation cap, but
            # an absolute bound prevents timedelta overflow and LLM misfire.
            if isinstance(stale_extensions, list) and stale_extensions:
                # Exclude all LLM-proposed removals, not just the trimmed set,
                # so a cap-surviving proposed-removal fact is never extended.
                extendable_ids = candidate_ids - proposed_remove_ids
                ext_by_id = {e["id"]: e for e in stale_extensions if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"] in extendable_ids}
                if ext_by_id:
                    now_utc = datetime.now(UTC)
                    max_ext = config.staleness_max_extension_days
                    updated_facts: list[dict[str, Any]] = []
                    for fact in current_memory.get("facts", []):
                        fid = fact.get("id")
                        ext = ext_by_id.get(fid) if fid else None
                        if ext is not None:
                            extend_by = ext.get("extend_by_days")
                            if isinstance(extend_by, (int, float)) and not isinstance(extend_by, bool):
                                extend_by_int = int(extend_by)  # coerce before guard
                                if extend_by_int > 0:
                                    created = _parse_fact_datetime(fact.get("createdAt", ""))
                                    if created is None:
                                        # Unreachable: _select_stale_candidates already
                                        # excludes facts with unparseable createdAt.
                                        updated_facts.append(fact)
                                        continue
                                    days_since = int((now_utc - created).total_seconds() // 86400)
                                    new_evd = min(days_since + extend_by_int, max_ext)
                                    fact = {**fact, "expected_valid_days": new_evd}
                                    logger.info(
                                        "Staleness review extended fact %s by %d days (new expected_valid_days: %d): %s",
                                        fid,
                                        extend_by_int,
                                        new_evd,
                                        ext.get("reason", "no reason provided"),
                                    )
                        updated_facts.append(fact)
                    current_memory["facts"] = updated_facts

        # Add new facts
        existing_fact_keys = {fact_key for fact_key in (_fact_content_key(fact.get("content")) for fact in current_memory.get("facts", [])) if fact_key is not None}
        new_facts = update_data.get("newFacts", [])
        # Creation-time lifetime cap shared with the consolidation path below, so
        # both fact-creation sites apply the identical bound in one place.
        creation_cap = int(config.staleness_age_days * config.staleness_max_lifetime_multiplier)
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                raw_content = fact.get("content", "")
                if not isinstance(raw_content, str):
                    continue
                normalized_content = raw_content.strip()
                fact_key = _fact_content_key(normalized_content)
                if fact_key is None:
                    # Empty / whitespace-only content: skip it the same way the
                    # non-string guard above does, instead of appending a blank
                    # fact that violates the non-empty-content invariant.
                    continue
                if fact_key in existing_fact_keys:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": normalized_content,
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                source_error = fact.get("sourceError")
                if isinstance(source_error, str):
                    normalized_source_error = source_error.strip()
                    if normalized_source_error:
                        fact_entry["sourceError"] = normalized_source_error
                evd = _read_expected_valid_days(fact)
                if evd is not None:
                    # Apply the creation-time cap so the LLM cannot assign an
                    # unbounded lifetime that defers staleness review indefinitely.
                    # Extensions (staleFactsToExtend) bypass this cap via their own
                    # staleness_max_extension_days ceiling because they represent a
                    # deliberate review decision, not an unchecked initial assignment.
                    fact_entry["expected_valid_days"] = min(evd, creation_cap)
                current_memory["facts"].append(fact_entry)
                if fact_key is not None:
                    existing_fact_keys.add(fact_key)

        # Enforce max facts limit (coerced confidence -- see _trim_facts_to_max).
        current_memory["facts"] = _trim_facts_to_max(current_memory["facts"], config.max_facts)

        # ── Memory consolidation ──
        # Runs after the max_facts trim so source facts that were just evicted
        # (low confidence, pushed out by high-confidence newFacts) are absent
        # from fact_index and rejected by the existence guardrail - preventing
        # the only real data-loss scenario where sources are deleted but the
        # merged replacement is itself trimmed away.  Because consolidation
        # always removes ≥2 facts and adds 1, running it after trim cannot push
        # the total above max_facts.
        # Gate on the feature flag at apply time so a config change that races
        # with a debounced update does not silently merge facts the operator
        # intended to keep separate.
        if config.consolidation_enabled:
            consolidation_decisions = update_data.get("factsToConsolidate", [])
            if isinstance(consolidation_decisions, list) and consolidation_decisions:
                fact_index = {f.get("id"): f for f in current_memory.get("facts", []) if isinstance(f, dict)}
                max_groups = config.consolidation_max_groups_per_cycle
                max_sources = config.consolidation_max_sources
                # Creation-time lifetime cap shared with the newFacts path: an
                # inherited expected_valid_days is clamped so a merge of long-lived
                # sources cannot defer first review indefinitely.
                creation_cap = int(config.staleness_age_days * config.staleness_max_lifetime_multiplier)
                ids_consumed: set[str] = set()
                new_consolidated: list[dict[str, Any]] = []
                merge_count = 0

                # Mirror the staleness-pass guardrail: build the set of IDs the LLM
                # was legitimately allowed to see as candidates (excludes protected
                # categories and categories below the threshold).  Any LLM slip that
                # proposes a protected or ineligible fact ID is rejected here regardless
                # of model behaviour, matching how staleness intersects with
                # _select_stale_candidates before applying removals.  Skip id-less
                # legacy facts (they can never be targeted by the id-based source set).
                allowed_source_ids = {f["id"] for group in _select_consolidation_candidates(current_memory, config).values() for f in group if f.get("id") is not None}

                # Iterate all decisions and count successes rather than pre-slicing,
                # so guard failures on early decisions cannot silently starve valid
                # later ones from the configured merge budget.
                for decision in consolidation_decisions:
                    if merge_count >= max_groups:
                        break

                    source_ids = decision.get("sourceIds", [])
                    consolidated = decision.get("consolidated", {})

                    # Guardrail: all source IDs must exist in the post-trim index,
                    # must not already be consumed by an earlier merge this cycle,
                    # and must be in allowed_source_ids - the set built from
                    # _select_consolidation_candidates, which excludes categories in
                    # staleness_protected_categories (default: "correction").  This
                    # mirrors the staleness apply-time check and ensures explicit user
                    # feedback is never silently merged away regardless of model behaviour.
                    if any(sid in ids_consumed or sid not in fact_index or sid not in allowed_source_ids for sid in source_ids):
                        continue
                    # Guardrail: 2..max_sources per group
                    if not (2 <= len(source_ids) <= max_sources):
                        continue

                    content = consolidated.get("content", "")
                    if not isinstance(content, str) or not content.strip():
                        continue

                    source_confidences = [_coerce_source_confidence(fact_index[sid]) for sid in source_ids]
                    # _coerce_source_confidence already clamps each value to [0, 1],
                    # so max(source_confidences) ≤ 1.0 by contract.
                    max_source_conf = max(source_confidences)

                    # Use the LLM's returned confidence, capped at the source maximum so
                    # consolidation cannot inflate confidence.  Clamp to [0, 1] first so
                    # out-of-range values (e.g. 1.5) never leak even if the cap is later
                    # relaxed.  Falls back to max_source_conf when absent or malformed.
                    raw_llm_conf = consolidated.get("confidence")
                    if isinstance(raw_llm_conf, (int, float)) and not isinstance(raw_llm_conf, bool) and math.isfinite(float(raw_llm_conf)):
                        fact_confidence = min(max(0.0, min(float(raw_llm_conf), 1.0)), max_source_conf)
                    else:
                        fact_confidence = max_source_conf

                    # Skip merges whose result would fall below the storage threshold -
                    # same gate applied to newFacts, so consolidation never admits
                    # facts that the normal ingestion path would reject.
                    if fact_confidence < config.fact_confidence_threshold:
                        continue

                    # Carry the newest source's createdAt so the staleness clock
                    # reflects the age of the underlying information, not when
                    # synthesis happened.  consolidatedAt records the merge time
                    # for audit without resetting staleness eligibility.
                    # Use _parse_fact_datetime for crash-safe, timezone-aware comparison:
                    # a numeric createdAt would make string max() raise TypeError, and
                    # mixed Z/+00:00 formats sort wrong lexicographically.
                    _fallback_dt = _parse_fact_datetime(now) or datetime.now(UTC)
                    _source_dts = [_parse_fact_datetime(fact_index[sid].get("createdAt") or "") or _fallback_dt for sid in source_ids]
                    _newest_dt = max(_source_dts)
                    source_created_at = _newest_dt.isoformat().removesuffix("+00:00") + "Z"
                    new_fact: dict[str, Any] = {
                        "id": f"fact_{uuid.uuid4().hex[:8]}",
                        "content": content.strip(),
                        "category": consolidated.get("category", "context"),
                        "confidence": fact_confidence,
                        "createdAt": source_created_at,
                        "consolidatedAt": now,
                        "source": "consolidation",
                        "consolidatedFrom": list(source_ids),
                    }
                    # Propagate sourceError from any source fact so correction
                    # context (what went wrong and why) is not silently lost.
                    source_errors = list(dict.fromkeys(e for sid in source_ids if isinstance((e := fact_index[sid].get("sourceError")), str) and e.strip()))
                    if source_errors:
                        new_fact["sourceError"] = "\n".join(source_errors)

                    # Inherit expected_valid_days from the sources so the merged
                    # fact keeps the lifetime signal of the underlying information
                    # rather than silently degrading to the global staleness_age_days.
                    # The merged fact is re-reviewed at the EARLIEST source review
                    # deadline (createdAt + effective lifetime): a merge combines
                    # details from every source, and a volatile sub-detail (e.g.
                    # evd=7) must not inherit a stable source's 3650-day window and
                    # escape staleness review for years - staleness KEEP/REMOVE is the
                    # only path that re-validates a merged fact, so biasing toward the
                    # soonest deadline keeps uncertain merges re-checked sooner.
                    # Every source participates, including legacy facts without an
                    # explicit evd: their effective lifetime is the configured global
                    # staleness_age_days (matching _effective_fact_staleness_age's
                    # read-time fallback), so a legacy source's default 90-day window
                    # is not silently swallowed by a long-lived sibling. The deadline
                    # is expressed relative to the merged fact's createdAt (the newest
                    # source's), so a source already past its deadline yields a
                    # minimal positive window (review next cycle) rather than the
                    # global fallback, which would otherwise defer an overdue review.
                    # Capped at the creation-time multiplier (hoisted above the loop)
                    # like any new fact so consolidation cannot defer first review
                    # indefinitely.
                    # Compute each source's absolute review deadline
                    # (createdAt + effective lifetime). A huge persisted evd can
                    # overflow datetime arithmetic; _safe_add_days returns None
                    # then, and the source falls back to the global lifetime's
                    # deadline - the same treatment as a legacy (no-evd) source,
                    # so one malformed field cannot abort the merge.
                    global_age = config.staleness_age_days
                    source_deadlines: list[datetime] = []
                    for sid, dt in zip(source_ids, _source_dts):
                        eff = _effective_fact_staleness_age(fact_index[sid], config)
                        deadline = _safe_add_days(dt, eff)
                        if deadline is None:
                            deadline = _safe_add_days(dt, global_age) or _newest_dt
                        source_deadlines.append(deadline)
                    earliest_deadline = min(source_deadlines)
                    # int(total_seconds() // 86400) avoids the .days toward-zero
                    # truncation inconsistency flagged in #4143; a negative result
                    # (a source already past its deadline) is clamped below.
                    days_until_earliest = int((earliest_deadline - _newest_dt).total_seconds() // 86400)
                    # A non-positive value means a source is already past its
                    # deadline (the merge itself was the overdue review) - surface
                    # a minimal positive window so the merged fact is re-reviewed
                    # next cycle instead of inheriting the global fallback.
                    inherited_evd = max(days_until_earliest, 1)
                    new_fact["expected_valid_days"] = min(inherited_evd, creation_cap)

                    ids_consumed.update(source_ids)
                    new_consolidated.append(new_fact)
                    merge_count += 1
                    logger.info(
                        "Consolidation merged %d facts into: %s",
                        len(source_ids),
                        content.strip()[:80],
                    )

                if ids_consumed:
                    current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in ids_consumed]
                    current_memory["facts"].extend(new_consolidated)

        return current_memory
