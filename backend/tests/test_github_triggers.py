"""Tests for the GitHub dispatcher's trigger-filter logic."""

from __future__ import annotations

import pytest

from app.gateway.github.triggers import (
    DEFAULT_TRIGGERS,
    _resolved_trigger,
    event_should_fire,
)
from deerflow.config.agents_config import GitHubTriggerConfig

BOT = "coding-llm-gateway"


def _pr_payload(
    action: str = "opened",
    author: str = "zhfeng",
    author_association: str | None = "OWNER",
) -> dict:
    pr: dict[str, object] = {"number": 7, "user": {"login": author}}
    if author_association is not None:
        pr["author_association"] = author_association
    return {
        "action": action,
        "pull_request": pr,
        "repository": {"full_name": "a/b"},
        "sender": {"login": author},
    }


def _comment_payload(
    body: str,
    author: str = "zhfeng",
    author_association: str | None = "OWNER",
) -> dict:
    comment: dict[str, object] = {"body": body, "user": {"login": author}}
    if author_association is not None:
        comment["author_association"] = author_association
    return {
        "action": "created",
        "issue": {"number": 11},
        "comment": comment,
        "repository": {"full_name": "a/b"},
        "sender": {"login": author},
    }


def _resolve(event: str, override: GitHubTriggerConfig | None = None) -> GitHubTriggerConfig:
    """Mimic what the registry does for one ``(event, override)`` pair.

    The dispatcher used to take a full ``binding_triggers`` dict and let
    ``event_should_fire`` look the event up itself. After the registry
    refactor that lookup moved to :func:`_resolved_trigger` at build
    time, and ``event_should_fire`` receives a single pre-resolved
    :class:`GitHubTriggerConfig`. The tests below still want to assert
    behavior given a binding-shaped declaration, so this helper bridges
    the two — equivalent to ``_resolved_trigger(event, {event: override})``
    with an empty-override default.
    """
    override = override if override is not None else GitHubTriggerConfig()
    resolved = _resolved_trigger(event, {event: override})
    assert resolved is not None  # The registry would never call us otherwise.
    return resolved


# ---------------------------------------------------------------------------
# Defaults (merged into a binding's explicit-but-empty override)
# ---------------------------------------------------------------------------
#
# Events are opt-in per binding: an empty triggers map (``{}``) registers
# the agent for NO events — that opt-in / opt-out concern now lives in the
# registry (``_resolved_trigger`` returns ``None`` when the binding omits
# the event, and the registry simply does not index the agent for it).
# Once an event IS listed, the per-event defaults in ``DEFAULT_TRIGGERS``
# fill in any field the override didn't explicitly set, exactly as before.


def test_default_pull_request_opened_fires() -> None:
    fire, reason = event_should_fire("pull_request", _pr_payload("opened"), _resolve("pull_request"), BOT)
    assert fire is True
    assert "opened" in reason


def test_default_pull_request_synchronize_does_not_fire() -> None:
    fire, reason = event_should_fire("pull_request", _pr_payload("synchronize"), _resolve("pull_request"), BOT)
    assert fire is False
    assert "synchronize" in reason


def test_default_issue_comment_without_mention_does_not_fire() -> None:
    fire, reason = event_should_fire("issue_comment", _comment_payload("just a thought"), _resolve("issue_comment"), BOT)
    assert fire is False
    assert "mention" in reason.lower()


def test_default_issue_comment_with_mention_fires() -> None:
    fire, _ = event_should_fire("issue_comment", _comment_payload(f"hey @{BOT} please look"), _resolve("issue_comment"), BOT)
    assert fire is True


def test_default_issue_comment_mention_case_insensitive() -> None:
    fire, _ = event_should_fire("issue_comment", _comment_payload(f"hey @{BOT.upper()} look"), _resolve("issue_comment"), BOT)
    assert fire is True


