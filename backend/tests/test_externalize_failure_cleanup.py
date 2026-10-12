"""A failed externalization must not leave a half-written output behind."""

import json
import os
import pathlib
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
    real_open = open

    def failing_open(*args, **kwargs):
        return _FailsAfterHalfTheWrite(real_open(*args, **kwargs))

    monkeypatch.setattr(mw, "open", failing_open, raising=False)

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
@pytest.mark.parametrize("second_content", ["A" * 1000, "B" * 200], ids=["identical-output", "different-output"])
def test_concurrent_externalizations_do_not_share_temporary_files(tmp_path, monkeypatch, second_publish_fails, second_content):
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
            second_path = mw._externalize(second_content, **kwargs)
        finally:
            # Always release the worker, including when the second call fails.
            release_first.set()
        first_path = first.result(timeout=10)

    assert first_path is not None
    if second_publish_fails:
        assert second_path is None
    else:
        assert second_path is not None
        assert (first_path == second_path) is (second_content == "A" * 1000)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(written) == (2 if second_path is not None and second_path != first_path else 1)
    # Every advertised path retains its complete bytes, with no leftover temps.
    assert (tmp_path / "sub" / first_path.rsplit("/", 1)[1]).read_text(encoding="utf-8") == "A" * 1000
    if second_path is not None:
        assert (tmp_path / "sub" / second_path.rsplit("/", 1)[1]).read_text(encoding="utf-8") == second_content


def test_temporary_file_creation_failure_preserves_existing_output(tmp_path, monkeypatch):
    storage_dir = tmp_path / "sub"
    content = "Previous complete output"
    path = mw._externalize(content, tool_name="bash", tool_call_id="call_1", outputs_path=str(tmp_path), storage_subdir="sub")
    assert path is not None
    published = storage_dir / path.rsplit("/", 1)[1]

    def fail_to_create(*args, **kwargs):
        raise OSError("Cannot create temporary file")

    monkeypatch.setattr(mw, "open", fail_to_create, raising=False)
    result = mw._externalize(content, tool_name="bash", tool_call_id="call_1", outputs_path=str(tmp_path), storage_subdir="sub")

    assert result is None
    assert list(storage_dir.iterdir()) == [published]
    assert published.read_text(encoding="utf-8") == "Previous complete output"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not available on Windows")
@pytest.mark.parametrize("mask", [0o022, 0o002, 0o077], ids=["other-readable", "group-writable", "private"])
def test_published_output_respects_umask(tmp_path, mask):
    # Set umask only in a child; it is process-global and must not race other tests.
    script = """
import json
import os
import pathlib
import stat
import sys
from deerflow.agents.middlewares import tool_output_budget_middleware as mw

os.umask(int(sys.argv[2]))
kwargs = dict(tool_name="bash", tool_call_id="mode", outputs_path=sys.argv[1], storage_subdir="sub")
content = "Complete output"
first_path = mw._externalize(content, **kwargs)
assert first_path is not None
published = pathlib.Path(sys.argv[1]) / "sub" / first_path.rsplit("/", 1)[1]
initial_mode = stat.S_IMODE(published.stat().st_mode)
os.chmod(published, 0o600)
assert mw._externalize(content, **kwargs) == first_path
print(json.dumps({"modes": [initial_mode, stat.S_IMODE(published.stat().st_mode)], "content": published.read_text(encoding="utf-8")}))
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(mask)], capture_output=True, text=True, timeout=30, check=True)
    observed = json.loads(completed.stdout)
    assert observed["content"] == "Complete output"
    assert observed["modes"] == [0o666 & ~mask] * 2


def test_exclusive_creation_collision_preserves_other_writers_temp(tmp_path, monkeypatch):
    storage_dir = tmp_path / "sub"
    content = "Previous complete output"
    path = mw._externalize(content, tool_name="bash", tool_call_id="call_1", outputs_path=str(tmp_path), storage_subdir="sub")
    assert path is not None
    owned_by_other_writer = storage_dir / ".tool-output-collision.tmp"
    owned_by_other_writer.write_text("Other writer's pending output", encoding="utf-8")
    published = storage_dir / path.rsplit("/", 1)[1]
    monkeypatch.setattr(mw, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="collision")), raising=False)

    result = mw._externalize(content, tool_name="bash", tool_call_id="call_1", outputs_path=str(tmp_path), storage_subdir="sub")

    assert result is None
    assert set(storage_dir.iterdir()) == {owned_by_other_writer, published}
    assert owned_by_other_writer.read_text(encoding="utf-8") == "Other writer's pending output"
    assert published.read_text(encoding="utf-8") == "Previous complete output"
