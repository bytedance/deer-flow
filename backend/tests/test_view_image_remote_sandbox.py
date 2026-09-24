import asyncio
import base64
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.tools.builtins.view_image_tool import view_image_tool

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
STALE_SAME_SIZE_PNG_BYTES = PNG_BYTES[:-1] + bytes([PNG_BYTES[-1] ^ 1])
_E2BFileNotFound = type(
    "FileNotFoundException",
    (Exception,),
    {"__module__": "e2b.filesystem.filesystem"},
)


class _RemoteSandbox:
    def __init__(self, image_bytes: bytes, *, sandbox_id: str = "remote-1") -> None:
        self.id = sandbox_id
        self.image_bytes = image_bytes
        self.downloads: list[str] = []
        self.released_scopes: list[str] = []

    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.image_bytes

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)


class _FailingRemoteSandbox(_RemoteSandbox):
    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        raise OSError("remote download failed")


class _MissingRemoteSandbox(_RemoteSandbox):
    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        try:
            raise _E2BFileNotFound("not found")
        except _E2BFileNotFound as error:
            raise OSError(f"Failed to download file '{path}' from sandbox: not found") from error


class _BlockingRemoteSandbox(_RemoteSandbox):
    def __init__(self, image_bytes: bytes, *, sandbox_id: str = "remote-1") -> None:
        super().__init__(image_bytes, sandbox_id=sandbox_id)
        self.download_started = threading.Event()
        self.allow_download = threading.Event()

    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        self.download_started.set()
        assert self.allow_download.wait(timeout=5)
        return self.image_bytes


class _Provider:
    def __init__(self, sandbox: _RemoteSandbox | None) -> None:
        self.sandbox = sandbox
        self.acquire_calls: list[tuple[str | None, str | None]] = []
        self.release_calls: list[str] = []

    def acquire(self, thread_id=None, *, user_id=None):
        self.acquire_calls.append((thread_id, user_id))
        raise AssertionError("view_image must not acquire a replacement sandbox")

    def get(self, sandbox_id: str):
        if self.sandbox is None:
            return None
        return self.sandbox if sandbox_id == self.sandbox.id else None

    def release(self, sandbox_id: str) -> None:
        self.release_calls.append(sandbox_id)


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


def _image_metadata(
    actual_path: Path,
    image_bytes: bytes,
    *,
    source_sandbox_id: str | None = None,
    include_digest: bool = True,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "mime_type": "image/png",
        "size": len(image_bytes),
        "actual_path": str(actual_path),
    }
    if include_digest:
        metadata["sha256"] = hashlib.sha256(image_bytes).hexdigest()
    if source_sandbox_id is not None:
        metadata["source_sandbox_id"] = source_sandbox_id
    return metadata


def _make_runtime(
    thread_data: dict[str, str],
    *,
    sandbox_id: str = "remote-1",
    viewed_images: dict[str, dict[str, object]] | None = None,
) -> SimpleNamespace:
    state: dict[str, object] = {
        "thread_data": thread_data,
        "sandbox": {"sandbox_id": sandbox_id},
    }
    if viewed_images is not None:
        state["viewed_images"] = viewed_images
    return SimpleNamespace(
        state=state,
        context={"thread_id": "thread-1"},
        config={},
    )


def _make_model_request(state: dict) -> ModelRequest:
    assistant = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "view_image",
                "id": "call-view-image",
                "args": {"image_path": "/mnt/user-data/outputs/plot.png"},
            }
        ],
    )
    messages = [
        assistant,
        ToolMessage(content="Successfully read image", tool_call_id="call-view-image"),
    ]
    return ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
        messages=messages,
        system_message=None,
        tool_choice=None,
        tools=[],
        response_format=None,
        state={"messages": messages, **state},
        runtime=MagicMock(),
        model_settings={},
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


def _image_block_count(blocks: list[str | dict]) -> int:
    return sum(1 for block in blocks if isinstance(block, dict) and block.get("type") == "image_url")


def test_view_image_reads_active_sandbox_when_host_mirror_is_missing(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    sandbox = _RemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
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
    assert viewed["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert viewed["source_sandbox_id"] == sandbox.id
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]
    assert provider.acquire_calls == []


def test_view_image_prefers_active_sandbox_over_stale_host_mirror(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    remote_bytes = PNG_BYTES + b"remote-version"
    sandbox = _RemoteSandbox(remote_bytes)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-stale",
    )

    assert _message_content(result) == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["size"] == len(remote_bytes)
    assert viewed["sha256"] == hashlib.sha256(remote_bytes).hexdigest()
    assert viewed["source_sandbox_id"] == sandbox.id
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]
    assert provider.acquire_calls == []