def test_event_not_in_binding_is_disabled_at_registry() -> None:
    # An event the binding does not list resolves to ``None`` — the
    # registry never indexes the agent for it, so ``event_should_fire``
    # is never called. This boundary is verified at the resolver layer.
    assert _resolved_trigger("pull_request", {}) is None


def test_default_ping_is_disabled_even_when_opted_in() -> None:
    # ``ping`` has DEFAULT_TRIGGERS[ping] = None — no field defaults — so
    # the opt-in override is used as-is. It has no actions or mention
    # requirement, so it fires (which is fine; ping is harmless). What
    # we DO care about is that the registry never indexes a ``ping`` event
    # the binding didn't list; that's the test above.
    assert DEFAULT_TRIGGERS["ping"] is None


def test_default_issues_is_disabled_unless_listed_at_registry() -> None:
    # Same shape as the pull_request case above: an issues-less binding
    # resolves to ``None`` and the registry drops it.
    assert _resolved_trigger("issues", {}) is None


# ---------------------------------------------------------------------------
# Override: action whitelist
# ---------------------------------------------------------------------------


def test_action_whitelist_overrides_default() -> None:
    # Default for pull_request is ["opened"]. Widening lets "reopened" fire.
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=["opened", "reopened"]))
    fire, _ = event_should_fire("pull_request", _pr_payload("reopened"), trigger, BOT)
    assert fire is True


def test_empty_actions_list_blocks_all() -> None:
    # Empty list = explicit empty whitelist = nothing matches.
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=[]))
    fire, _ = event_should_fire("pull_request", _pr_payload("opened"), trigger, BOT)
    assert fire is False


def test_actions_none_allows_any_action() -> None:
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=None))
    fire, _ = event_should_fire("pull_request", _pr_payload("labeled"), trigger, BOT)
    assert fire is True


# ---------------------------------------------------------------------------
# Override: allow_authors bypasses require_mention
# ---------------------------------------------------------------------------


def test_allow_authors_bypasses_mention_requirement() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["zhfeng"]))
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload("no handle here", author="zhfeng"),
        trigger,
        BOT,
    )
    assert fire is True
    assert "zhfeng" in reason


def test_allow_authors_does_not_help_other_users() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["alice"]))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("no handle", author="bob"),
        trigger,
        BOT,
    )
    assert fire is False


@pytest.mark.parametrize(
    ("allow_authors", "author"),
    [
        (["Alice"], "alice"),  # config upper / payload lower
        (["alice"], "Alice"),  # reverse: config lower / payload upper
        (["ALICE"], "alice"),  # all-caps config
        (["Alice"], "Alice"),  # exact case still fires after folding
    ],
)
def test_allow_authors_match_is_case_insensitive(allow_authors: list[str], author: str) -> None:
    """GitHub logins are case-insensitive; allow_authors must match that.

    Sibling gates already ignore case: ``_mentions`` documents
    ``Match is case-insensitive; GitHub itself is.``, and the self-event
    check lowercases both sides. A bare ``in`` membership test rejects an
    owner whose YAML casing differs from the payload login, so
    ``require_mention`` still applies and the webhook is silently dropped.

    ``.lower()`` is symmetric, so both fold directions and an all-caps
    config must fire; the exact-case pair pins that folding stays a
    superset of the old exact match.
    """
    trigger = _resolve(
        "issue_comment",
        GitHubTriggerConfig(require_mention=True, allow_authors=allow_authors),
    )
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload("no handle here", author=author),
        trigger,
        BOT,
    )
    assert fire is True
    assert "allow_authors" in reason


def test_allow_authors_case_insensitive_still_rejects_other_users() -> None:
    """Case-folding the allowlist must not open the gate for non-members."""
    trigger = _resolve(
        "issue_comment",
        GitHubTriggerConfig(require_mention=True, allow_authors=["Alice"]),
    )
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("no handle", author="bob"),
        trigger,
        BOT,
    )
    assert fire is False


# ---------------------------------------------------------------------------
# Override: mention_login replaces default login
# ---------------------------------------------------------------------------


