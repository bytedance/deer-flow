"""Tests for the GitHubChannel.

The channel is log-only on the outbound path: GitHub agents have ``gh`` in
their sandbox and post comments themselves mid-run, so the channel does NOT
auto-deliver the agent's final assistant message to GitHub. These tests pin
that contract — any regression that re-introduces an HTTP call during
``send`` will fail the httpx tripwire.

Queued and overflow acknowledgements are a separate path
(``acknowledge_followup``). They may POST a comment reaction; ``send`` must
not.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

import app.channels.github as github_channel_module
from app.channels.github import GitHubChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.service import _CHANNEL_REGISTRY


def test_github_channel_registered() -> None:
    assert _CHANNEL_REGISTRY["github"] == "app.channels.github:GitHubChannel"


def test_github_channel_capabilities_non_streaming() -> None:
    # GitHub comments are single-shot; no in-place editing (yet).
    assert CHANNEL_CAPABILITIES["github"]["supports_streaming"] is False


def test_github_channel_does_not_import_writeback() -> None:
    """The ``writeback`` module has been deleted — confirm the channel does
    not re-import it under any name."""
    # Check both the old module path and any httpx usage inside the channel
    assert "app.gateway.github.writeback" not in dir(github_channel_module)


@pytest.mark.asyncio
async def test_start_subscribes_outbound_and_stop_unsubscribes() -> None:
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={"enabled": True})

    assert channel.is_running is False
    assert bus._outbound_listeners == []

    await channel.start()
    assert channel.is_running is True
    assert bus._outbound_listeners == [channel._on_outbound]

    await channel.stop()
    assert channel.is_running is False
    assert bus._outbound_listeners == []


@pytest.mark.asyncio
async def test_send_never_posts_to_github(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """The contract: ``send`` logs but never makes an HTTP call.

    We patch ``httpx.AsyncClient.request`` as the tripwire — the channel
    (unlike the old ``writeback`` module) has no business talking to GitHub
    over HTTP. If a future refactor wires it back, the mock will be awaited
    and the test fails.
    """
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="zhfeng/llm-gateway",
        thread_id="t-1",
        text="Hello from the agent.",
        metadata={
            "github": {
                "repo": "zhfeng/llm-gateway",
                "number": 7,
                "installation_id": 1234,
            }
        },
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("final message from agent for zhfeng/llm-gateway#7" in rec.message and "not posted" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_logs_empty_body_at_info(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """An empty final message still gets the info log (text_len=0). The body
    debug line is skipped when there's nothing to mirror."""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="",
        metadata={"github": {"repo": "a/b", "number": 1, "installation_id": 1}},
    )
    with caplog.at_level(logging.DEBUG, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("text_len=0" in rec.message for rec in caplog.records)
    assert not any("final body" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_tolerates_missing_metadata(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """No github metadata block: log line falls back to ``chat_id`` as the
    repo and ``None`` for the number. Still no HTTP call."""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="hi",
        metadata={},  # no github block at all
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    # ``chat_id`` falls in as the repo when metadata is absent.
    assert any("a/b" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_send_handles_non_dict_github_metadata(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Defensive: a stringly-typed ``metadata["github"]`` must not raise."""
    bus = MessageBus()
    channel = GitHubChannel(bus=bus, config={})

    tripwire = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "request", tripwire)

    out = OutboundMessage(
        channel_name="github",
        chat_id="a/b",
        thread_id="t",
        text="hi",
        metadata={"github": "not-a-dict"},
    )
    with caplog.at_level(logging.INFO, logger="app.channels.github"):
        await channel.send(out)

    tripwire.assert_not_awaited()
    assert any("a/b" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_acknowledge_followup_posts_eyes_and_confused(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = GitHubChannel(bus=MessageBus(), config={})
    calls: list[tuple[dict, str]] = []

    async def capture(target, content):
        calls.append((dict(target), content))
        return True

    monkeypatch.setattr("app.channels.github.post_comment_reaction", capture)
    target = {"provider": "github", "repo": "octo/hello", "comment_id": 4242, "subject": "issue_comment", "installation_id": 77}
    await channel.acknowledge_followup(target, kind="queued")
    await channel.acknowledge_followup(target, kind="overflow")

    assert calls == [(target, "eyes"), (target, "confused")]


@pytest.mark.asyncio
async def test_acknowledge_followup_ignores_unknown_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = GitHubChannel(bus=MessageBus(), config={})

    async def fail(*args, **kwargs):
        raise AssertionError("reaction should not be posted")

    monkeypatch.setattr("app.channels.github.post_comment_reaction", fail)
    await channel.acknowledge_followup({"provider": "slack", "comment_id": 1}, kind="queued")
    await channel.acknowledge_followup({"provider": "github", "comment_id": 1}, kind="working")


@pytest.mark.asyncio
async def test_acknowledge_followup_swallows_poster_errors(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = GitHubChannel(bus=MessageBus(), config={})

    async def explode(*args, **kwargs):
        raise RuntimeError("token=ghs_should_not_leak")

    monkeypatch.setattr("app.channels.github.post_comment_reaction", explode)
    with caplog.at_level(logging.WARNING, logger="app.channels.github"):
        await channel.acknowledge_followup({"provider": "github"}, kind="queued")

    assert "ghs_should_not_leak" not in caplog.text
    assert any("comment reaction failed kind=queued" in record.message for record in caplog.records)
