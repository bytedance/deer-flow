"""Tests for the GitHub dispatcher's identity helpers."""

from __future__ import annotations

import uuid

import pytest

from app.gateway.github.identity import (
    GITHUB_THREAD_NAMESPACE,
    extract_target,
    resolve_thread_id,
)

# ---------------------------------------------------------------------------
# resolve_thread_id
# ---------------------------------------------------------------------------


def test_thread_id_is_deterministic() -> None:
    a = resolve_thread_id("zhfeng/llm-gateway", 11, "coder")
    b = resolve_thread_id("zhfeng/llm-gateway", 11, "coder")
    assert a == b


def test_thread_id_differs_per_pr() -> None:
    assert resolve_thread_id("zhfeng/llm-gateway", 11, "coder") != resolve_thread_id("zhfeng/llm-gateway", 12, "coder")


def test_thread_id_differs_per_repo() -> None:
    assert resolve_thread_id("a/b", 1, "coder") != resolve_thread_id("c/d", 1, "coder")


def test_thread_id_differs_per_agent() -> None:
    """Different agents on the same PR must land on different threads.

    This is the headline guarantee of the per-agent thread design: coder and
    reviewer bound to ``owner/repo#7`` never share a LangGraph thread, so
    dual-mentions can never silently drop one run via
    ``multitask_strategy="reject"`` and the agents' message histories stay
    independent.
    """
    assert resolve_thread_id("zhfeng/llm-gateway", 7, "coder") != resolve_thread_id("zhfeng/llm-gateway", 7, "reviewer")


def test_thread_id_is_uuid5_under_namespace() -> None:
    repo, num, agent = "zhfeng/llm-gateway", 11, "coder"
    expected = str(uuid.uuid5(GITHUB_THREAD_NAMESPACE, f"{repo}#{num}:{agent}"))
    assert resolve_thread_id(repo, num, agent) == expected
    # And valid UUID.
    uuid.UUID(resolve_thread_id(repo, num, agent))


def test_thread_id_rejects_bad_repo() -> None:
    with pytest.raises(ValueError):
        resolve_thread_id("no-slash", 1, "coder")


def test_thread_id_rejects_non_int_number() -> None:
    with pytest.raises(ValueError):
        resolve_thread_id("a/b", "11", "coder")  # type: ignore[arg-type]


def test_thread_id_rejects_empty_agent_name() -> None:
    with pytest.raises(ValueError):
        resolve_thread_id("a/b", 1, "")
    with pytest.raises(ValueError):
        resolve_thread_id("a/b", 1, "   ")
    with pytest.raises(ValueError):
        resolve_thread_id("a/b", 1, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_target
# ---------------------------------------------------------------------------


def test_extract_target_pull_request() -> None:
    payload = {
        "repository": {"full_name": "a/b"},
        "pull_request": {"number": 7},
    }
    assert extract_target("pull_request", payload) == ("a/b", 7)


def test_extract_target_pull_request_falls_back_to_top_level_number() -> None:
    # Some PR payloads put the number at the top level, not on pull_request.
    payload = {"repository": {"full_name": "a/b"}, "pull_request": {}, "number": 4}
    assert extract_target("pull_request", payload) == ("a/b", 4)


def test_extract_target_issue_comment() -> None:
    payload = {
        "repository": {"full_name": "a/b"},
        "issue": {"number": 12},
        "comment": {"body": "hi"},
    }
    assert extract_target("issue_comment", payload) == ("a/b", 12)


def test_extract_target_pull_request_review() -> None:
    payload = {
        "repository": {"full_name": "a/b"},
        "pull_request": {"number": 5},
        "review": {},
    }
    assert extract_target("pull_request_review", payload) == ("a/b", 5)


def test_extract_target_issues() -> None:
    payload = {"repository": {"full_name": "a/b"}, "issue": {"number": 99}}
    assert extract_target("issues", payload) == ("a/b", 99)


def test_extract_target_ping_returns_none() -> None:
    assert extract_target("ping", {"repository": {"full_name": "a/b"}}) is None


def test_extract_target_missing_repo_returns_none() -> None:
    assert extract_target("pull_request", {"pull_request": {"number": 1}}) is None


def test_extract_target_missing_number_returns_none() -> None:
    assert extract_target("pull_request", {"repository": {"full_name": "a/b"}, "pull_request": {}}) is None