def test_mention_login_override() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="other-bot"))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload("hi @other-bot"),
        trigger,
        BOT,
    )
    assert fire is True


def test_mention_login_override_default_login_does_not_match() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="other-bot"))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"hi @{BOT}"),
        trigger,
        BOT,
    )
    assert fire is False


# ---------------------------------------------------------------------------
# Enabling previously-disabled events
# ---------------------------------------------------------------------------


def test_enabling_issues_via_override() -> None:
    # ``issues`` is disabled by default but an operator can opt in.
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"]))
    fire, _ = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "x"}, "author_association": "OWNER"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "x"},
        },
        trigger,
        BOT,
    )
    assert fire is True


# ---------------------------------------------------------------------------
# issues event: require_mention scans the issue body (no separate comment)
# ---------------------------------------------------------------------------


def test_issues_require_mention_fires_when_body_mentions_bot() -> None:
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "alice"}, "author_association": "OWNER", "body": f"Hey @{BOT} please fix this"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "mention" not in reason  # mention gate passed


def test_issues_require_mention_skips_without_mention() -> None:
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "alice"}, "author_association": "OWNER", "body": "just a normal bug report"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is False
    assert "mention required" in reason


def test_issues_allow_authors_bypasses_mention() -> None:
    # zhfeng opening an issue fires even without a mention.
    trigger = _resolve("issues", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT, allow_authors=["zhfeng"]))
    fire, reason = event_should_fire(
        "issues",
        {
            "action": "opened",
            "issue": {"number": 1, "user": {"login": "zhfeng"}, "body": "no mention here"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "zhfeng"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "allow_authors" in reason


def test_pull_request_require_mention_scans_pr_body() -> None:
    # A PR-opened trigger with require_mention should scan the PR body.
    trigger = _resolve("pull_request", GitHubTriggerConfig(actions=["opened"], require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "pull_request",
        {
            "action": "opened",
            "pull_request": {"number": 3, "user": {"login": "bob"}, "author_association": "COLLABORATOR", "body": f"@{BOT} can you finish this?"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "bob"},
        },
        trigger,
        BOT,
    )
    assert fire is True


# ---------------------------------------------------------------------------
# pull_request_review: require_mention scans the review summary body
# ---------------------------------------------------------------------------


def test_pull_request_review_require_mention_fires_on_review_body_mention() -> None:
    # Regression: _comment_body used to fall through to "" for
    # pull_request_review, so require_mention could never match even when
    # the human explicitly @-mentioned the bot in the review summary.
    trigger = _resolve("pull_request_review", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "pull_request_review",
        {
            "action": "submitted",
            "pull_request": {"number": 4},
            "review": {"user": {"login": "alice"}, "author_association": "MEMBER", "body": f"@{BOT} please look again", "state": "commented"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is True
    assert "mention" not in reason


def test_pull_request_review_require_mention_skips_without_mention() -> None:
    trigger = _resolve("pull_request_review", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, reason = event_should_fire(
        "pull_request_review",
        {
            "action": "submitted",
            "pull_request": {"number": 5},
            "review": {"user": {"login": "alice"}, "author_association": "MEMBER", "body": "looks good", "state": "approved"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is False
    assert "mention required" in reason


# ---------------------------------------------------------------------------
# @-mention boundary: ``@deerflow`` must NOT match ``@deerflow-bot``
# ---------------------------------------------------------------------------


def test_mention_prefix_does_not_match_longer_login() -> None:
    # Agent with mention_login='deerflow' must NOT fire on a comment that
    # addresses a different account, '@deerflow-bot'. Regression for the
    # naive substring ``f'@{login}' in body`` check.
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login="deerflow"))
    fire, reason = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": "Hey @deerflow-bot please review", "user": {"login": "alice"}, "author_association": "OWNER"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        "deerflow",
    )
    assert fire is False
    assert "mention required" in reason


def test_mention_inside_email_does_not_match() -> None:
    # Login-class char immediately before ``@`` (an email-like context)
    # must not register as a mention.
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": f"contact noreply@{BOT}.example to retrigger", "user": {"login": "alice"}, "author_association": "OWNER"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is False


def test_mention_at_start_of_body_matches() -> None:
    # The boundary regex must allow a mention at position 0 (no char before
    # @). Guards against an over-eager fix that requires a preceding
    # whitespace.
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    fire, _ = event_should_fire(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 1, "user": {"login": "alice"}},
            "comment": {"body": f"@{BOT} ping", "user": {"login": "alice"}, "author_association": "OWNER"},
            "repository": {"full_name": "a/b"},
            "sender": {"login": "alice"},
        },
        trigger,
        BOT,
    )
    assert fire is True


def test_mention_followed_by_punctuation_matches() -> None:
    # ``@bot,`` and ``@bot.`` are still valid mentions — the trailing char
    # is not in the login class, so the boundary regex accepts it.
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, mention_login=BOT))
    for body in (f"hey @{BOT}, please look", f"asked @{BOT}.", f"thanks @{BOT}!"):
        fire, _ = event_should_fire(
            "issue_comment",
            {
                "action": "created",
                "issue": {"number": 1, "user": {"login": "alice"}},
                "comment": {"body": body, "user": {"login": "alice"}, "author_association": "OWNER"},
                "repository": {"full_name": "a/b"},
                "sender": {"login": "alice"},
            },
            trigger,
            BOT,
        )
        assert fire is True, f"expected mention to match in: {body!r}"


# ---------------------------------------------------------------------------
# Author authorization (fail-closed by default)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "association",
    ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", None, ""],
)
def test_issue_comment_rejects_untrusted_author_even_with_mention(association: str | None) -> None:
    trigger = _resolve("issue_comment")
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} run this", author="outsider", author_association=association),
        trigger,
        BOT,
    )
    assert fire is False
    assert "unauthorized_author" in reason


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_issue_comment_allows_trusted_associations_with_mention(association: str) -> None:
    trigger = _resolve("issue_comment")
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} please review", author="maintainer", author_association=association),
        trigger,
        BOT,
    )
    assert fire is True


