"""Backend twin of the frontend ``expectNoRawIdentifiers`` helper.

User-visible text the backend writes itself (scheduled-task IM notices) must
show no raw identifiers: UUIDs, task/run ids, ISO timestamps, five-field cron
strings and internal enum or field names. The patterns are those of
``frontend/tests/e2e/utils/raw-identifiers.ts``, plus URLs (IM notices carry no
links) and any snake_case token (internal reason and event codes such as
``consecutive_unmet`` or ``task_finished``).
"""

from __future__ import annotations

import re

RAW_IDENTIFIER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
    re.compile(r"\btask-(run-)?[0-9a-f]{16,}\b"),
    re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
    re.compile(r"(^|\s)[\d*/,-]+(\s[\d*/,-]+){4}(\s|$)"),
    re.compile(r"\b(fresh_thread_per_run|reuse_thread|lead_agent|goal_objective|max_runs|end_at|unmet|stop_scheduled_task|schedule_task)\b"),
    # Backend additions: no links, no internal snake_case codes.
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),
)


def find_raw_identifiers(text: str) -> list[str]:
    """The patterns ``text`` matches, with the matched text, for a readable failure message."""
    found = []
    for pattern in RAW_IDENTIFIER_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append(f'{pattern.pattern} -> "{match.group(0).strip()}"')
    return found


def assert_no_raw_identifiers(text: str) -> None:
    """Assert that user-visible ``text`` carries no raw identifiers, URLs or internal codes."""
    found = find_raw_identifiers(text)
    assert not found, f"raw identifiers in user-visible text: {found}\n---\n{text}"
