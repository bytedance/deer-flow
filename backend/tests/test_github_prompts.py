"""Tests for the GitHub webhook → prompt translator."""

from __future__ import annotations

from app.gateway.github.prompts import build_prompt


def test_pull_request_prompt_contains_core_fields() -> None:
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 7,
            "title": "Add webhook receiver",
            "user": {"login": "zhfeng"},
            "html_url": "https://github.com/a/b/pull/7",
            "body": "This adds X and fixes Y.",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request", payload)
    assert "pull request" in prompt.lower()
    assert "#7" in prompt
    assert "Add webhook receiver" in prompt
    assert "zhfeng" in prompt
    assert "https://github.com/a/b/pull/7" in prompt
    assert "This adds X and fixes Y." in prompt


def test_pull_request_prompt_handles_missing_body() -> None:
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {}, "body": None},
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request", payload)
    assert "(no description)" in prompt


def test_pull_request_prompt_truncates_huge_body() -> None:
    huge = "X" * 50000
    payload = {
        "action": "opened",
        "pull_request": {"number": 1, "title": "x", "user": {}, "body": huge},
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request", payload)
    assert "truncated" in prompt
    assert len(prompt) < 10000


def test_issue_comment_prompt_includes_body_verbatim() -> None:
    payload = {
        "action": "created",
        "issue": {"number": 11, "pull_request": {"url": "..."}},
        "comment": {
            "body": "Hey @coding-llm-gateway please look at this",
            "user": {"login": "zhfeng"},
            "html_url": "https://github.com/a/b/issues/11#issuecomment-1",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("issue_comment", payload)
    assert "pull request #11" in prompt  # is_pr True
    assert "@coding-llm-gateway please look at this" in prompt
    assert "zhfeng" in prompt


def test_issue_comment_plain_issue_says_issue() -> None:
    payload = {
        "action": "created",
        "issue": {"number": 12},
        "comment": {"body": "x", "user": {"login": "u"}},
        "repository": {"full_name": "a/b"},
    }
    assert "issue #12" in build_prompt("issue_comment", payload)


def test_issue_comment_prompt_includes_issue_title_and_body() -> None:
    """The comment alone isn't enough — the agent needs the issue context too.

    The webhook payload already includes the parent issue/PR's title and body
    on the ``issue`` object; we just have to render them.
    """
    payload = {
        "action": "created",
        "issue": {
            "number": 42,
            "title": "Login button is broken",
            "body": "Clicking login throws a 500. Repro: open /login, click submit.",
            "user": {"login": "reporter"},
        },
        "comment": {
            "body": "@bot what do you think?",
            "user": {"login": "asker"},
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("issue_comment", payload)
    assert "Login button is broken" in prompt
    assert "Clicking login throws a 500" in prompt
    assert "reporter" in prompt  # issue author, distinct from comment author
    assert "@bot what do you think?" in prompt


def test_pull_request_review_comment_includes_pr_title_and_body() -> None:
    payload = {
        "action": "created",
        "pull_request": {
            "number": 9,
            "title": "Refactor auth flow",
            "body": "Splits AuthService into AuthN/AuthZ.",
            "user": {"login": "author"},
        },
        "comment": {
            "user": {"login": "alice"},
            "path": "src/foo.py",
            "line": 42,
            "diff_hunk": "@@ -1 +1 @@\n-a\n+b",
            "body": "consider renaming",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request_review_comment", payload)
    assert "Refactor auth flow" in prompt
    assert "Splits AuthService into AuthN/AuthZ." in prompt
    assert "consider renaming" in prompt


def test_pull_request_review_prompt_includes_pr_title_and_body() -> None:
    payload = {
        "action": "submitted",
        "pull_request": {
            "number": 5,
            "title": "Bump deps",
            "body": "Updates everything to latest.",
            "user": {"login": "author"},
        },
        "review": {
            "state": "changes_requested",
            "user": {"login": "alice"},
            "body": "Looks risky",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request_review", payload)
    assert "Bump deps" in prompt
    assert "Updates everything to latest." in prompt
    assert "changes_requested" in prompt
    assert "Looks risky" in prompt


def test_pull_request_review_comment_includes_file_and_diff() -> None:
    payload = {
        "action": "created",
        "pull_request": {"number": 9},
        "comment": {
            "user": {"login": "alice"},
            "path": "src/foo.py",
            "line": 42,
            "diff_hunk": "@@ -1,3 +1,4 @@\n a\n+b\n c",
            "body": "consider renaming",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request_review_comment", payload)
    assert "src/foo.py:42" in prompt
    assert "+b" in prompt
    assert "consider renaming" in prompt


def test_pull_request_review_prompt_includes_state() -> None:
    payload = {
        "action": "submitted",
        "pull_request": {"number": 5},
        "review": {
            "state": "changes_requested",
            "user": {"login": "alice"},
            "body": "Looks risky",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("pull_request_review", payload)
    assert "changes_requested" in prompt
    assert "Looks risky" in prompt
    assert "alice" in prompt


def test_issues_prompt() -> None:
    payload = {
        "action": "opened",
        "issue": {
            "number": 3,
            "title": "bug",
            "user": {"login": "u"},
            "html_url": "https://github.com/a/b/issues/3",
            "body": "things broken",
        },
        "repository": {"full_name": "a/b"},
    }
    prompt = build_prompt("issues", payload)
    assert "#3" in prompt
    assert "bug" in prompt
    assert "things broken" in prompt


def test_ping_prompt() -> None:
    payload = {"zen": "Practicality beats purity.", "hook": {"id": 42}}
    prompt = build_prompt("ping", payload)
    assert "ping" in prompt.lower()
    assert "42" in prompt


def test_unknown_event_returns_generic_stub() -> None:
    prompt = build_prompt("workflow_run", {"action": "completed", "repository": {"full_name": "a/b"}})
    assert "workflow_run" in prompt
    assert "a/b" in prompt
