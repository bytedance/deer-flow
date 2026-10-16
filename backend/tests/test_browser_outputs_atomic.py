# SPDX-License-Identifier: MIT
"""Browser captures must not be published half written under the final name."""

from __future__ import annotations

import inspect
import os
import stat
from pathlib import Path

import pytest

from deerflow.community.browser_automation import tools as browser_automation_tools
from deerflow.community.browserless import tools as browserless_tools
from deerflow.utils.atomic_write import publish_bytes_atomically


@pytest.fixture(params=[browser_automation_tools, browserless_tools], ids=["browser", "browserless"])
def publisher(request):
    return request.param._publish_bytes_atomically


def test_publish_replaces_only_after_content_is_complete(tmp_path, monkeypatch, publisher):
    target = tmp_path / "shot.png"
    target.write_bytes(b"old")
    replace = os.replace
    publications = []

    def observe_replace(source, destination):
        assert target.read_bytes() == b"old"
        assert destination == target
        temporary = Path(source)
        assert temporary.parent == target.parent
        assert temporary.name.startswith(".")
        assert temporary.read_bytes() == b"new complete capture"
        if os.name != "nt":
            assert stat.S_IMODE(temporary.stat().st_mode) == stat.S_IMODE(target.stat().st_mode)
        publications.append(destination)
        replace(source, destination)

    monkeypatch.setattr(os, "replace", observe_replace)
    publisher(target, b"new complete capture")

    assert publications == [target]
    assert target.read_bytes() == b"new complete capture"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits and umask")
@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644])
def test_publish_preserves_existing_permissions(tmp_path, publisher, mode):
    target = tmp_path / "shot.png"
    target.write_bytes(b"old")
    target.chmod(mode)

    publisher(target, b"new")

    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits and umask")
@pytest.mark.parametrize("mask", [0o022, 0o077])
def test_publish_new_file_uses_normal_creation_permissions(tmp_path, publisher, mask):
    target = tmp_path / "shot.png"
    previous_mask = os.umask(mask)
    try:
        publisher(target, b"new")
    finally:
        os.umask(previous_mask)

    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~mask
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("stage", ["write", "fsync", "replace"])
@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
def test_publish_failure_preserves_target_and_cleans_temporary(tmp_path, monkeypatch, publisher, stage, existing):
    target = tmp_path / "shot.png"
    if existing:
        target.write_bytes(b"old")
    old_mode = target.stat().st_mode if existing else None

    def fail(*args, **kwargs):
        raise OSError("publication failed")

    if stage == "write":
        fdopen = os.fdopen

        class PartialWriter:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, content):
                self.handle.write(content[:2])
                fail()

        monkeypatch.setattr(os, "fdopen", lambda *args, **kwargs: PartialWriter(fdopen(*args, **kwargs)))
    else:
        monkeypatch.setattr(os, stage, fail)

    with pytest.raises(OSError, match="publication failed"):
        publisher(target, b"new complete capture")

    if existing:
        assert target.read_bytes() == b"old"
        assert target.stat().st_mode == old_mode
        assert list(tmp_path.iterdir()) == [target]
    else:
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor permissions")
def test_publish_permission_failure_keeps_previous_file(tmp_path, monkeypatch, publisher):
    target = tmp_path / "shot.png"
    target.write_bytes(b"old")
    target.chmod(0o640)

    def fail(*args):
        raise OSError("permission setup failed")

    monkeypatch.setattr(os, "fchmod", fail)
    with pytest.raises(OSError, match="permission setup failed"):
        publisher(target, b"new")

    assert target.read_bytes() == b"old"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert list(tmp_path.iterdir()) == [target]


def test_screenshot_writes_go_through_the_atomic_publish():
    source = inspect.getsource(browser_automation_tools)

    # A truncating write left a partial capture behind while the function returned
    # the name as if it had been saved.
    assert "(outputs_path / name).write_bytes(" not in source
    assert "_publish_bytes_atomically(outputs_path / name, content)" in source


def test_capture_writes_go_through_the_atomic_publish():
    source = inspect.getsource(browserless_tools)

    assert "(outputs_path / final_name).write_bytes(" not in source
    assert "destination.unlink(missing_ok=True)" in source
    assert "_publish_bytes_atomically(destination, content)" in source


def test_both_tools_share_the_atomic_publisher():
    for module in (browser_automation_tools, browserless_tools):
        assert module._publish_bytes_atomically is publish_bytes_atomically
