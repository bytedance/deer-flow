"""Shared helpers for turning conversations into memory update inputs."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from copy import copy
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

_PATTERN_CACHE: dict[tuple[str, str | None], list[re.Pattern[str]]] = {}


def load_patterns(name: str, *, patterns_dir: str | None = None) -> list[re.Pattern[str]]:
    """Load and compile signal patterns from a YAML file.

    ``name`` is ``"correction"`` or ``"reinforcement"``. ``patterns_dir``
    overrides the bundled ``core/message_patterns/`` directory; ``None`` (the
    default) loads the bundled defaults, which mirror the pre-externalization
    hardcoded patterns so zero-config behavior is unchanged. Compiled patterns
    are cached per ``(name, patterns_dir)``.

    Each YAML list entry is either a string (compiled with no flags) or a
    mapping ``{pattern: <regex>, flags: [...]}`` where ``flags`` may contain
    ``"ignorecase"``. Raises ``ValueError`` for invalid YAML, a non-list
    top-level value, or an invalid regex (all with the file path in the message).
    For explicit *patterns_dir*: missing files raise ``FileNotFoundError``;
    unreadable files (OSError) are re-raised. Malformed entries and unknown flag
    names are skipped with a WARNING. For bundled defaults (*patterns_dir* is
    ``None``): missing/unreadable files log a WARNING and return ``[]``
    (packaging bug, not a configuration error).
    """
    cache_key = (name, patterns_dir)
    cached = _PATTERN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    base = Path(patterns_dir) if patterns_dir else Path(__file__).parent / "message_patterns"
    path = base / f"{name}.yaml"
    if not path.exists():
        if patterns_dir is not None:
            raise FileNotFoundError(f"Signal patterns file not found: {path}")
        logger.warning("Signal patterns file not found (%s); %s detection disabled.", path, name)
        _PATTERN_CACHE[cache_key] = []
        return []

    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e
    except OSError as e:
        if patterns_dir is not None:
            raise OSError(f"Failed to read signal patterns file {path}: {e}") from e
        logger.warning("Failed to read signal patterns %s: %s; %s detection disabled.", path, e, name)
        _PATTERN_CACHE[cache_key] = []
        return []

    if not isinstance(data, list):
        raise ValueError(f"Signal patterns file {path} must contain a list, not {type(data).__name__}")

    compiled: list[re.Pattern[str]] = []
    for i, entry in enumerate(data):
        if isinstance(entry, str):
            pattern_text, flag_names = entry, []
        elif isinstance(entry, Mapping):
            pattern_text = entry.get("pattern")
            flag_names = entry.get("flags", []) or []
        else:
            logger.warning("Skipping non-string/non-mapping entry %d in %s (type %s)", i, path, type(entry).__name__)
            continue
        if not isinstance(pattern_text, str) or not pattern_text:
            logger.warning("Skipping entry %d in %s: missing or empty 'pattern'", i, path)
            continue
        flags = 0
        for flag_name in flag_names:
            if flag_name == "ignorecase":
                flags |= re.IGNORECASE
            else:
                logger.warning("Ignoring unknown flag %r in entry %d of %s", flag_name, i, path)
        try:
            compiled.append(re.compile(pattern_text, flags))
        except re.error as e:
            raise ValueError(f"Invalid regex in {path} entry {i}: {e} (pattern={pattern_text!r})") from e

    _PATTERN_CACHE[cache_key] = compiled
    return compiled


def extract_message_text(message: Any) -> str:
    """Extract plain text from message content for filtering and signal detection."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
        return " ".join(text_parts)
    return str(content)


def _non_empty_str(value: object) -> str | None:
    """Return ``value`` if it is a non-empty (stripped) string, else None."""
    return value if isinstance(value, str) and value.strip() else None


