"""Trigger filter logic for GitHub webhook dispatch.

Pure functions, no I/O. Given an event name, its payload, and the
agent-config's per-event trigger overrides, decide whether to fire the
agent and why (the reason string makes the gateway log line useful).

**Events are opt-in per binding.** If an event name does not appear as a
key in the binding's ``triggers:`` mapping, the agent is **not registered**
for that event — the dispatcher never even loads the agent for it. The
agent's ``config.yaml`` is the single source of truth for "which events
do I care about?".

:data:`DEFAULT_TRIGGERS` still exists, but it is no longer an
event-enablement list. It is the per-event **field-level defaults** that
get merged into the binding's override when an event IS listed. So:

* ``issue_comment: {}`` → registers the agent for ``issue_comment`` and
  inherits ``require_mention: True`` from the default. (Same shape as
  before — minimal config, sensible defaults.)
* Binding omits ``issue_comment`` entirely → the agent does **not** see
  ``issue_comment`` events at all. (New behavior.)

Trigger override merge is field-wise via Pydantic's ``exclude_unset``:
fields the binding explicitly set win; fields it omitted fall back to
the default. Fields with no default (``DEFAULT_TRIGGERS[event]`` is
``None``) just use the binding's literal value.
"""

from __future__ import annotations

import re
from typing import Any

from deerflow.config.agents_config import GitHubTriggerConfig

# Per-event field-level defaults. These are merged into a binding's
# override when the event IS listed in the binding's ``triggers:``. They
# no longer enable the event by themselves — the binding must list the
# event for the agent to register for it.
#
# ``None`` means "no per-event defaults; use whatever the binding set
# (or the model's own field defaults)".
DEFAULT_TRIGGERS: dict[str, GitHubTriggerConfig | None] = {
    "ping": None,
    "issues": None,
    "pull_request_review": None,
    "pull_request": GitHubTriggerConfig(actions=["opened"]),
    "issue_comment": GitHubTriggerConfig(require_mention=True),
    "pull_request_review_comment": GitHubTriggerConfig(require_mention=True),
}


def _action(payload: dict[str, Any]) -> str | None:
    action = payload.get("action")
    return action if isinstance(action, str) else None