def test_view_image_falls_back_to_host_when_saved_sandbox_has_no_live_client(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    provider = _Provider(None)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-host-fallback",
    )

    assert _message_content(result) == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["size"] == len(PNG_BYTES)
    assert viewed["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert "source_sandbox_id" not in viewed
    assert provider.acquire_calls == []


def test_view_image_does_not_fall_back_after_live_sandbox_download_failure(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _FailingRemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )

    previous = {
        "/mnt/user-data/outputs/plot.png": _image_metadata(
            host_path,
            PNG_BYTES,
            source_sandbox_id="remote-old",
        )
    }
    result = view_image_tool.func(
        runtime=_make_runtime(thread_data, viewed_images=previous),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-live-failure",
    )

    assert _message_content(result).startswith("Error reading image file:")
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]
    assert provider.acquire_calls == []


def test_view_image_recovers_verified_host_copy_when_replacement_sandbox_lacks_file(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES, sandbox_id="remote-new")
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    previous = {
        "/mnt/user-data/outputs/plot.png": _image_metadata(
            host_path,
            PNG_BYTES,
            source_sandbox_id="remote-old",
        )
    }

    result = view_image_tool.func(
        runtime=_make_runtime(
            thread_data,
            sandbox_id=sandbox.id,
            viewed_images=previous,
        ),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-replacement-host-fallback",
    )

    assert _message_content(result) == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/outputs/plot.png"]
    assert viewed["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert "source_sandbox_id" not in viewed
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_view_image_rejects_same_size_stale_host_copy_after_replacement(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(STALE_SAME_SIZE_PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES, sandbox_id="remote-new")
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    previous = {
        "/mnt/user-data/outputs/plot.png": _image_metadata(
            host_path,
            PNG_BYTES,
            source_sandbox_id="remote-old",
        )
    }

    result = view_image_tool.func(
        runtime=_make_runtime(
            thread_data,
            sandbox_id=sandbox.id,
            viewed_images=previous,
        ),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-stale-host-rejected",
    )

    assert _message_content(result) == "Error: Image file not found: /mnt/user-data/outputs/plot.png"
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_view_image_same_generation_missing_file_stays_fail_closed(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    previous = {
        "/mnt/user-data/outputs/plot.png": _image_metadata(
            host_path,
            PNG_BYTES,
            source_sandbox_id=sandbox.id,
        )
    }

    result = view_image_tool.func(
        runtime=_make_runtime(thread_data, viewed_images=previous),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-same-generation-missing",
    )

    assert _message_content(result) == "Error: Image file not found: /mnt/user-data/outputs/plot.png"
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_view_image_legacy_metadata_does_not_authorize_cross_generation_fallback(tmp_path, monkeypatch):
    thread_data = _make_thread_data(tmp_path)
    host_path = Path(thread_data["outputs_path"]) / "plot.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES, sandbox_id="remote-new")
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    previous = {
        "/mnt/user-data/outputs/plot.png": _image_metadata(
            host_path,
            PNG_BYTES,
            source_sandbox_id="remote-old",
            include_digest=False,
        )
    }

    result = view_image_tool.func(
        runtime=_make_runtime(
            thread_data,
            sandbox_id=sandbox.id,
            viewed_images=previous,
        ),
        image_path="/mnt/user-data/outputs/plot.png",
        tool_call_id="tc-legacy-no-digest",
    )

    assert _message_content(result) == "Error: Image file not found: /mnt/user-data/outputs/plot.png"


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
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                tmp_path / "missing-host-copy.png",
                PNG_BYTES,
                source_sandbox_id=sandbox.id,
            )
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
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                host_path,
                remote_bytes,
                source_sandbox_id=sandbox.id,
            )
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_bytes_from_blocks(blocks) == remote_bytes
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_middleware_falls_back_to_host_when_saved_sandbox_has_no_live_client(tmp_path, monkeypatch):
    host_path = tmp_path / "synced-host-copy.png"
    host_path.write_bytes(PNG_BYTES)
    provider = _Provider(None)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": "remote-1"},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                host_path,
                PNG_BYTES,
                source_sandbox_id="remote-old",
            )
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_bytes_from_blocks(blocks) == PNG_BYTES
    assert provider.acquire_calls == []


def test_middleware_uses_verified_host_copy_after_sandbox_replacement(tmp_path, monkeypatch):
    host_path = tmp_path / "synced-old-image.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES, sandbox_id="remote-new")
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": sandbox.id},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                host_path,
                PNG_BYTES,
                source_sandbox_id="remote-old",
            )
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_bytes_from_blocks(blocks) == PNG_BYTES
    assert sandbox.downloads == []