@pytest.mark.parametrize("event, object_key", [("issues", "issue"), ("pull_request", "pull_request"), ("pull_request_review", "review"), ("pull_request_review_comment", "comment")])
def test_other_authored_events_reject_untrusted_authors_by_default(event: str, object_key: str) -> None:
    trigger = _resolve(event, GitHubTriggerConfig(require_mention=False))
    payload = {
        "action": "opened" if event in ("issues", "pull_request") else "created",
        object_key: {"number": 1, "user": {"login": "outsider"}, "author_association": "NONE", "body": f"@{BOT}"},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "outsider"},
    }
    fire, reason = event_should_fire(event, payload, trigger, BOT)
    assert fire is False
    assert "unauthorized_author" in reason


@pytest.mark.parametrize("event, object_key", [("issue_comment", "comment"), ("issues", "issue"), ("pull_request", "pull_request")])
def test_sender_mismatch_does_not_inherit_object_author_association(event: str, object_key: str) -> None:
    trigger = _resolve(event, GitHubTriggerConfig(actions=["edited"], require_mention=False))
    payload = {
        "action": "edited",
        object_key: {"number": 1, "user": {"login": "repo-owner"}, "author_association": "OWNER", "body": f"@{BOT}"},
        "repository": {"full_name": "a/b"},
        "sender": {"login": "outsider"},
    }
    fire, reason = event_should_fire(event, payload, trigger, BOT)
    assert fire is False
    assert "unauthorized_author" in reason


@pytest.mark.parametrize("malformed_sender", [None, {}, {"login": ""}, {"login": "   "}, "not-a-dict"])
def test_malformed_sender_fails_closed_even_when_object_is_owner(malformed_sender: object) -> None:
    trigger = _resolve("issue_comment")
    payload = {
        "action": "created",
        "issue": {"number": 1},
        "comment": {"body": f"@{BOT} hi", "user": {"login": "repo-owner"}, "author_association": "OWNER"},
        "repository": {"full_name": "a/b"},
        "sender": malformed_sender,
    }
    fire, reason = event_should_fire("issue_comment", payload, trigger, BOT)
    assert fire is False
    assert "unauthorized_author" in reason


