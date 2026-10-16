import base64
import hashlib
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.storage import BlobRef, BlobWriteError
from deerflow.tools.builtins.view_image_tool import view_image_tool

view_image_module = importlib.import_module("deerflow.tools.builtins.view_image_tool")

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

# Minimal 1x1 transparent GIF (starts with the "GIF89a" magic bytes).
GIF_BYTES = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _make_thread_data(tmp_path: Path) -> dict[str, str]:
    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    workspace = user_data / "workspace"
    uploads = user_data / "uploads"
    outputs = user_data / "outputs"
    for directory in (workspace, uploads, outputs):
        directory.mkdir(parents=True)

    return {
        "workspace_path": str(workspace),
        "uploads_path": str(uploads),
        "outputs_path": str(outputs),
    }


def _make_runtime(thread_data: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        state={"thread_data": thread_data},
        context={"thread_id": "thread-1"},
        config={},
    )


def _message_content(result) -> str:
    return result.update["messages"][0].content


def test_view_image_rejects_external_absolute_path(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(PNG_BYTES)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path=str(outside_image),
        tool_call_id="tc-external",
    )

    assert "Only image paths under /mnt/user-data" in _message_content(result)
    assert "viewed_images" not in result.update


def test_view_image_reads_virtual_uploads_path(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "sample.png"
    image_path.write_bytes(PNG_BYTES)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/sample.png",
        tool_call_id="tc-uploads",
    )

    assert _message_content(result) == "Successfully read image"
    viewed_image = result.update["viewed_images"]["/mnt/user-data/uploads/sample.png"]
    assert viewed_image["mime_type"] == "image/png"
    assert viewed_image["size"] == len(PNG_BYTES)
    assert viewed_image["actual_path"] == str(image_path)


def test_view_image_persists_blob_ref_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "shared.png"
    image_path.write_bytes(PNG_BYTES)
    calls: list[dict] = []

    class RecordingStore:
        def put_bytes(self, data: bytes, **kwargs) -> BlobRef:
            calls.append({"data": data, **kwargs})
            return BlobRef(
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                kind=kwargs["kind"],
                content_type=kwargs["content_type"],
            )

    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: RecordingStore())

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/shared.png",
        tool_call_id="tc-shared",
    )

    assert _message_content(result) == "Successfully read image"
    metadata = result.update["viewed_images"]["/mnt/user-data/uploads/shared.png"]
    assert metadata["blob_ref"] == {
        "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
        "size": len(PNG_BYTES),
        "kind": "viewed-image",
        "content_type": "image/png",
    }
    assert calls == [
        {
            "data": PNG_BYTES,
            "kind": "viewed-image",
            "content_type": "image/png",
            "thread_id": "thread-1",
        }
    ]


def test_view_image_does_not_claim_success_when_configured_blob_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "shared.png"
    image_path.write_bytes(PNG_BYTES)

    class FailingStore:
        def put_bytes(self, data: bytes, **kwargs) -> BlobRef:
            raise BlobWriteError("backend detail must not reach the model")

    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: FailingStore())

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/shared.png",
        tool_call_id="tc-shared-failure",
    )

    assert _message_content(result) == "Error: Failed to persist image in shared blob storage"
    assert "viewed_images" not in result.update
    assert "backend detail" not in _message_content(result)


def test_view_image_returns_generic_error_when_blob_store_factory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "shared.png"
    image_path.write_bytes(PNG_BYTES)

    def fail_to_resolve_store():
        raise ValueError("misconfigured backend detail must not reach the model")

    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", fail_to_resolve_store)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/shared.png",
        tool_call_id="tc-shared-factory-failure",
    )

    assert _message_content(result) == "Error: Failed to persist image in shared blob storage"
    assert "viewed_images" not in result.update
    assert "misconfigured backend detail" not in _message_content(result)


def test_view_image_returns_generic_error_when_backend_leaks_raw_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "shared.png"
    image_path.write_bytes(PNG_BYTES)

    class FailingStore:
        def put_bytes(self, data: bytes, **kwargs) -> BlobRef:
            raise RuntimeError("raw SDK detail must not reach the model")

    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: FailingStore())

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/shared.png",
        tool_call_id="tc-shared-raw-failure",
    )

    assert _message_content(result) == "Error: Failed to persist image in shared blob storage"
    assert "viewed_images" not in result.update
    assert "raw SDK detail" not in _message_content(result)


def test_view_image_reads_gif(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "animation.gif"
    image_path.write_bytes(GIF_BYTES)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/animation.gif",
        tool_call_id="tc-gif",
    )

    assert _message_content(result) == "Successfully read image"
    viewed_image = result.update["viewed_images"]["/mnt/user-data/uploads/animation.gif"]
    assert viewed_image["mime_type"] == "image/gif"
    assert viewed_image["size"] == len(GIF_BYTES)


def test_view_image_rejects_spoofed_extension(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "not-really.png"
    image_path.write_bytes(b"not an image")

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/not-really.png",
        tool_call_id="tc-spoofed",
    )

    assert "contents do not match" in _message_content(result)
    assert "viewed_images" not in result.update


def test_view_image_rejects_mismatched_magic_bytes(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "jpeg-named-png.png"
    image_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/jpeg-named-png.png",
        tool_call_id="tc-mismatch",
    )

    assert "file extension indicates image/png" in _message_content(result)
    assert "viewed_images" not in result.update


def test_view_image_rejects_oversized_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "sample.png"
    image_path.write_bytes(PNG_BYTES)
    monkeypatch.setattr(view_image_module, "_MAX_IMAGE_BYTES", len(PNG_BYTES) - 1)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/sample.png",
        tool_call_id="tc-oversized",
    )

    assert "Image file is too large" in _message_content(result)
    assert "viewed_images" not in result.update


def test_view_image_sanitizes_read_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    thread_data = _make_thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "sample.png"
    image_path.write_bytes(PNG_BYTES)

    def _open(*args, **kwargs):
        raise PermissionError(f"permission denied: {image_path}")

    monkeypatch.setattr("builtins.open", _open)

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/sample.png",
        tool_call_id="tc-read-error",
    )

    message = _message_content(result)
    assert "Error reading image file" in message
    assert str(image_path) not in message
    assert str(Path(thread_data["uploads_path"])) not in message
    assert "/mnt/user-data/uploads/sample.png" in message
    assert "viewed_images" not in result.update


@pytest.mark.skipif(os.name == "nt", reason="symlink semantics differ on Windows")
def test_view_image_rejects_uploads_symlink_escape(tmp_path: Path) -> None:
    thread_data = _make_thread_data(tmp_path)
    outside_image = tmp_path / "outside-target.png"
    outside_image.write_bytes(PNG_BYTES)

    link_path = Path(thread_data["uploads_path"]) / "escape.png"
    try:
        link_path.symlink_to(outside_image)
    except OSError as exc:
        pytest.skip(f"symlink creation failed: {exc}")

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/uploads/escape.png",
        tool_call_id="tc-symlink",
    )

    assert "path traversal" in _message_content(result)
    assert "viewed_images" not in result.update
