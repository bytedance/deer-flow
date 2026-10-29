# SPDX-License-Identifier: MIT
"""Browser captures must not be published half written under the final name."""

from __future__ import annotations

import inspect
import logging
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


def test_descriptor_cleanup_failure_still_attempts_unlink(tmp_path, monkeypatch, publisher, caplog):
    target = tmp_path / "shot.png"
    publish_error = OSError("fdopen failed")
    close = os.close
    closed = []

    def fail_fdopen(*args):
        raise publish_error

    def fail_close(fd):
        close(fd)
        closed.append(fd)
        raise OSError("close failed")

    with monkeypatch.context() as patches:
        patches.setattr(os, "fdopen", fail_fdopen)
        patches.setattr(os, "close", fail_close)
        with pytest.raises(OSError) as caught:
            publisher(target, b"new")

    assert caught.value is publish_error
    assert len(closed) == 1
    assert list(tmp_path.iterdir()) == []
    records = [record for record in caplog.records if record.name == "deerflow.utils.atomic_write"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "close" in records[0].getMessage()
    assert records[0].exc_info[1].args == ("close failed",)


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


@pytest.mark.parametrize("publish_error", [OSError("publication failed"), KeyboardInterrupt("publication interrupted")], ids=["io-error", "interrupt"])
@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
def test_cleanup_failure_preserves_publication_error(tmp_path, monkeypatch, publisher, publish_error, existing, caplog):
    target = tmp_path / "shot.png"
    if existing:
        target.write_bytes(b"old")
    cleanup_attempts = []

    def fail_publish(*args):
        raise publish_error

    def fail_cleanup(path, **kwargs):
        cleanup_attempts.append(path)
        raise PermissionError("cleanup failed")

    with monkeypatch.context() as patches:
        patches.setattr(os, "replace", fail_publish)
        patches.setattr(Path, "unlink", fail_cleanup)
        with pytest.raises(type(publish_error)) as caught:
            publisher(target, b"new complete capture")

    assert caught.value is publish_error
    assert len(cleanup_attempts) == 1
    assert cleanup_attempts[0].parent == tmp_path
    assert cleanup_attempts[0].read_bytes() == b"new complete capture"
    records = [record for record in caplog.records if record.name == "deerflow.utils.atomic_write"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert str(cleanup_attempts[0]) in records[0].getMessage()
    assert isinstance(records[0].exc_info[1], PermissionError)
    if existing:
        assert target.read_bytes() == b"old"
    else:
        assert not target.exists()


def test_both_cleanup_failures_are_logged_without_masking_interruption(tmp_path, monkeypatch, publisher, caplog):
    interruption = KeyboardInterrupt("publication interrupted")
    close = os.close

    def fail_fdopen(*args):
        raise interruption

    def fail_close(fd):
        close(fd)
        raise OSError("close failed")

    def fail_unlink(*args, **kwargs):
        raise PermissionError("unlink failed")

    with monkeypatch.context() as patches:
        patches.setattr(os, "fdopen", fail_fdopen)
        patches.setattr(os, "close", fail_close)
        patches.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(KeyboardInterrupt) as caught:
            publisher(tmp_path / "shot.png", b"new")

    assert caught.value is interruption
    records = [record for record in caplog.records if record.name == "deerflow.utils.atomic_write"]
    assert [record.levelno for record in records] == [logging.WARNING, logging.WARNING]
    assert [record.exc_info[1].args for record in records] == [("close failed",), ("unlink failed",)]
    assert len(list(tmp_path.glob("*.tmp"))) == 1


@pytest.mark.parametrize("publish_error_type", [OSError, KeyboardInterrupt], ids=["io-error", "interrupt"])
@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
@pytest.mark.parametrize("cleanup_failure", ["close", "unlink", "both"])
def test_failing_log_handler_preserves_error_and_independent_cleanup(tmp_path, monkeypatch, publisher, caplog, publish_error_type, existing, cleanup_failure):
    target = tmp_path / "shot.png"
    if existing:
        target.write_bytes(b"old")
    publish_error = publish_error_type("publication failed")
    close = os.close
    unlink = Path.unlink
    unlink_attempts = []
    warning_attempts = []

    def fail_publish(*args):
        raise publish_error

    def fail_close(fd):
        close(fd)
        raise OSError("close failed")

    def cleanup(path, **kwargs):
        unlink_attempts.append(path)
        if cleanup_failure in {"unlink", "both"}:
            raise PermissionError("unlink failed")
        return unlink(path, **kwargs)

    # A standard delayed FileHandler raises from emit when its directory is
    # unavailable; this exercises logging itself rather than mocking warning().
    handler = logging.FileHandler(tmp_path / "missing-log-directory" / "cleanup.log", delay=True)
    emit = handler.emit

    def record_warning(record):
        warning_attempts.append(record)
        emit(record)

    log = logging.getLogger("deerflow.utils.atomic_write")
    log.addHandler(handler)
    try:
        with monkeypatch.context() as patches:
            patches.setattr(handler, "emit", record_warning)
            patches.setattr(Path, "unlink", cleanup)
            if cleanup_failure in {"close", "both"}:
                patches.setattr(os, "fdopen", fail_publish)
                patches.setattr(os, "close", fail_close)
            else:
                patches.setattr(os, "replace", fail_publish)
            with caplog.at_level(logging.WARNING, logger=log.name), pytest.raises(publish_error_type) as caught:
                publisher(target, b"new complete capture")
    finally:
        log.removeHandler(handler)
        handler.close()

    assert caught.value is publish_error
    assert len(unlink_attempts) == 1
    temporary = unlink_attempts[0]
    assert temporary.parent == tmp_path
    assert temporary.exists() == (cleanup_failure in {"unlink", "both"})
    assert len(warning_attempts) == (2 if cleanup_failure == "both" else 1)
    assert all(str(temporary) in record.getMessage() and record.exc_info is not None for record in warning_attempts)
    if existing:
        assert target.read_bytes() == b"old"
    else:
        assert not target.exists()