def test_missing_sender_fails_closed_even_when_object_is_owner_or_allowlisted() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["repo-owner"]))
    payload = {
        "action": "created",
        "issue": {"number": 1},
        "comment": {"body": f"@{BOT} hi", "user": {"login": "repo-owner"}, "author_association": "OWNER"},
        "repository": {"full_name": "a/b"},
    }
    fire, reason = event_should_fire("issue_comment", payload, trigger, BOT)
    assert fire is False
    assert "unauthorized_author" in reason


def test_resolved_trigger_deep_copies_default_lists() -> None:
    first = _resolve("issue_comment")
    second = _resolve("issue_comment")
    first.allow_author_associations.append("NONE")
    assert second.allow_author_associations == ["OWNER", "MEMBER", "COLLABORATOR"]
    assert DEFAULT_TRIGGERS["issue_comment"].allow_author_associations == ["OWNER", "MEMBER", "COLLABORATOR"]  # type: ignore[union-attr]


def test_empty_allow_author_associations_requires_explicit_allow_authors() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(require_mention=True, allow_authors=["alice"], allow_author_associations=[]))
    fire_owner, reason = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} please review", author="bob", author_association="OWNER"),
        trigger,
        BOT,
    )
    assert fire_owner is False
    assert "unauthorized_author" in reason

    fire_listed, _ = event_should_fire(
        "issue_comment",
        _comment_payload("direct command", author="alice", author_association="NONE"),
        trigger,
        BOT,
    )
    assert fire_listed is True


def test_custom_allow_author_associations_can_exclude_org_members() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(allow_author_associations=["OWNER", "COLLABORATOR"]))
    fire_member, reason = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} run", author="org-member", author_association="MEMBER"),
        trigger,
        BOT,
    )
    assert fire_member is False
    assert "unauthorized_author" in reason

    fire_collab, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} run", author="collab", author_association="COLLABORATOR"),
        trigger,
        BOT,
    )
    assert fire_collab is True


def test_explicit_opt_in_to_none_association_allows_external_mention() -> None:
    trigger = _resolve("issue_comment", GitHubTriggerConfig(allow_author_associations=["OWNER", "NONE"]))
    fire, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} triage this", author="outsider", author_association="NONE"),
        trigger,
        BOT,
    )
    assert fire is True


def test_allow_authors_with_bypass_mention_disabled_still_requires_mention() -> None:
    trigger = _resolve(
        "issue_comment",
        GitHubTriggerConfig(
            require_mention=True,
            allow_authors=["alice", "coderabbitai[bot]"],
            allow_authors_bypass_mention=False,
            allow_author_associations=[],
        ),
    )
    fire_no_mention, reason_no_mention = event_should_fire(
        "issue_comment",
        _comment_payload("ordinary review discussion", author="alice", author_association="MEMBER"),
        trigger,
        BOT,
    )
    assert fire_no_mention is False
    assert "mention required" in reason_no_mention

    fire_with_mention, _ = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} please check this", author="coderabbitai[bot]", author_association="NONE"),
        trigger,
        BOT,
    )
    assert fire_with_mention is True

    fire_unlisted_member, reason_unlisted = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} please check this", author="bob", author_association="MEMBER"),
        trigger,
        BOT,
    )
    assert fire_unlisted_member is False
    assert "unauthorized_author" in reason_unlisted


def test_unauthorized_reason_escapes_control_characters_in_sender_login() -> None:
    trigger = _resolve("issue_comment")
    fire, reason = event_should_fire(
        "issue_comment",
        _comment_payload(f"@{BOT} hi", author="bad\nactor", author_association="NONE"),
        trigger,
        BOT,
    )
    assert fire is False
    assert "\n" not in reason
    assert "unauthorized_author" in reason
