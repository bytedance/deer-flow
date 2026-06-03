"""Visible acknowledgements for GitHub comments queued during a busy run.

Issue #4121 buffers a comment that arrives while an autonomous run is active,
but ``GitHubChannel.send`` is log-only, so the commenter sees nothing. This
module posts the two reactions the manager can stand behind:

- ``eyes`` — the comment was queued and will be picked up after the current run
- ``confused`` — the per-thread buffer was full and this comment was dropped

Only ``issue_comment`` and ``pull_request_review_comment`` have reaction
endpoints. Review summaries and issue/PR bodies stay unmarked. The poster
never raises into the buffer path and never logs the installation token,
comment body, response body, or exception text.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

logger = logging.getLogger(__name__)

QUEUED_REACTION = "eyes"
OVERFLOW_REACTION = "confused"
REACTION_BY_KIND = {
    "queued": QUEUED_REACTION,
    "overflow": OVERFLOW_REACTION,
}

_SUBJECT_PATHS = {
    "issue_comment": "issues/comments",
    "pull_request_review_comment": "pulls/comments",
}
_ALLOWED_REPO_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.")
_API_ROOT = "https://api.github.com"
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
_ACCEPT = "application/vnd.github+json"

TokenMinter = Callable[..., Awaitable[str]]


def comment_reaction_fields(event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``comment_id`` and ``reaction_subject`` when this event can be reacted to.

    Other events return an empty dict. A boolean or non-positive id is treated
    as missing so it cannot be interpolated into a request path.
    """
    if event not in _SUBJECT_PATHS:
        return {}
    comment = payload.get("comment")
    if not isinstance(comment, Mapping):
        return {}
    comment_id = _positive_int(comment.get("id"))
    if comment_id is None:
        return {}
    return {"comment_id": comment_id, "reaction_subject": event}


def followup_ack_from_github(github_meta: Mapping[str, Any]) -> dict[str, Any] | None:
    """Opaque ack payload for one buffered comment, or None when it cannot be reacted to."""
    repo = github_meta.get("repo")
    if not _safe_repo(repo):
        return None
    installation_id = _positive_int(github_meta.get("installation_id"))
    comment_id = _positive_int(github_meta.get("comment_id"))
    subject = github_meta.get("reaction_subject")
    if installation_id is None or comment_id is None or subject not in _SUBJECT_PATHS:
        return None
    return {
        "provider": "github",
        "repo": repo,
        "installation_id": installation_id,
        "comment_id": comment_id,
        "subject": subject,
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _safe_repo(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    owner, sep, name = value.partition("/")
    if not sep or not owner or not name or "/" in name:
        return False
    if ".." in owner or ".." in name:
        return False
    return all(char in _ALLOWED_REPO_CHARS for char in owner) and all(char in _ALLOWED_REPO_CHARS for char in name)


async def post_comment_reaction(
    target: Mapping[str, Any],
    content: str,
    *,
    client: httpx.AsyncClient | None = None,
    mint_token: TokenMinter | None = None,
) -> bool:
    """POST one comment reaction. Return True when GitHub accepts it.

    A 401 refreshes the installation token once. Every other failure is logged
    with the status code or exception class and returns False.
    """
    if content not in {QUEUED_REACTION, OVERFLOW_REACTION}:
        return False
    normalized = followup_ack_from_github(
        {
            "repo": target.get("repo"),
            "installation_id": target.get("installation_id"),
            "comment_id": target.get("comment_id"),
            "reaction_subject": target.get("subject"),
        }
    )
    if normalized is None:
        logger.info("[GitHub] skipping comment reaction; target is not a reactable comment")
        return False

    if mint_token is None:
        from app.gateway.github.app_auth import mint_installation_token

        mint_token = mint_installation_token

    path_kind = _SUBJECT_PATHS[normalized["subject"]]
    url = f"{_API_ROOT}/repos/{normalized['repo']}/{path_kind}/{normalized['comment_id']}/reactions"
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        token = await mint_token(normalized["installation_id"], force_refresh=False)
        response = await _post_reaction(http, url, token, content)
        if response.status_code == 401:
            token = await mint_token(normalized["installation_id"], force_refresh=True)
            response = await _post_reaction(http, url, token, content)
        if response.status_code in {200, 201}:
            logger.info(
                "[GitHub] reacted %s on %s %s#%s",
                content,
                normalized["subject"],
                normalized["repo"],
                normalized["comment_id"],
            )
            return True
        logger.warning(
            "[GitHub] comment reaction %s failed for %s %s#%s (status=%s)",
            content,
            normalized["subject"],
            normalized["repo"],
            normalized["comment_id"],
            response.status_code,
        )
        return False
    except Exception as exc:
        logger.warning(
            "[GitHub] comment reaction %s failed for %s %s#%s (%s)",
            content,
            normalized["subject"],
            normalized["repo"],
            normalized["comment_id"],
            type(exc).__name__,
        )
        return False
    finally:
        if owns_client:
            await http.aclose()


async def _post_reaction(client: httpx.AsyncClient, url: str, token: str, content: str) -> httpx.Response:
    return await client.post(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"content": content},
    )
