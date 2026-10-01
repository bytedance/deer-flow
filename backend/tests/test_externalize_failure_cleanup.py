"""A failed externalization must not leave a half-written output behind."""

import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from deerflow.agents.middlewares import tool_output_budget_middleware as mw


class _FailsAfterHalfTheWrite:
    """File object that fails part-way through the write, like a full disk."""

    def __init__(self, handle):
        self._handle = handle
        self.name = handle.name

    def write(self, data):
        self._handle.write(data[: len(data) // 2])
        self._handle.flush()
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._handle.close()
        return False


def test_failed_write_leaves_no_file_behind(tmp_path, monkeypatch):
    real_temporary_file = mw.tempfile.NamedTemporaryFile

    def failing_temporary_file(*args, **kwargs):
        return _FailsAfterHalfTheWrite(real_temporary_file(*args, **kwargs))

    monkeypatch.setattr(mw.tempfile, "NamedTemporaryFile", failing_temporary_file)

    result = mw._externalize(
        "X" * 100,
        tool_name="bash",
        tool_call_id="call_1",
        outputs_path=str(tmp_path),
        storage_subdir="sub",
    )

    assert result is None
    assert [p for p in pathlib.Path(tmp_path).rglob("*") if p.is_file()] == []


def test_successful_write_publishes_the_whole_content(tmp_path):
    result = mw._externalize(
        "Y" * 100,
        tool_name="bash",
        tool_call_id="call_2",
        outputs_path=str(tmp_path),
        storage_subdir="sub",
    )

    assert result is not None
    written = [p for p in pathlib.Path(tmp_path).rglob("*") if p.is_file()]
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == "Y" * 100


@pytest.mark.parametrize("second_publish_fails", [False, True])
def test_concurrent_externalizations_do_not_share_temporary_files(tmp_path, monkeypatch, second_publish_fails):
    first_ready = threading.Event()
    release_first = threading.Event()
    real_replace = mw.os.replace

    def ordered_replace(source, destination):
        if not first_ready.is_set():
            # The first writer has closed its file but has not published it.
            first_ready.set()
            assert release_first.wait(timeout=10)
        elif second_publish_fails:
            raise OSError("Publication failed")
        return real_replace(source, destination)

    monkeypatch.setattr(mw.os, "replace", ordered_replace)
    kwargs = dict(tool_name="bash", tool_call_id="same_call", outputs_path=str(tmp_path), storage_subdir="sub")
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(mw._externalize, "A" * 1000, **kwargs)
        try:
            assert first_ready.wait(timeout=10)
            second_path = mw._externalize("B" * 200, **kwargs)
        finally:
            # Always release the worker, including when the second call fails.
            release_first.set()
        first_path = first.result(timeout=10)

    assert first_path == "/mnt/user-data/outputs/sub/bash-same_call.log"
    assert second_path == (None if second_publish_fails else first_path)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(written) == 1
    # The last successful publisher wins, without mixed bytes or leftover temps.
    assert written[0].read_text(encoding="utf-8") == "A" * 1000


def test_temporary_file_creation_failure_preserves_existing_output(tmp_path, monkeypatch):
    storage_dir = tmp_path / "sub"
    storage_dir.mkdir()
    published = storage_dir / "bash-call_1.log"
    published.write_text("Previous complete output", encoding="utf-8")

    def fail_to_create(*args, **kwargs):
        raise OSError("Cannot create temporary file")

    monkeypatch.setattr(mw.tempfile, "NamedTemporaryFile", fail_to_create)
    result = mw._externalize("New output", tool_name="bash", tool_call_id="call_1", outputs_path=str(tmp_path), storage_subdir="sub")

    assert result is None
    assert list(storage_dir.iterdir()) == [published]
    assert published.read_text(encoding="utf-8") == "Previous complete output"
