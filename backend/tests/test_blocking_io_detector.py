from __future__ import annotations

import asyncio
import os
import time
from os import walk as imported_walk
from pathlib import Path
from time import sleep as imported_sleep

import httpx
import pytest
import requests
from support.detectors.blocking_io import (
    BlockingCallSpec,
    BlockingIOProbe,
    detect_blocking_io,
)

pytestmark = pytest.mark.asyncio


TIME_SLEEP_ONLY = (BlockingCallSpec("time.sleep", "time:sleep"),)
REQUESTS_ONLY = (BlockingCallSpec("requests.Session.request", "requests.sessions:Session.request"),)
HTTPX_ONLY = (BlockingCallSpec("httpx.Client.request", "httpx:Client.request"),)
OS_WALK_ONLY = (BlockingCallSpec("os.walk", "os:walk", record_on_iteration=True),)
PATH_READ_TEXT_ONLY = (BlockingCallSpec("pathlib.Path.read_text", "pathlib:Path.read_text"),)


async def test_records_time_sleep_on_event_loop() -> None:
    with detect_blocking_io(TIME_SLEEP_ONLY) as detector:
        time.sleep(0)

    assert [violation.name for violation in detector.violations] == ["time.sleep"]


async def test_records_already_imported_sleep_alias_on_event_loop() -> None:
    original_alias = imported_sleep

    with detect_blocking_io(TIME_SLEEP_ONLY) as detector:
        imported_sleep(0)

    assert imported_sleep is original_alias
    assert [violation.name for violation in detector.violations] == ["time.sleep"]


async def test_can_disable_loaded_alias_patching() -> None:
    with detect_blocking_io(TIME_SLEEP_ONLY, patch_loaded_aliases=False) as detector:
        imported_sleep(0)

    assert detector.violations == []


async def test_does_not_record_time_sleep_offloaded_to_thread() -> None:
    with detect_blocking_io(TIME_SLEEP_ONLY) as detector:
        await asyncio.to_thread(time.sleep, 0)

    assert detector.violations == []


async def test_fixture_allows_offloaded_sync_work(blocking_io_detector) -> None:
    await asyncio.to_thread(time.sleep, 0)

    assert blocking_io_detector.violations == []


async def test_does_not_record_sync_call_without_running_event_loop() -> None:
    def call_sleep() -> list[str]:
        with detect_blocking_io(TIME_SLEEP_ONLY) as detector:
            time.sleep(0)
        return [violation.name for violation in detector.violations]

    assert await asyncio.to_thread(call_sleep) == []


async def test_fail_on_exit_includes_call_site() -> None:
    with pytest.raises(AssertionError) as exc_info:
        with detect_blocking_io(TIME_SLEEP_ONLY, fail_on_exit=True):
            time.sleep(0)

    message = str(exc_info.value)
    assert "time.sleep" in message
    assert "test_fail_on_exit_includes_call_site" in message


async def test_records_requests_session_request_without_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: requests.Session, method: str, url: str, **kwargs: object) -> str:
        return f"{method}:{url}"

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    with detect_blocking_io(REQUESTS_ONLY) as detector:
        assert requests.get("https://example.invalid") == "get:https://example.invalid"

    assert [violation.name for violation in detector.violations] == ["requests.Session.request"]


async def test_records_sync_httpx_client_request_without_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(self: httpx.Client, method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    with detect_blocking_io(HTTPX_ONLY) as detector:
        with httpx.Client() as client:
            response = client.get("https://example.invalid")

    assert response.status_code == 200
    assert [violation.name for violation in detector.violations] == ["httpx.Client.request"]


async def test_records_os_walk_on_event_loop(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()

    with detect_blocking_io(OS_WALK_ONLY) as detector:
        assert list(os.walk(tmp_path))

    assert [violation.name for violation in detector.violations] == ["os.walk"]


async def test_records_already_imported_os_walk_alias_on_iteration(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    original_alias = imported_walk

    with detect_blocking_io(OS_WALK_ONLY) as detector:
        assert list(imported_walk(tmp_path))

    assert imported_walk is original_alias
    assert [violation.name for violation in detector.violations] == ["os.walk"]


async def test_does_not_record_os_walk_before_iteration(tmp_path: Path) -> None:
    with detect_blocking_io(OS_WALK_ONLY) as detector:
        walker = os.walk(tmp_path)

    assert list(walker)
    assert detector.violations == []


async def test_does_not_record_os_walk_iterated_off_event_loop(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()

    with detect_blocking_io(OS_WALK_ONLY) as detector:
        walker = os.walk(tmp_path)
        assert await asyncio.to_thread(lambda: list(walker))

    assert detector.violations == []


async def test_records_path_read_text_on_event_loop(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("content", encoding="utf-8")

    with detect_blocking_io(PATH_READ_TEXT_ONLY) as detector:
        assert path.read_text(encoding="utf-8") == "content"

    assert [violation.name for violation in detector.violations] == ["pathlib.Path.read_text"]


async def test_probe_formats_summary_for_recorded_violations(tmp_path: Path) -> None:
    probe = BlockingIOProbe(Path(__file__).resolve().parents[1])
    path = tmp_path / "data.txt"
    path.write_text("content", encoding="utf-8")

    with detect_blocking_io(PATH_READ_TEXT_ONLY, stack_limit=18) as detector:
        assert path.read_text(encoding="utf-8") == "content"

    probe.record("tests/test_example.py::test_example", detector.violations)
    summary = probe.format_summary()

    assert "blocking io probe: 1 violations across 1 tests" in summary
    assert "pathlib.Path.read_text" in summary


async def test_probe_formats_empty_summary_and_can_be_cleared(tmp_path: Path) -> None:
    probe = BlockingIOProbe(Path(__file__).resolve().parents[1])

    assert probe.format_summary() == "blocking io probe: no violations"

    path = tmp_path / "data.txt"
    path.write_text("content", encoding="utf-8")
    with detect_blocking_io(PATH_READ_TEXT_ONLY, stack_limit=18) as detector:
        assert path.read_text(encoding="utf-8") == "content"

    probe.record("tests/test_example.py::test_example", detector.violations)
    assert probe.violation_count == 1

    probe.clear()

    assert probe.violation_count == 0
    assert probe.format_summary() == "blocking io probe: no violations"