def _comment_body(event: str, payload: dict[str, Any]) -> str:
    """Extract the human-typed text to scan for an ``@mention``.

    For comment events this is the comment body. For ``issues`` and
    ``pull_request`` events there is no separate comment — the mention
    would be in the issue/PR body itself — so we read that. For
    ``pull_request_review`` the body is the review summary. Other events
    have no user-authored text to mention-check and return ``""``.
    """
    if event in ("issue_comment", "pull_request_review_comment"):
        body = (payload.get("comment") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "issues":
        body = (payload.get("issue") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "pull_request":
        body = (payload.get("pull_request") or {}).get("body")
        return body if isinstance(body, str) else ""
    if event == "pull_request_review":
        body = (payload.get("review") or {}).get("body")
        return body if isinstance(body, str) else ""
    return ""


def _author_login(event: str, payload: dict[str, Any]) -> str | None:
    """Login of the human who triggered the event, for ``allow_authors``."""
    if event in ("issue_comment", "pull_request_review_comment"):
        login = (payload.get("comment") or {}).get("user", {}).get("login")
    elif event == "pull_request":
        login = (payload.get("pull_request") or {}).get("user", {}).get("login")
    elif event == "pull_request_review":
        login = (payload.get("review") or {}).get("user", {}).get("login")
    elif event == "issues":
        login = (payload.get("issue") or {}).get("user", {}).get("login")
    else:
        login = (payload.get("sender") or {}).get("login")
    return login if isinstance(login, str) else None


def _resolved_trigger(
    event: str,
    binding_triggers: dict[str, GitHubTriggerConfig],
) -> GitHubTriggerConfig | None:
    """Merge the binding's override with per-event field defaults.

    Returns ``None`` if the binding does not list the event at all — the
    event is opt-in per binding.

    Otherwise, returns a ``GitHubTriggerConfig`` where:
    * fields the binding explicitly set win,
    * fields the binding omitted fall back to ``DEFAULT_TRIGGERS[event]``,
    * and if there is no per-event default the binding's own field
      defaults (from the Pydantic model) apply.

    Detection of "explicitly set" relies on Pydantic's
    ``model_fields_set`` — fields not present in the source YAML aren't
    counted as set.
    """
    override = binding_triggers.get(event)
    if override is None:
        return None

    default = DEFAULT_TRIGGERS.get(event)
    if default is None:
        return override

    # Field-wise merge: take fields the binding explicitly set,
    # backfill the rest from the per-event default.
    explicit = override.model_dump(exclude_unset=True)
    merged = default.model_copy(update=explicit)
    return merged


def _mentions(body: str, login: str) -> bool:
    """Return True if ``body`` @-mentions ``login`` with proper boundaries.

    GitHub logins are ``[A-Za-z0-9-]+``, so the character immediately
    after the login in a mention must NOT be one of those — otherwise
    ``@deerflow`` would falsely match ``@deerflow-bot`` (a different,
    legitimate GitHub user). A plain substring ``in`` check is wrong for
    this reason.

    Also rejects mentions where the ``@`` is preceded by a login-class
    character (e.g. ``foo@deerflow`` inside an email address) to avoid
    incidental matches on URLs / pasted addresses.

    Match is case-insensitive; GitHub itself is.
    """
    pattern = rf"(?:^|[^A-Za-z0-9-])@{re.escape(login)}(?![A-Za-z0-9-])"
    return re.search(pattern, body, flags=re.IGNORECASE) is not None


def event_should_fire(
    event: str,
    payload: dict[str, Any],
    trigger: GitHubTriggerConfig,
    default_mention_login: str,
) -> tuple[bool, str]:
    """Decide whether ``event`` fires the agent for this binding.

    Args:
        event: GitHub event name (``X-GitHub-Event``).
        payload: Parsed webhook payload.
        trigger: Pre-resolved trigger config for this ``(repo, event)``.
            The caller (registry) has already merged the binding override
            with per-event :data:`DEFAULT_TRIGGERS` field defaults, so this
            function does not look the event up in any dict — it just
            applies the gates the trigger declares.
        default_mention_login: Bot login (without ``@``) used by
            ``require_mention`` when the trigger doesn't override
            ``mention_login``. Pass the agent name as a fallback.

    Returns:
        ``(fire, reason)`` where ``fire`` is the decision and ``reason``
        is a short label for logging (e.g. ``"action=opened"``,
        ``"mention"``, ``"disabled"``).
    """
    # Action whitelist (e.g. only "opened" PRs).
    if trigger.actions is not None:
        action = _action(payload)
        if action not in trigger.actions:
            return False, f"action={action!r} not in {trigger.actions}"

    # allow_authors bypasses require_mention entirely. Useful so a repo
    # owner can talk to the bot without typing the handle every time.
    # Match is case-insensitive — GitHub logins are, and the sibling gates
    # in this module already are (``_mentions`` uses re.IGNORECASE; the
    # self-event check lowercases both sides). A bare ``in`` membership
    # test would drop an owner whose YAML casing differs from the payload.
    if trigger.allow_authors:
        author = _author_login(event, payload)
        if author and author.lower() in {a.lower() for a in trigger.allow_authors}:
            return True, f"allow_authors:{author}"

    if trigger.require_mention:
        # ``trigger.mention_login`` is normalized (whitespace-only -> None)
        # by ``GitHubTriggerConfig``'s field validator, so this ``or`` falls
        # through a misconfigured ``mention_login: "   "`` to
        # ``default_mention_login`` instead of gating on a literal
        # whitespace string that no real ``@mention`` could ever match.
        login = trigger.mention_login or default_mention_login
        body = _comment_body(event, payload)
        # Boundary-aware @-mention match: ``@deerflow`` must NOT match
        # ``@deerflow-bot`` (a distinct, legitimate GitHub login). See
        # :func:`_mentions` for the full rationale.
        if not login or not _mentions(body, login):
            return False, f"mention required for @{login}"

    # All gates passed.
    action = _action(payload)
    return True, f"action={action}" if action else "ok"