def _is_human_clarification_response(additional_kwargs: Any) -> bool:
    """Return True iff ``additional_kwargs`` carries a well-formed human
    clarification response (a user-authored answer worth remembering).

    Host-agnostic structural mirror of deer-flow's ``read_human_input_response``
    (which the host injects via ``should_keep_hidden_message`` in production):
    a ``human_input_response`` mapping with version 1 + kind
    ``human_input_response``, non-empty source/request_id/value, and (for
    option responses) a non-empty option_id. Malformed/partial payloads return
    False so they are excluded like other hide_from_ui framework messages.
    Kept inline (no host import) so the bare ``filter_messages_for_memory``
    does the right thing standalone and in tests. NOTE: if the
    human_input_response format changes, keep this in sync with
    ``read_human_input_response`` (the production path) -- they must agree.
    """
    if not isinstance(additional_kwargs, Mapping):
        return False
    raw = additional_kwargs.get("human_input_response")
    if not isinstance(raw, Mapping):
        return False
    if raw.get("version") != 1 or raw.get("kind") != "human_input_response":
        return False
    if _non_empty_str(raw.get("source")) is None or _non_empty_str(raw.get("request_id")) is None or _non_empty_str(raw.get("value")) is None:
        return False
    response_kind = raw.get("response_kind")
    if response_kind == "text":
        return True
    if response_kind == "option":
        return _non_empty_str(raw.get("option_id")) is not None
    return False


def filter_messages_for_memory(messages: list[Any], *, should_keep_hidden_message: Any = None) -> list[Any]:
    """Keep only user inputs and final assistant responses for memory updates.

    ``hide_from_ui`` framework messages are skipped, but user-authored
    clarification answers (a well-formed ``human_input_response``) are kept by
    default via a host-agnostic structural check (mirrors deer-flow's
    ``read_human_input_response``). Pass a ``should_keep_hidden_message(
    additional_kwargs) -> bool`` hook to override the keep decision; the host
    injects one delegating to the authoritative ``read_human_input_response``
    in production.
    """
    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            # Middleware-injected hidden messages (e.g. TodoMiddleware.todo_reminder,
            # ViewImageMiddleware, p0 DynamicContextMiddleware.__memory) carry
            # hide_from_ui and must never reach the memory-updating LLM — otherwise
            # framework-internal text pollutes long-term memory (and the p0 __memory
            # payload could trigger a self-amplification loop).
            additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
            if additional_kwargs.get("hide_from_ui"):
                # Framework-injected hidden messages (TodoMiddleware reminders,
                # ViewImage payloads, p0 __memory self-amplification guard) are
                # excluded. User-authored clarification answers (a well-formed
                # human_input_response) ARE real content worth remembering, so
                # they are kept by default via a host-agnostic structural check.
                # A host ``should_keep_hidden_message`` hook, when supplied,
                # overrides this (production DeerMem injects one delegating to
                # the authoritative read_human_input_response).
                if should_keep_hidden_message is not None:
                    keep = should_keep_hidden_message(additional_kwargs)
                else:
                    keep = _is_human_clarification_response(additional_kwargs)
                if not keep:
                    continue
            content_str = extract_message_text(msg)
            if "<uploaded_files>" in content_str:
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    skip_next_ai = True
                    continue
                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)

    return filtered


def detect_correction(messages: list[Any], *, patterns: list[re.Pattern[str]] | None = None) -> bool:
    """Detect explicit user corrections in recent conversation turns.

    ``patterns`` overrides the loaded patterns (useful when the caller has
    already resolved ``DeerMemConfig.patterns_dir``); ``None`` loads the bundled
    defaults via :func:`load_patterns`. The scan window stays ``messages[-6:]``
    (the most recent human turns).
    """
    if patterns is None:
        patterns = load_patterns("correction")
    recent_user_msgs = [msg for msg in messages[-6:] if getattr(msg, "type", None) == "human"]

    for msg in recent_user_msgs:
        content = extract_message_text(msg).strip()
        if content and any(pattern.search(content) for pattern in patterns):
            return True

    return False


def detect_reinforcement(messages: list[Any], *, patterns: list[re.Pattern[str]] | None = None) -> bool:
    """Detect explicit positive reinforcement signals in recent conversation turns.

    ``patterns`` overrides the loaded patterns (useful when the caller has
    already resolved ``DeerMemConfig.patterns_dir``); ``None`` loads the bundled
    defaults via :func:`load_patterns`. The scan window stays ``messages[-6:]``.
    """
    if patterns is None:
        patterns = load_patterns("reinforcement")
    recent_user_msgs = [msg for msg in messages[-6:] if getattr(msg, "type", None) == "human"]

    for msg in recent_user_msgs:
        content = extract_message_text(msg).strip()
        if content and any(pattern.search(content) for pattern in patterns):
            return True

    return False
