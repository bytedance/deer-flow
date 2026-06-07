"""Tests for ProbeRunner — orchestrates per-candidate bot probes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.collector.bot_search_throttle import (
    BotQueryLimitExceeded,
    BotQueryThrottle,
)
from tg_intel_crawler.probe.runner import ProbeRunner
from tg_intel_crawler.probe.sampler import SampledCandidate


def _public(key="douyinhao88", count=10):
    return SampledCandidate(
        key=key, count=count, invite_hash=None,
        candidate_type="public", stratum="L3",
    )


def _private(key="+abc", count=2):
    return SampledCandidate(
        key=key, count=count, invite_hash=key.lstrip("+"),
        candidate_type="private", stratum="L5",
    )


def _make_throttle():
    """A throttle that doesn't actually wait."""
    now = SimpleNamespace(t=0.0)
    async def fake_sleep(s):
        now.t += s
    return BotQueryThrottle(
        interval_seconds=0,
        max_queries_per_run=10_000,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )


def _stub_parser(previews_for_query):
    """Build a parser stub whose .parse() returns previews_for_query[query]."""
    class StubParser:
        def parse(self, reply_text, *, query, bot):
            return previews_for_query.get(query, [])
    return StubParser()


def _preview(channel_username=None):
    return BotPreview(
        bot="@JISOU", query="x", raw_line="🌄 ...", text="...",
        deeplink=None, channel_username=channel_username, msg_id=None,
        icon="🌄", seen_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_probe_public_direct_hit():
    bot = SimpleNamespace(query=AsyncMock(return_value="🌄 ..."))
    parser = _stub_parser({"douyinhao88": [_preview(channel_username="douyinhao88")]})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "direct_hit"
    assert rec.query_sent == "douyinhao88"
    assert rec.previews_count == 1
    assert rec.matched_preview is not None
    assert rec.matched_preview["channel_username"] == "douyinhao88"
    assert rec.error is None


@pytest.mark.asyncio
async def test_probe_private_strips_plus_prefix():
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_private(key="+abcXYZ"))
    bot.query.assert_called_once_with("abcXYZ")
    assert rec.classification == "empty_reply"


@pytest.mark.asyncio
async def test_probe_empty_reply_when_query_returns_none():
    bot = SimpleNamespace(query=AsyncMock(return_value=None))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "empty_reply"
    assert rec.reply_status == "empty_reply"
    assert rec.reply_raw == ""


@pytest.mark.asyncio
async def test_probe_no_results_when_reply_has_no_previews():
    bot = SimpleNamespace(query=AsyncMock(return_value="未找到结果"))
    parser = _stub_parser({"douyinhao88": []})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "no_results"
    assert rec.reply_status == "ok"
    assert rec.previews_count == 0


@pytest.mark.asyncio
async def test_probe_error_when_query_raises():
    bot = SimpleNamespace(query=AsyncMock(side_effect=RuntimeError("boom")))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert rec.classification == "error"
    assert rec.reply_status == "error"
    assert rec.error is not None
    assert "RuntimeError" in rec.error
    assert "boom" in rec.error


@pytest.mark.asyncio
async def test_probe_truncates_long_reply():
    long_reply = "x" * 5000
    bot = SimpleNamespace(query=AsyncMock(return_value=long_reply))
    parser = _stub_parser({"douyinhao88": []})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    rec = await runner.probe_one(_public())
    assert len(rec.reply_raw) <= 4096 + len("... [truncated]")
    assert rec.reply_raw.endswith("... [truncated]")


@pytest.mark.asyncio
async def test_run_processes_all_samples():
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})
    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=_make_throttle(), bot_name="@JISOU",
    )
    samples = [_public(key=f"pub_{i}") for i in range(3)]
    records, truncated = await runner.run(samples)
    assert len(records) == 3
    assert truncated is False
    assert {r.candidate.key for r in records} == {"pub_0", "pub_1", "pub_2"}


@pytest.mark.asyncio
async def test_run_stops_and_marks_truncated_on_limit_exceeded():
    """When the throttle raises BotQueryLimitExceeded mid-run, return what
    we have so far with truncated=True."""
    bot = SimpleNamespace(query=AsyncMock(return_value=""))
    parser = _stub_parser({})

    # Throttle that allows exactly 2 acquires.
    now = SimpleNamespace(t=0.0)
    async def fake_sleep(s):
        now.t += s
    throttle = BotQueryThrottle(
        interval_seconds=0,
        max_queries_per_run=2,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )

    runner = ProbeRunner(
        bot_client=bot, parser=parser, throttle=throttle, bot_name="@JISOU",
    )
    samples = [_public(key=f"pub_{i}") for i in range(5)]
    records, truncated = await runner.run(samples)
    assert len(records) == 2
    assert truncated is True
