# SPDX-License-Identifier: MIT
"""``browser_screenshot`` must never replace a file already in the outputs directory."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community.browser_automation import tools

_SHOT = b"\x89PNG\r\n\x1a\nscreenshot"


async def _screenshot(outputs: Path, filename: str | None = "report.png"):
    session = MagicMock()
    session.screenshot_bytes = AsyncMock(return_value=_SHOT)
    manager = MagicMock()
    manager.get_session.return_value = session
    runtime = SimpleNamespace(context={"thread_id": "thread-1"}, state={"thread_data": {"outputs_path": str(outputs)}})
    with patch.object(tools, "get_browser_session_manager", return_value=manager), patch.object(tools, "_get_tool_config", return_value={}):
        return await tools.browser_screenshot_tool.coroutine(runtime=runtime, tool_call_id="t1", filename=filename)


def _artifact(result) -> str:
    return result.update["artifacts"][0]


@pytest.mark.asyncio
async def test_screenshot_keeps_an_existing_output_and_takes_the_next_name(tmp_path):
    (tmp_path / "report.png").write_bytes(b"user report")

    result = await _screenshot(tmp_path)

    assert _artifact(result) == "/mnt/user-data/outputs/report-1.png"
    assert "Saved browser screenshot: /mnt/user-data/outputs/report-1.png" in result.update["messages"][0].content
    assert (tmp_path / "report.png").read_bytes() == b"user report"
    assert (tmp_path / "report-1.png").read_bytes() == _SHOT
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report-1.png", "report.png"]


@pytest.mark.asyncio
async def test_repeated_screenshots_with_one_filename_keep_every_capture(tmp_path):
    names = [_artifact(await _screenshot(tmp_path)).rsplit("/", 1)[1] for _ in range(3)]

    assert names == ["report.png", "report-1.png", "report-2.png"]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(names)


@pytest.mark.asyncio
async def test_a_name_claimed_after_the_choice_is_not_replaced(tmp_path, monkeypatch):
    # A peer (another tool call, or the user) can create a name after an
    # existence check chose it. Simulate that window: whenever bytes are about
    # to be written onto a visible name, a peer claims that name first. Only a
    # publication that itself refuses occupied names keeps every peer file.
    publish = tools._publish_bytes_atomically
    claimed: list[Path] = []

    def peer_claims_name_before_write(path, content):
        if not path.name.startswith(".") and not path.exists():
            path.write_bytes(b"peer output")
            claimed.append(path)
        publish(path, content)

    monkeypatch.setattr(tools, "_publish_bytes_atomically", peer_claims_name_before_write)
    result = await _screenshot(tmp_path)

    saved = tmp_path / _artifact(result).rsplit("/", 1)[1]
    assert saved.read_bytes() == _SHOT
    assert saved not in claimed
    assert all(path.read_bytes() == b"peer output" for path in claimed)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation")
@pytest.mark.asyncio
async def test_screenshot_does_not_replace_a_symlink_at_the_name(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "report.png").symlink_to(tmp_path / "missing-target.png")

    result = await _screenshot(outputs)

    assert _artifact(result) == "/mnt/user-data/outputs/report-1.png"
    assert (outputs / "report.png").is_symlink()
    assert not (tmp_path / "missing-target.png").exists()


@pytest.mark.asyncio
async def test_failed_publication_reports_an_error_and_leaves_no_files(tmp_path, monkeypatch):
    (tmp_path / "report.png").write_bytes(b"user report")

    def no_hard_links(*args, **kwargs):
        raise OSError(errno.EPERM, "hard links unsupported")

    monkeypatch.setattr(os, "link", no_hard_links)
    result = await _screenshot(tmp_path)

    assert "artifacts" not in result.update
    assert "Error: could not capture screenshot" in result.update["messages"][0].content
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.png"]
    assert (tmp_path / "report.png").read_bytes() == b"user report"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits and umask")
@pytest.mark.parametrize("mask", [0o022, 0o077])
@pytest.mark.asyncio
async def test_screenshot_uses_normal_creation_permissions(tmp_path, mask):
    previous_mask = os.umask(mask)
    try:
        await _screenshot(tmp_path)
    finally:
        os.umask(previous_mask)

    assert stat.S_IMODE((tmp_path / "report.png").stat().st_mode) == 0o666 & ~mask


@pytest.mark.asyncio
async def test_default_names_from_the_same_second_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_safe_screenshot_name", lambda filename: "browser-capture-20261015-120000.png")

    first = _artifact(await _screenshot(tmp_path, filename=None))
    second = _artifact(await _screenshot(tmp_path, filename=None))

    assert first.endswith("/browser-capture-20261015-120000.png")
    assert second.endswith("/browser-capture-20261015-120000-1.png")
