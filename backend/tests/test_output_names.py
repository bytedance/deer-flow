# SPDX-License-Identifier: MIT
"""Both capture tools take output names from one shared candidate sequence."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from itertools import islice
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.utils import output_names

browser_automation_tools = importlib.import_module("deerflow.community.browser_automation.tools")
browserless_tools = importlib.import_module("deerflow.community.browserless.tools")


class _StepClock(datetime):
    """Each call advances one microsecond, so every fallback stamp is distinct."""

    ticks = 0

    @classmethod
    def now(cls, tz=None):
        cls.ticks += 1
        return datetime(2026, 10, 18, 12, 0, 0, cls.ticks, tzinfo=UTC)


def test_candidates_keep_the_name_then_number_then_timestamp(monkeypatch):
    monkeypatch.setattr(output_names, "MAX_COLLISION_PROBES", 2)
    monkeypatch.setattr(_StepClock, "ticks", 0)
    monkeypatch.setattr(output_names, "datetime", _StepClock)

    assert list(output_names.output_name_candidates("report.png")) == [
        "report.png",
        "report-1.png",
        "report-2.png",
        *(f"report-20261018-120000-{tick:06d}.png" for tick in range(1, output_names.MAX_TIMESTAMP_ATTEMPTS + 1)),
    ]


def test_candidates_read_the_clock_only_when_a_fallback_is_reached(monkeypatch):
    monkeypatch.setattr(_StepClock, "ticks", 0)
    monkeypatch.setattr(output_names, "datetime", _StepClock)

    assert len(list(islice(output_names.output_name_candidates("a.png"), output_names.MAX_COLLISION_PROBES + 1))) == output_names.MAX_COLLISION_PROBES + 1
    assert _StepClock.ticks == 0


def test_both_capture_tools_share_the_candidate_sequence():
    for module in (browser_automation_tools, browserless_tools):
        assert module.output_name_candidates is output_names.output_name_candidates


@pytest.mark.asyncio
async def test_screenshot_retries_a_held_timestamp_fallback(tmp_path, monkeypatch):
    # Browserless already retried a held timestamped name; the screenshot tool
    # now shares that bound instead of giving up after one stamp.
    monkeypatch.setattr(output_names, "MAX_COLLISION_PROBES", 1)
    monkeypatch.setattr(_StepClock, "ticks", 0)
    monkeypatch.setattr(output_names, "datetime", _StepClock)
    held = ["report.png", "report-1.png", "report-20261018-120000-000001.png"]
    for name in held:
        (tmp_path / name).write_bytes(b"earlier")

    session = MagicMock()
    session.screenshot_bytes = AsyncMock(return_value=b"shot")
    manager = MagicMock()
    manager.get_session.return_value = session
    runtime = SimpleNamespace(context={"thread_id": "thread-1"}, state={"thread_data": {"outputs_path": str(tmp_path)}})
    with patch.object(browser_automation_tools, "get_browser_session_manager", return_value=manager), patch.object(browser_automation_tools, "_get_tool_config", return_value={}):
        result = await browser_automation_tools.browser_screenshot_tool.coroutine(runtime=runtime, tool_call_id="t1", filename="report.png")

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report-20261018-120000-000002.png"]
    assert (tmp_path / "report-20261018-120000-000002.png").read_bytes() == b"shot"
    assert all((tmp_path / name).read_bytes() == b"earlier" for name in held)
