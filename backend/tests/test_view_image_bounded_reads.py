"""Host image reads must stay bounded when a file grows after its size check."""

import base64
import builtins
import hashlib
import importlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.agents.middlewares import view_image_middleware

view_image_module = importlib.import_module("deerflow.tools.builtins.view_image_tool")
PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.mark.parametrize("reader", ["tool", "recovery", "middleware"])
@pytest.mark.parametrize("grow", [False, True], ids=["exact-limit", "grows-after-stat"])
def test_host_image_reads_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str, grow: bool) -> None:
    thread_data = {}
    for name in ("workspace", "uploads", "outputs"):
        directory = tmp_path / name
        directory.mkdir()
        thread_data[f"{name}_path"] = str(directory)
    image_path = tmp_path / "uploads" / "sample.png"
    image_path.write_bytes(PNG_BYTES)
    limit = len(PNG_BYTES)
    monkeypatch.setattr(view_image_module, "_MAX_IMAGE_BYTES", limit)
    monkeypatch.setattr(view_image_middleware, "_MAX_IMAGE_BYTES", limit)
    original_open = builtins.open
    reads = []

    class TrackedReader:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def read(self, size=-1):
            # Append only after the production stat check and before its real read.
            if grow:
                with original_open(image_path, "ab") as writer:
                    writer.write(b"x" * (limit * 4))
            data = self.file.read(size)
            reads.append((size, len(data)))
            return data

    def tracked_open(file, mode="r", *args, **kwargs):
        opened = original_open(file, mode, *args, **kwargs)
        if mode == "rb" and Path(file) == image_path:
            return TrackedReader(opened)
        return opened

    monkeypatch.setattr(builtins, "open", tracked_open)
    monkeypatch.setattr(io, "open", tracked_open)
    digest = hashlib.sha256(PNG_BYTES).hexdigest()

    if reader == "tool":
        runtime = SimpleNamespace(state={"thread_data": thread_data}, context={"thread_id": "thread-1"}, config={})
        result = view_image_module.view_image_tool.func(
            runtime=runtime,
            image_path="/mnt/user-data/uploads/sample.png",
            tool_call_id="bounded-read",
        )
        if grow:
            assert "Image file changed during read" in result.update["messages"][0].content
            assert "viewed_images" not in result.update
        else:
            assert result.update["messages"][0].content == "Successfully read image"
    elif reader == "recovery":
        result = view_image_module._read_verified_host_copy(image_path, expected_size=limit, expected_sha256=digest)
        assert result == (None if grow else PNG_BYTES)
    else:
        result = view_image_middleware.ViewImageMiddleware._read_host_image_as_data_url(str(image_path), "image/png", limit, digest)
        expected = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        assert result == (None if grow else expected)

    assert len(reads) == 1
    requested, consumed = reads[0]
    assert consumed <= limit + 1
    assert 0 < requested <= limit + 1
