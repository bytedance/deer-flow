"""Lightweight primitives for neutralizing untrusted model-context data."""

import re

# Finite set of blocked tag names: system-reserved + common injection patterns.
#
# Maintenance: when adding a new framework block tag that the system emits into
# model input, update the expected count in
# test_input_sanitization_middleware.py::test_denylist_covers_framework_authority_blocks.
_BLOCKED_TAG_NAMES: frozenset[str] = frozenset(
    {
        # Framework-injected structured/authority blocks. The lead-agent system
        # prompt's "System-Context Confidentiality" section declares every such
        # tag trusted internal data, so untrusted input must not forge one.
        "system-reminder",
        "system_reminder",
        "memory",
        "current_date",
        "think",
        "analysis",
        "role",
        "soul",
        "self_update",
        "thinking_style",
        "clarification_system",
        "critical_reminders",
        "response_style",
        "citations",
        "uploaded_files",
        "current_uploads",
        "subagent_system",
        "skill_system",
        "skill_index",
        "available_skills",
        "disabled_skills",
        "memory_tool_system",
        "todo_list_system",
        "durable_context_data",
        "slash_skill_activation",
        "mcp_routing_hints",
        "available-deferred-tools",
        "goal_continuation",
        "file_editing_workflow",
        "guidelines",
        "output_format",
        "working_directory",
        "tool_restrictions",
        # Common prompt-injection tag patterns.
        "system",
        "instruction",
        "important",
        "override",
        "ignore",
        "prompt",
    }
)

# Plain-text boundary markers (OWASP structured-prompt guidance).
_USER_INPUT_BEGIN = "--- BEGIN USER INPUT ---"
_USER_INPUT_END = "--- END USER INPUT ---"

_BLOCKED_TAG_PATTERN = re.compile(
    r"<\s*/?\s*(?:" + "|".join(re.escape(tag) for tag in sorted(_BLOCKED_TAG_NAMES)) + r")\b[^>]*>?",
    re.IGNORECASE,
)
_NEUTRALIZED_BEGIN = "[BEGIN USER INPUT]"
_NEUTRALIZED_END = "[END USER INPUT]"
_BOUNDARY_TOKEN_RE = re.compile(
    re.escape(_USER_INPUT_BEGIN) + r"|" + re.escape(_USER_INPUT_END),
)


def _escape_tag_match(match: re.Match) -> str:
    """Escape blocked tag delimiters so the match renders as literal text."""
    return match.group(0).replace("<", "&lt;").replace(">", "&gt;")


def _neutralize_boundary_tokens(text: str) -> str:
    """Replace real user-input boundary markers with inert look-alikes."""
    return _BOUNDARY_TOKEN_RE.sub(
        lambda match: _NEUTRALIZED_BEGIN if match.group(0) == _USER_INPUT_BEGIN else _NEUTRALIZED_END,
        text,
    )


def neutralize_untrusted_tags(text: str) -> str:
    """Neutralize framework tags and boundary tokens in untrusted data."""
    if not text.strip():
        return text
    text = _BLOCKED_TAG_PATTERN.sub(_escape_tag_match, text)
    return _neutralize_boundary_tokens(text)
