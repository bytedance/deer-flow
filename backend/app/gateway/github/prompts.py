"""Translate GitHub webhook payloads into prompts for the agent.

Each supported event has its own template. The output is a single
human-readable string fed in as a ``role: user`` message to the agent.

Design notes:

* The prompt is descriptive ("a PR was opened on …"), not imperative
  ("review this PR"), so the agent's SOUL.md gets to define behavior.
  The dispatcher appends one terse instruction at the end so a stock
  ``lead_agent`` SOUL still does something useful.
* The channel layer is **log-only on the outbound path** — the agent's
  final message goes to ``gateway.log`` and is NOT posted to GitHub.
  If the agent wants to reply on the PR/issue, it must call ``gh`` (or
  the equivalent REST API) **during** the run. We do not promise the
  agent that "your final message will be posted." That used to be true;
  it isn't any more.
* We embed the comment body verbatim because that's the most useful
  signal — the agent needs to see what the human actually typed. We
  do not try to escape it; agents understand markdown.
* We never include the raw payload JSON; that's noise.
"""

from __future__ import annotations

from typing import Any


def _truncate(text: str | None, limit: int = 4000) -> str:
    """Trim long fields so a single bad payload doesn't blow the context window."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n[…truncated…]"


def _pull_request_prompt(payload: dict[str, Any]) -> str:
    pr = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
    number = pr.get("number") or payload.get("number")
    title = pr.get("title") or "(no title)"
    author = (pr.get("user") or {}).get("login") or "(unknown)"
    url = pr.get("html_url") or "(no url)"
    action = payload.get("action") or "opened"
    body = _truncate(pr.get("body"))

    return (
        f"A pull request was {action} on {repo}:\n\n"
        f"  #{number} {title}\n"
        f"  Author: {author}\n"
        f"  URL: {url}\n\n"
        f"Description:\n{body or '(no description)'}\n\n"
        f"Decide what action (if any) to take for this pull request and carry it out. "
        f"Your final assistant message is for the run log only — it will NOT be "
        f"posted to GitHub. If you want to reply on the PR, call `gh pr comment` "
        f"(or `gh pr review`) yourself during the run."
    )


def _render_parent_context(parent: dict[str, Any], kind: str) -> str:
    """Render the issue/PR the event hangs off as a header block.

    ``kind`` is ``"issue"`` or ``"pull request"`` — used in the heading
    only. The webhook payload's ``issue``/``pull_request`` object already
    carries the title, body, and author for the parent, so no extra API
    call is needed for first-level context.
    """
    title = parent.get("title") or "(no title)"
    author = (parent.get("user") or {}).get("login") or "(unknown)"
    url = parent.get("html_url") or "(no url)"
    body = _truncate(parent.get("body"))
    return f"Parent {kind}:\n  Title: {title}\n  Author: {author}\n  URL: {url}\n\n  Description:\n{body or '(no description)'}\n"


def _issue_comment_prompt(payload: dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
    issue = payload.get("issue") or {}
    number = issue.get("number")
    is_pr = "pull_request" in issue
    target = "pull request" if is_pr else "issue"
    parent_block = _render_parent_context(issue, target)
    comment = payload.get("comment") or {}
    author = (comment.get("user") or {}).get("login") or "(unknown)"
    url = comment.get("html_url") or "(no url)"
    body = _truncate(comment.get("body"))
    return (
        f"A new comment was posted on {target} #{number} in {repo}.\n\n"
        f"{parent_block}\n"
        f"New comment:\n"
        f"  Author: {author}\n"
        f"  URL: {url}\n\n"
        f"  Body:\n{body or '(empty comment)'}\n\n"
        f"Decide what action (if any) to take in response to this comment, in the context "
        f"of the parent {target} above. Your final assistant message is for the run log "
        f"only — it will NOT be posted to GitHub. If you want to reply, call "
        f"`gh issue comment {number} --repo {repo} --body-file -` yourself during the run."
    )


def _pr_review_comment_prompt(payload: dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    parent_block = _render_parent_context(pr, "pull request")
    comment = payload.get("comment") or {}
    author = (comment.get("user") or {}).get("login") or "(unknown)"
    path = comment.get("path") or "(unknown file)"
    line = comment.get("line") or comment.get("original_line") or "?"
    diff_hunk = _truncate(comment.get("diff_hunk"), limit=2000)
    body = _truncate(comment.get("body"))
    return (
        f"A new review comment was posted on pull request #{number} in {repo}.\n\n"
        f"{parent_block}\n"
        f"Review comment:\n"
        f"  Author: {author}\n"
        f"  File: {path}:{line}\n\n"
        f"  Diff context:\n```\n{diff_hunk}\n```\n\n"
        f"  Body:\n{body or '(empty comment)'}\n\n"
        f"Decide what action (if any) to take in response to this review comment, in the "
        f"context of the parent pull request above. Your final assistant message is for the "
        f"run log only — it will NOT be posted to GitHub. If you want to reply, call "
        f"`gh pr comment {number} --repo {repo} --body-file -` yourself during the run."
    )


def _pr_review_prompt(payload: dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    parent_block = _render_parent_context(pr, "pull request")
    review = payload.get("review") or {}
    review_id = review.get("id")
    state = review.get("state") or "(unknown state)"
    author = (review.get("user") or {}).get("login") or "(unknown)"
    body = _truncate(review.get("body"))
    # This payload carries only the review's own top-level summary. Any
    # inline comments the reviewer left arrive as SEPARATE
    # `pull_request_review_comment` webhook deliveries, and the dispatcher
    # suppresses those as redundant fan-out for a binding that (like this
    # one) also listens for `pull_request_review` on this repo — see
    # `dispatcher.py::_is_redundant_review_comment`. That suppression is
    # only genuinely redundant if the agent actually recovers the inline
    # content from here, so tell it how (PR #4131 review, Concern 1,
    # zhfeng): without this, the filter and the prompt were working against
    # each other — the filter suppressed the only events that carried the
    # inline content, and nothing ever told the agent to go get it. Omitted
    # when `review.id` (or the PR number) is missing/malformed so the
    # instruction never renders a broken `gh api` path.
    fetch_hint = ""
    if review_id is not None and number is not None:
        fetch_hint = f"This review's inline comments are not included in this message. Before deciding what to do, fetch them with `gh api repos/{repo}/pulls/{number}/reviews/{review_id}/comments`.\n\n"
    return (
        f"A pull request review was submitted on #{number} in {repo}.\n\n"
        f"{parent_block}\n"
        f"Review:\n"
        f"  Reviewer: {author}\n"
        f"  State: {state}\n\n"
        f"  Body:\n{body or '(no review body)'}\n\n"
        f"{fetch_hint}"
        f"Decide what action (if any) to take in response to this review, in the context "
        f"of the parent pull request above. Your final assistant message is for the run "
        f"log only — it will NOT be posted to GitHub. If you want to reply (or push a fix), "
        f"call `gh pr comment {number} --repo {repo} --body-file -` (and the usual "
        f"`git clone` / `gh pr checkout` / `git push` flow for code changes) yourself "
        f"during the run."
    )


def _issues_prompt(payload: dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
    issue = payload.get("issue") or {}
    number = issue.get("number")
    title = issue.get("title") or "(no title)"
    author = (issue.get("user") or {}).get("login") or "(unknown)"
    url = issue.get("html_url") or "(no url)"
    body = _truncate(issue.get("body"))
    action = payload.get("action") or "opened"
    return (
        f"An issue was {action} on {repo}:\n\n"
        f"  #{number} {title}\n"
        f"  Author: {author}\n"
        f"  URL: {url}\n\n"
        f"Description:\n{body or '(no description)'}\n\n"
        f"Decide what action (if any) to take for this issue and carry it out. "
        f"Your final assistant message is for the run log only — it will NOT be "
        f"posted to GitHub. If you want to reply on the issue (or open a PR), call "
        f"`gh issue comment {number} --repo {repo} --body-file -` / `gh pr create` "
        f"yourself during the run."
    )


def _ping_prompt(payload: dict[str, Any]) -> str:
    # Ping events arrive when a webhook is first installed. We don't
    # normally fire on them but include a template for completeness.
    zen = payload.get("zen") or "(no zen)"
    hook_id = (payload.get("hook") or {}).get("id")
    return f"GitHub sent a ping event. zen={zen!r} hook_id={hook_id}\n\nNo action required."


_EVENT_BUILDERS: dict[str, Any] = {
    "ping": _ping_prompt,
    "pull_request": _pull_request_prompt,
    "issue_comment": _issue_comment_prompt,
    "pull_request_review_comment": _pr_review_comment_prompt,
    "pull_request_review": _pr_review_prompt,
    "issues": _issues_prompt,
}


def build_prompt(event: str, payload: dict[str, Any]) -> str:
    """Return the prompt string for a webhook delivery.

    Unknown events get a generic stub so the dispatcher can still kick
    off a run without crashing — useful when a new event type is
    enabled before this module is updated.
    """
    builder = _EVENT_BUILDERS.get(event)
    if builder is None:
        repo = (payload.get("repository") or {}).get("full_name") or "(unknown repo)"
        return f"GitHub event {event!r} fired on {repo}. action={payload.get('action')!r}"
    return builder(payload)
