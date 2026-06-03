"""Offline tests for GitHub comment reactions queued during a busy run."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.gateway.github.reactions import (
    OVERFLOW_REACTION,
    QUEUED_REACTION,
    comment_reaction_fields,
    followup_ack_from_github,
    post_comment_reaction,
)


def test_issue_comment_exposes_a_reaction_target() -> None:
    fields = comment_reaction_fields(
        "issue_comment",
        {"comment": {"id": 4242, "body": "please also cover the edge case"}},
    )
    assert fields == {"comment_id": 4242, "reaction_subject": "issue_comment"}


def test_pull_request_review_comment_exposes_a_reaction_target() -> None:
    fields = comment_reaction_fields(
        "pull_request_review_comment",
        {"comment": {"id": 99, "pull_request_review_id": 7, "body": "nit"}},
    )
    assert fields == {"comment_id": 99, "reaction_subject": "pull_request_review_comment"}


@pytest.mark.parametrize(
    "event,payload",
    [
        ("pull_request_review", {"review": {"id": 5, "body": "LGTM"}}),
        ("issues", {"issue": {"number": 3, "body": "bug"}}),
        ("pull_request", {"pull_request": {"number": 3, "body": "change"}}),
        ("issue_comment", {"comment": {"id": True, "body": "nope"}}),
        ("issue_comment", {"comment": {"id": 0, "body": "nope"}}),
        ("issue_comment", {"comment": {"id": "4242", "body": "nope"}}),
        ("issue_comment", {"comment": "not-a-dict"}),
        ("issue_comment", {}),
    ],
)
def test_events_without_a_comment_reaction_endpoint_are_unmarked(event: str, payload: dict) -> None:
    assert comment_reaction_fields(event, payload) == {}


def test_followup_ack_requires_a_safe_repo_and_installation() -> None:
    base = {
        "repo": "octo/hello",
        "installation_id": 77,
        "comment_id": 4242,
        "reaction_subject": "issue_comment",
    }
    ack = followup_ack_from_github(base)
    assert ack == {
        "provider": "github",
        "repo": "octo/hello",
        "installation_id": 77,
        "comment_id": 4242,
        "subject": "issue_comment",
    }
    for broken in (
        {**base, "repo": "octo/hello/extra"},
        {**base, "repo": "../hello"},
        {**base, "repo": "octo/hel lo"},
        {**base, "installation_id": None},
        {**base, "installation_id": True},
        {**base, "reaction_subject": "pull_request_review"},
    ):
        assert followup_ack_from_github(broken) is None


def _target(**overrides: object) -> dict:
    payload = {
        "provider": "github",
        "repo": "octo/hello",
        "installation_id": 77,
        "comment_id": 4242,
        "subject": "issue_comment",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_post_eyes_uses_the_issue_comment_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": 1, "content": "eyes"})

    async def mint(installation_id: int, *, force_refresh: bool = False) -> str:
        assert installation_id == 77
        assert force_refresh is False
        return "ghs_test_token"

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await post_comment_reaction(_target(), QUEUED_REACTION, client=client, mint_token=mint)

    assert ok is True
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/repos/octo/hello/issues/comments/4242/reactions"
    assert request.headers["authorization"] == "token ghs_test_token"
    assert json.loads(request.content) == {"content": "eyes"}


@pytest.mark.asyncio
async def test_post_confused_uses_the_review_comment_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": 2, "content": "confused"})

    async def mint(installation_id: int, *, force_refresh: bool = False) -> str:
        return "ghs_test_token"

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await post_comment_reaction(
            _target(subject="pull_request_review_comment", comment_id=99),
            OVERFLOW_REACTION,
            client=client,
            mint_token=mint,
        )

    assert ok is True
    assert seen[0].url.path == "/repos/octo/hello/pulls/comments/99/reactions"
    assert json.loads(seen[0].content) == {"content": "confused"}


@pytest.mark.asyncio
async def test_unauthorized_reaction_refreshes_the_installation_token_once() -> None:
    auths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auths.append(request.headers["authorization"])
        if len(auths) == 1:
            return httpx.Response(401, json={"message": "bad credentials"})
        return httpx.Response(201, json={"id": 3})

    async def mint(installation_id: int, *, force_refresh: bool = False) -> str:
        return "ghs_refreshed" if force_refresh else "ghs_stale"

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await post_comment_reaction(_target(), QUEUED_REACTION, client=client, mint_token=mint)

    assert ok is True
    assert auths == ["token ghs_stale", "token ghs_refreshed"]


@pytest.mark.asyncio
async def test_reaction_failure_hides_token_and_response_body(caplog: pytest.LogCaptureFixture) -> None:
    secret = "ghs_supersecret_token"
    body_sentinel = "comment-body-SENTINEL"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": body_sentinel, "token": secret})

    async def mint(installation_id: int, *, force_refresh: bool = False) -> str:
        return secret

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with caplog.at_level(logging.DEBUG, logger="app.gateway.github.reactions"):
            ok = await post_comment_reaction(_target(), QUEUED_REACTION, client=client, mint_token=mint)

    assert ok is False
    assert secret not in caplog.text
    assert body_sentinel not in caplog.text
    assert any("status=403" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_mint_failure_does_not_raise_or_log_the_exception_text(caplog: pytest.LogCaptureFixture) -> None:
    secret = "private-key-SENTINEL"

    async def mint(installation_id: int, *, force_refresh: bool = False) -> str:
        raise RuntimeError(f"mint failed with {secret}")

    with caplog.at_level(logging.DEBUG, logger="app.gateway.github.reactions"):
        ok = await post_comment_reaction(_target(), QUEUED_REACTION, mint_token=mint)

    assert ok is False
    assert secret not in caplog.text
    assert any("RuntimeError" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_unreactable_target_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP client should not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", fail_client)
    ok = await post_comment_reaction(_target(repo="not a repo"), QUEUED_REACTION, mint_token=_unused_mint)
    assert ok is False


async def _unused_mint(installation_id: int, *, force_refresh: bool = False) -> str:
    raise AssertionError("token mint should not run")
