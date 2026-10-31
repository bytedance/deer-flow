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
    # A peer (another tool call, or the user) can create a name after the
    # publisher chose it. Simulate that window at the publication step itself:
    # right before a link or replace lands the capture on a visible name, a
    # peer claims that name. Only a publication that refuses occupied names at
    # that step keeps the peer file.
    link, replace = os.link, os.replace
    claimed: list[Path] = []

    def peer_claims(destination) -> None:
        destination = Path(destination)
        if not claimed and not destination.name.startswith("."):
            destination.write_bytes(b"peer output")
            claimed.append(destination)

    def link_after_peer(source, destination, *args, **kwargs):
        peer_claims(destination)
        return link(source, destination, *args, **kwargs)

    def replace_after_peer(source, destination, *args, **kwargs):
        peer_claims(destination)
        return replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", link_after_peer)
    monkeypatch.setattr(os, "replace", replace_after_peer)
    result = await _screenshot(tmp_path)

    assert claimed == [tmp_path / "report.png"]
    assert _artifact(result) == "/mnt/user-data/outputs/report-1.png"
    assert (tmp_path / "report.png").read_bytes() == b"peer output"
    assert (tmp_path / "report-1.png").read_bytes() == _SHOT


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


def _swap_staged_before_link(monkeypatch, replace_staged, watch: Path | None = None) -> list[int]:
    """Replace the staged capture right before it is linked, as a sandbox writing ``outputs/`` could.

    Returns the link counts of *watch* observed right after each link call.
    """
    link = os.link
    link_counts: list[int] = []

    def swapped_link(source, destination, *args, **kwargs):
        source = Path(source)
        if source.name.startswith(".") and source.is_file() and not source.is_symlink():
            source.unlink()
            replace_staged(source)
        try:
            return link(source, destination, *args, **kwargs)
        finally:
            if watch is not None:
                link_counts.append(watch.stat().st_nlink)

    monkeypatch.setattr(os, "link", swapped_link)
    return link_counts


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation")
@pytest.mark.asyncio
async def test_a_staged_capture_swapped_for_a_symlink_never_publishes_its_target(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    secret = tmp_path / "host-secret.txt"
    secret.write_bytes(b"host secret")
    link_counts = _swap_staged_before_link(monkeypatch, lambda staged: staged.symlink_to(secret), watch=secret)

    result = await _screenshot(outputs)

    assert "artifacts" not in result.update
    assert "Error: could not capture screenshot" in result.update["messages"][0].content
    assert list(outputs.iterdir()) == []
    # The host file never gains a name in outputs/, not even briefly.
    assert link_counts and set(link_counts) == {1}


@pytest.mark.asyncio
async def test_a_staged_capture_swapped_for_another_file_is_not_published(tmp_path, monkeypatch):
    _swap_staged_before_link(monkeypatch, lambda staged: staged.write_bytes(b"planted"))

    result = await _screenshot(tmp_path)

    assert "artifacts" not in result.update
    assert "Error: could not capture screenshot" in result.update["messages"][0].content
    assert list(tmp_path.iterdir()) == []


def _open_descriptors_for(target: os.stat_result) -> list[int]:
    descriptors = []
    for entry in os.listdir("/dev/fd"):
        try:
            if os.path.samestat(os.fstat(int(entry)), target):
                descriptors.append(int(entry))
        except OSError:
            continue
    return descriptors


@pytest.mark.skipif(not os.path.isdir("/dev/fd"), reason="needs /dev/fd to list open descriptors")
@pytest.mark.asyncio
async def test_the_staged_capture_stays_open_while_it_is_linked(tmp_path, monkeypatch):
    # Linux filesystems hand a freed inode number to the next file at once, so
    # a capture whose descriptor is closed before the link lets a swapped-in
    # file reuse its number and pass the identity check. macOS rarely reuses
    # numbers, so the swap tests above only catch that there; pin the guard
    # itself: an open descriptor keeps the staged inode allocated.
    link = os.link
    open_at_link: list[list[int]] = []

    def observing_link(source, destination, *args, **kwargs):
        open_at_link.append(_open_descriptors_for(os.lstat(source)))
        return link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", observing_link)
    result = await _screenshot(tmp_path)

    assert _artifact(result) == "/mnt/user-data/outputs/report.png"
    assert open_at_link and all(open_at_link)


@pytest.mark.asyncio
async def test_a_failed_staging_write_leaves_no_files(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(os, "fsync", fail)
    result = await _screenshot(tmp_path)

    assert "Error: could not capture screenshot" in result.update["messages"][0].content
    assert list(tmp_path.iterdir()) == []


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
