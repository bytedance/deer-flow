"""Caller limits must reach the provider before image bytes are buffered."""

import errno
import io
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
from deerflow.community.boxlite.box import BoxliteBox
from deerflow.community.e2b_sandbox.e2b_sandbox import E2BSandbox
from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox
from deerflow.community.tenki.sandbox import TenkiSandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.tools.builtins.view_image_tool import _MAX_IMAGE_BYTES, _view_image_authorized

PATH = "/mnt/user-data/outputs/image.png"


class Stream:
    def __init__(self, chunks, error=None):
        self.chunks = iter(chunks)
        self.error = error
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        chunk = next(self.chunks)
        self.consumed += len(chunk)
        if self.error:
            raise self.error
        return chunk

    def close(self):
        self.closed = True


def provider(kind, stream):
    if kind == "e2b":
        return E2BSandbox("remote", SimpleNamespace(files=SimpleNamespace(read=Mock(return_value=stream))))
    if kind == "aio":
        box = object.__new__(AioSandbox)
        box._lock = threading.Lock()
        box._client = SimpleNamespace(file=SimpleNamespace(download_file=Mock(return_value=stream)))
        return box
    if kind == "opensandbox":
        box = object.__new__(OpenSandboxSandbox)
        files = SimpleNamespace(read_bytes_stream=Mock(return_value=stream))
        box._file_op = lambda operation: operation(files)
        return box
    box = object.__new__(TenkiSandbox)
    box._lock = threading.Lock()
    box._closed = False
    box._sandbox = SimpleNamespace(fs=SimpleNamespace(read_stream=Mock(return_value=stream)))
    box._resolve_path = lambda path: path
    box._note_failure = Mock()
    return box


@pytest.mark.parametrize("kind", ["aio", "e2b", "opensandbox", "tenki"])
@pytest.mark.parametrize("size", [0, 4, 5, 9])
def test_provider_limit_stops_stream_and_closes(kind, size):
    stream = Stream([b"x"] * size)
    box = provider(kind, stream)
    if size > 4:
        with pytest.raises(OSError) as error:
            box.download_file(PATH, max_bytes=4)
        assert error.value.errno == errno.EFBIG
    else:
        assert box.download_file(PATH, max_bytes=4) == b"x" * size
    assert stream.consumed == min(size, 5)
    assert stream.closed


@pytest.mark.parametrize("kind", ["aio", "e2b", "opensandbox", "tenki"])
@pytest.mark.parametrize("error", [OSError("transport"), KeyboardInterrupt()])
def test_provider_closes_stream_on_error_or_interruption(kind, error):
    stream = Stream([b"x"], error)
    with pytest.raises(type(error)):
        provider(kind, stream).download_file(PATH, max_bytes=4)
    assert stream.closed


def test_tool_rejects_21_mib_without_consuming_the_complete_stream(tmp_path, monkeypatch):
    stream = Stream([b"x" * 65536] * (21 * 16))
    box = provider("aio", stream)
    thread_data = {f"{name}_path": str(tmp_path / name) for name in ("workspace", "uploads", "outputs")}
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda _: box))
    runtime = SimpleNamespace(state={"thread_data": thread_data, "sandbox": {"sandbox_id": "remote"}}, context={"thread_id": "thread"}, config={})
    result = _view_image_authorized(runtime, PATH, "call")
    assert "Error" in result.update["messages"][0].content
    assert "viewed_images" not in result.update
    assert stream.consumed <= _MAX_IMAGE_BYTES + 65536
    assert stream.closed


def test_e2b_bounded_read_never_retries_buffered_sdk():
    read = Mock(side_effect=TypeError("stream unavailable"))
    box = E2BSandbox("remote", SimpleNamespace(files=SimpleNamespace(read=read)))
    with pytest.raises(OSError):
        box.download_file(PATH, max_bytes=4)
    assert read.call_count == 1
    assert read.call_args.kwargs == {"format": "stream"}


def test_local_growth_after_stat_is_still_bounded(monkeypatch):
    box = object.__new__(LocalSandbox)
    box._resolve_path = lambda path: path
    stream = io.BytesIO(b"x" * 100)
    requests = []

    class Reader(io.BytesIO):
        def read(self, size=-1):
            requests.append(size)
            return stream.read(size)

    monkeypatch.setattr("os.path.getsize", lambda _: 4)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: Reader())
    with pytest.raises(OSError) as error:
        box.download_file(PATH, max_bytes=4)
    assert error.value.errno == errno.EFBIG
    assert requests == [5]
    assert stream.tell() == 5