def test_middleware_rejects_same_size_stale_host_after_sandbox_replacement(tmp_path, monkeypatch):
    host_path = tmp_path / "stale-same-size.png"
    host_path.write_bytes(STALE_SAME_SIZE_PNG_BYTES)
    sandbox = _MissingRemoteSandbox(PNG_BYTES, sandbox_id="remote-new")
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": sandbox.id},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                host_path,
                PNG_BYTES,
                source_sandbox_id="remote-old",
            )
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_block_count(blocks) == 0
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_middleware_same_generation_failure_does_not_use_host_copy(tmp_path, monkeypatch):
    host_path = tmp_path / "matching-host-copy.png"
    host_path.write_bytes(PNG_BYTES)
    sandbox = _FailingRemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    state = {
        "sandbox": {"sandbox_id": sandbox.id},
        "viewed_images": {
            "/mnt/user-data/outputs/plot.png": _image_metadata(
                host_path,
                PNG_BYTES,
                source_sandbox_id=sandbox.id,
            )
        },
    }

    blocks = ViewImageMiddleware()._create_image_details_message(state)

    assert _image_block_count(blocks) == 0
    assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]


def test_middleware_sync_read_finishes_before_lease_release(tmp_path, monkeypatch):
    sandbox = _BlockingRemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "run-owner",
        sandbox.id,
        thread_id="thread-1",
        user_id="user-1",
    )
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    request = _make_model_request(
        {
            "sandbox": {"sandbox_id": sandbox.id},
            "viewed_images": {
                "/mnt/user-data/outputs/plot.png": _image_metadata(
                    tmp_path / "missing-host-copy.png",
                    PNG_BYTES,
                    source_sandbox_id=sandbox.id,
                )
            },
        }
    )
    handler_called = threading.Event()
    invocation_errors: list[BaseException] = []

    def handler(_prepared: ModelRequest) -> AIMessage:
        handler_called.set()
        return AIMessage(content="ok")

    def invoke_under_lease() -> None:
        try:
            ViewImageMiddleware().wrap_model_call(request, handler)
        except BaseException as error:
            invocation_errors.append(error)
        finally:
            manager.release("run-owner")

    worker = threading.Thread(target=invoke_under_lease)
    try:
        worker.start()
        assert sandbox.download_started.wait(timeout=1)

        assert worker.is_alive()
        assert not handler_called.is_set()
        assert provider.release_calls == []
        assert sandbox.released_scopes == []

        sandbox.allow_download.set()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert invocation_errors == []
        assert handler_called.is_set()
        assert provider.release_calls == [sandbox.id]
        assert sandbox.released_scopes == ["run-owner"]
    finally:
        sandbox.allow_download.set()
        worker.join(timeout=2)
        if manager.binding_for("run-owner") is not None:
            manager.release("run-owner")
        manager.close()


@pytest.mark.asyncio
async def test_middleware_cancellation_drains_sandbox_download_before_lease_release(tmp_path, monkeypatch):
    sandbox = _BlockingRemoteSandbox(PNG_BYTES)
    provider = _Provider(sandbox)
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "run-owner",
        sandbox.id,
        thread_id="thread-1",
        user_id="user-1",
    )
    monkeypatch.setattr(
        "deerflow.sandbox.sandbox_provider.get_sandbox_provider",
        lambda: provider,
    )
    request = _make_model_request(
        {
            "sandbox": {"sandbox_id": sandbox.id},
            "viewed_images": {
                "/mnt/user-data/outputs/plot.png": _image_metadata(
                    tmp_path / "missing-host-copy.png",
                    PNG_BYTES,
                    source_sandbox_id=sandbox.id,
                )
            },
        }
    )
    handler_called = False

    async def handler(_prepared: ModelRequest) -> AIMessage:
        nonlocal handler_called
        handler_called = True
        return AIMessage(content="unexpected")

    async def invoke_under_lease():
        try:
            return await ViewImageMiddleware().awrap_model_call(request, handler)
        finally:
            await manager.release_async("run-owner")

    task = asyncio.create_task(invoke_under_lease())
    try:
        assert await asyncio.to_thread(sandbox.download_started.wait, 1)

        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        assert provider.release_calls == []
        assert sandbox.released_scopes == []

        sandbox.allow_download.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert handler_called is False
        assert provider.release_calls == [sandbox.id]
        assert sandbox.released_scopes == ["run-owner"]
    finally:
        sandbox.allow_download.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        manager.close()
