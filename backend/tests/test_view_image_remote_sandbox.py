import base64
from pathlib import Path
from types import SimpleNamespace

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.tools.builtins.view_image_tool import view_image_tool

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class _RemoteSandbox:
    id = "remote-1"

    def __init__(self, image_bytes: bytes) -> None:
        self.image_bytes = image_bytes
        self.downloads: list[str] = []

    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.image_bytes


class _Provider:
    def __init__(self, sandbox: _RemoteSandbox) -> None:
        self.sandbox = sandbox

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == self.sandbox.id else None


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
        state={
            "thread_data": thread_data,
            "sandbox": {"sandbox_id": "remote-1"},
        },
        context={"thread_id": "thread-1"},
        config={},
    )


def _message_content(result) -> str:
    return result.update["messages"][0].content


def _image_bytes_from_blocks(blocks: list[str | dict]) -> bytes:
    image_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "image_url"]
    assert len(image_blocks) == 1
    data_url = image_blocks[0]["image_url"]["url"]
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    return base64.b64decode(data_url[len(prefix) :])


def test_view_image_reads_active_sandbox_when_host_mirror_is_missing(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    sandbox = _RemoteSandbox(PNG_BYTES)
    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized",
        lambda runtime: sandbox,
    )
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    assert not host_path.exists()

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-remote",
    )

    assert _message_content(result) == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["size"] == len(PNG_BYTES)
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_view_image_prefers_active_sandbox_over_stale_host_mirror(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    remote_bytes = PNG_BYTES + b"remote-version"
    sandbox = _RemoteSandbox(remote_bytes)
    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized",
        lambda runtime: sandbox,
    )

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-stale",
    )

    assert _message_content(result) == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["size"] == len(remote_bytes)
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_middleware_injects_image_from_active_sandbox_without_host_copy(tmp_path, monkeypatch):
    sandbox = _RemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": sandbox.id},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": {
                "mime_type": "image/png",
                "size": len(PNG_BYTES),
                "actual_path": str(tmp_path / "missing-host-copy.png"),
            }
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_bytes_from_blocks(blocks) == PNG_BYTES
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_middleware_prefers_active_sandbox_over_stale_host_mirror(tmp_path, monkeypatch):
    host_path = tmp_path / "stale-host-copy.png"
    host_path.write_bytes(PNG_BYTES)
    remote_bytes = PNG_BYTES + b"remote-version"
    sandbox = _RemoteSandbox(remote_bytes)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": sandbox.id},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": {
                "mime_type": "image/png",
                "size": len(remote_bytes),
                "actual_path": str(host_path),
            }
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_bytes_from_blocks(blocks) == remote_bytes
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]