@pytest.mark.parametrize("kind", ["aio", "e2b", "opensandbox", "tenki", "local", "boxlite"])
@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_invalid_limit_rejected_before_io(kind, limit):
    box = object.__new__({"local": LocalSandbox, "boxlite": BoxliteBox}[kind]) if kind in {"local", "boxlite"} else provider(kind, Stream([]))
    with pytest.raises(ValueError):
        box.download_file(PATH, max_bytes=limit)


@pytest.mark.parametrize("size", [0, 4, 5, 100])
def test_boxlite_bounds_actual_shell_read(tmp_path, size):
    git = shutil.which("git")
    shell = str(Path(git).parent.parent / "bin" / "bash.exe") if os.name == "nt" and git else shutil.which("sh")
    if not shell or not Path(shell).exists():
        pytest.skip("POSIX shell is required for the BoxLite transport probe")
    image = tmp_path / "image ; quoted.png"
    image.write_bytes(b"x" * size)
    box = object.__new__(BoxliteBox)
    outputs = []

    def run(script):
        script = script.replace(shlex.quote(PATH), shlex.quote(image.as_posix()))
        if os.name == "nt":
            script = "export PATH=/usr/bin:/bin\n" + script
        result = subprocess.run([shell, "-c", script], capture_output=True, text=True, timeout=10)
        outputs.append(result.stdout)
        return SimpleNamespace(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)

    box._sh = run
    if size > 4:
        with pytest.raises(OSError) as error:
            box.download_file(PATH, max_bytes=4)
        assert error.value.errno == errno.EFBIG
    else:
        assert box.download_file(PATH, max_bytes=4) == b"x" * size
    assert len(outputs[0]) < 80
    image.unlink()
    with pytest.raises(OSError):
        box.download_file(PATH, max_bytes=4)


@pytest.mark.parametrize("source", ["remote", "old-remote"])
def test_model_injection_limits_remote_download(tmp_path, monkeypatch, source):
    stream = Stream([b"x" * 65536] * (21 * 16))
    box = provider("aio", stream)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda _: box))
    result = ViewImageMiddleware._read_image_as_data_url({"sandbox": {"sandbox_id": "remote"}}, PATH, "", "image/png", 1, "digest", source)
    assert result is None
    assert stream.consumed <= _MAX_IMAGE_BYTES + 65536
    assert stream.closed


def test_custom_provider_without_limit_fails_closed(tmp_path, monkeypatch):
    calls = []

    class Legacy:
        def download_file(self, path):
            calls.append(path)
            return b"legacy"

    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda _: Legacy()))
    runtime = SimpleNamespace(
        state={"thread_data": {f"{name}_path": str(tmp_path / name) for name in ("workspace", "uploads", "outputs")}, "sandbox": {"sandbox_id": "remote"}},
        context={"thread_id": "thread"},
        config={},
    )
    result = _view_image_authorized(runtime, PATH, "call")
    assert "Error" in result.update["messages"][0].content
    assert calls == []


@pytest.mark.parametrize("kind", ["aio", "e2b", "opensandbox", "tenki"])
@pytest.mark.parametrize("max_bytes", [None, 100 * 1024 * 1024 + 1])
def test_caller_cannot_raise_default_provider_ceiling(kind, max_bytes):
    from deerflow.sandbox.download import DEFAULT_DOWNLOAD_LIMIT

    class OversizedChunk:
        def __len__(self):
            return DEFAULT_DOWNLOAD_LIMIT + 1

    stream = Stream([OversizedChunk(), b"unread"])
    with pytest.raises(OSError) as error:
        provider(kind, stream).download_file(PATH, max_bytes=max_bytes)
    assert error.value.errno == errno.EFBIG
    assert str(DEFAULT_DOWNLOAD_LIMIT) in str(error.value)
    assert stream.consumed == DEFAULT_DOWNLOAD_LIMIT + 1
    assert stream.closed


@pytest.mark.parametrize("max_bytes", [None, 100 * 1024 * 1024 + 1])
def test_local_caller_cannot_raise_default_provider_ceiling(monkeypatch, max_bytes):
    from deerflow.sandbox.download import DEFAULT_DOWNLOAD_LIMIT

    box = object.__new__(LocalSandbox)
    box._resolve_path = lambda path: path
    monkeypatch.setattr("os.path.getsize", lambda _: DEFAULT_DOWNLOAD_LIMIT + 1)
    read = Mock()
    monkeypatch.setattr("builtins.open", read)
    with pytest.raises(OSError) as error:
        box.download_file(PATH, max_bytes=max_bytes)
    assert error.value.errno == errno.EFBIG
    read.assert_not_called()
