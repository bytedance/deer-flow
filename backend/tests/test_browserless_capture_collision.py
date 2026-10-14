"""Browserless captures must retain every successful concurrent output."""

import asyncio
import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from support.symlinks import symlink_or_skip

from deerflow.community.browserless import tools
from deerflow.community.browserless.browserless_client import BrowserlessScreenshotResult


def _synchronize_first_publications(monkeypatch):
    publish = tools._publish_bytes_atomically
    barrier = threading.Barrier(2, timeout=10)
    worker = threading.local()

    def publish_together(path, content, **kwargs):
        if not getattr(worker, "arrived", False):
            worker.arrived = True
            # Both writers selected their candidate before either publishes.
            barrier.wait()
        return publish(path, content, **kwargs)

    monkeypatch.setattr(tools, "_publish_bytes_atomically", publish_together)


@pytest.mark.parametrize("existing", [False, True], ids=["empty", "existing"])
def test_concurrent_captures_keep_distinct_payloads(tmp_path, monkeypatch, existing):
    if existing:
        (tmp_path / "report.png").write_bytes(b"original")
    _synchronize_first_publications(monkeypatch)
    payloads = [b"capture A", b"capture B"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(tools._write_capture_output, tmp_path, "report.png", payload) for payload in payloads]
        names = [future.result(timeout=15) for future in futures]

    expected = {"report-1.png", "report-2.png"} if existing else {"report.png", "report-1.png"}
    assert set(names) == expected
    assert {(tmp_path / name).read_bytes() for name in names} == set(payloads)
    if existing:
        assert (tmp_path / "report.png").read_bytes() == b"original"
    assert {path.name for path in tmp_path.iterdir()} == expected | ({"report.png"} if existing else set())


def test_capture_preserves_a_dangling_symlink_name(tmp_path):
    original = tmp_path / "report.png"
    symlink_or_skip(original, tmp_path / "missing.png")

    name = tools._write_capture_output(tmp_path, "report.png", b"capture")

    assert name == "report-1.png"
    assert original.is_symlink()
    assert (tmp_path / name).read_bytes() == b"capture"
    assert {path.name for path in tmp_path.iterdir()} == {"report.png", "report-1.png"}


def test_capture_bounds_publication_collision_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_MAX_FILENAME_COLLISION_PROBES", 2)
    attempts = []

    def competing_publication(path, content, **kwargs):
        attempts.append(path.name)
        path.write_bytes(b"competing capture")
        raise FileExistsError("candidate was taken")

    monkeypatch.setattr(tools, "_publish_bytes_atomically", competing_publication)
    with pytest.raises(FileExistsError, match="filename collisions"):
        tools._write_capture_output(tmp_path, "report.png", b"capture")

    assert attempts == ["report.png", "report-1.png"]
    assert {path.read_bytes() for path in tmp_path.iterdir()} == {b"competing capture"}


def test_capture_does_not_retry_other_publication_errors(tmp_path, monkeypatch):
    error = PermissionError("cannot publish")
    attempts = []

    def fail(path, content, **kwargs):
        attempts.append(path)
        raise error

    monkeypatch.setattr(tools, "_publish_bytes_atomically", fail)
    with pytest.raises(PermissionError) as raised:
        tools._write_capture_output(tmp_path, "report.png", b"capture")

    assert raised.value is error
    assert len(attempts) == 1
    assert list(tmp_path.iterdir()) == []


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 8, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["report.png", None], ids=["explicit-name", "same-second-default"])
async def test_parallel_capture_tools_return_distinct_complete_artifacts(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(tools, "datetime", _FixedDateTime)
    monkeypatch.setattr(tools, "_get_tool_config", lambda name: {"base_url": "https://production-sfo.browserless.io"})
    monkeypatch.setattr(tools, "_resolve_host_addresses", lambda hostname: [ipaddress.ip_address("93.184.216.34")])
    payloads = [b"\x89PNG\r\n\x1a\ncapture A", b"\x89PNG\r\n\x1a\ncapture B"]
    responses = [BrowserlessScreenshotResult(content=payload, content_type="image/png", target_status_code="200", target_status="OK", final_url="https://example.com/dashboard") for payload in payloads]
    client = SimpleNamespace(capture_screenshot=AsyncMock(side_effect=responses))
    monkeypatch.setattr(tools, "_get_browserless_client", lambda *args: client)
    _synchronize_first_publications(monkeypatch)
    runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(tmp_path)}})

    results = await asyncio.gather(*(tools.web_capture_tool.coroutine(runtime=runtime, url="https://example.com/dashboard", tool_call_id=f"call-{index}", filename=filename) for index in range(2)))

    artifacts = [result.update["artifacts"][0] for result in results]
    assert len(set(artifacts)) == 2
    assert {(tmp_path / Path(artifact).name).read_bytes() for artifact in artifacts} == set(payloads)
    assert {path.name for path in tmp_path.iterdir()} == {Path(artifact).name for artifact in artifacts}
    for index, result in enumerate(results):
        message = result.update["messages"][0]
        assert message.tool_call_id == f"call-{index}"
        assert message.content == f"Captured screenshot: {artifacts[index]}"
