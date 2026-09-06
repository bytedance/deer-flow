"""Identity helpers for GitHub webhook dispatch.

Two helpers live here:

* :func:`resolve_thread_id` makes the langgraph thread id deterministic
  from ``(repo, number, agent_name)``. Same PR + same agent → same
  thread, even across gateway restarts. Different agents on the same PR
  (e.g. coder + reviewer) deliberately get different thread ids — see
  the function docstring for the rationale.

* :func:`extract_target` extracts the ``(repo, number)`` pair from a
  webhook payload, so the dispatcher can route deliveries to the right
  thread.
"""

from __future__ import annotations

import uuid
from typing import Any

# UUID5 namespace dedicated to GitHub-driven threads. The bytes themselves
# are arbitrary; what matters is that every gateway in the fleet uses the
# *same* namespace so two replicas produce the same thread id for the same
# (repo, number, agent_name) triple. Don't change this without a migration
# plan.
GITHUB_THREAD_NAMESPACE = uuid.UUID("a3f4b2c1-7e8d-4f6a-b9c0-1234567890ab")


def resolve_thread_id(repo: str, issue_or_pr_number: int, agent_name: str) -> str:
    """Build a deterministic langgraph thread id from a GitHub target + agent.

    The agent name is part of the seed so two agents bound to the same
    PR/issue (e.g. a coder + a reviewer on ``owner/repo#7``) land on
    distinct LangGraph threads. Sharing the thread would force
    ``multitask_strategy="reject"`` to silently drop one run on every
    dual-mention, and would couple the two agents' message histories
    and checkpoints. Each agent now owns its own thread; cross-agent
    coordination flows through GitHub (PR comments, review threads) —
    the source of truth humans see anyway.

    Args:
        repo: ``"owner/name"``.
        issue_or_pr_number: Issue or PR number (they share the namespace on
            the GitHub side, so we don't need to distinguish here).
        agent_name: The bound custom agent's name. Validated upstream
            against ``^[A-Za-z0-9-]+$`` (see
            ``app/gateway/routers/agents.py::AGENT_NAME_PATTERN``) so it
            is safe to embed verbatim in the UUID5 seed.

    Returns:
        Stringified UUID5 under :data:`GITHUB_THREAD_NAMESPACE`.
    """
    if not isinstance(repo, str) or "/" not in repo:
        raise ValueError(f"Expected repo as 'owner/name', got {repo!r}")
    if not isinstance(issue_or_pr_number, int):
        raise ValueError(f"Expected issue_or_pr_number as int, got {type(issue_or_pr_number).__name__}")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError(f"Expected agent_name as non-empty str, got {agent_name!r}")
    return str(uuid.uuid5(GITHUB_THREAD_NAMESPACE, f"{repo}#{issue_or_pr_number}:{agent_name}"))


def extract_target(event: str, payload: dict[str, Any]) -> tuple[str, int] | None:
    """Best-effort extraction of (repo, number) from a webhook payload.

    Returns ``None`` when the event has no associated issue/PR number
    (e.g. ``ping``, ``push``) or when the payload is malformed.
    """
    repo = (payload.get("repository") or {}).get("full_name")
    if not isinstance(repo, str):
        return None

    number: int | None = None
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or payload.get("number")
    elif event == "pull_request_review":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
    elif event == "pull_request_review_comment":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
    elif event == "issue_comment":
        number = (payload.get("issue") or {}).get("number")
    elif event == "issues":
        number = (payload.get("issue") or {}).get("number")
    else:
        return None

    if not isinstance(number, int):
        return None
    return repo, number
