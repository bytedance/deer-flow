import asyncio
import base64
import threading
from pathlib import Path

import pytest
from langchain.tools import ToolRuntime

from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.tools.builtins.view_image_tool import view_image_tool

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class _BlockingRemoteSandbox:
    id = "remote-1"

    def __init__(self) -> None:
        self.download_started = threading.Event()
        self.allow_download = threading.Event()
        self.downloads: list[str] = []
        self.released_scopes: list[str] = []

    def download_file(self, path: str) -> bytes:
        self.downloads.append(path)
        self.download_started.set()
        assert self.allow_download.wait(timeout=5)
        return PNG_BYTES

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)


class _Provider:
    def __init__(self, sandbox: _BlockingRemoteSandbox) -> None:
        self.sandbox = sandbox
        self.release_calls: list[str] = []

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == self.sandbox.id else None

    def release(self, sandbox_id: str) -> None:
        self.release_calls.append(sandbox_id)


def _thread_data(tmp_path: Path) -> dict[str, str]:
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


def _runtime(tmp_path: Path, sandbox_id: str) -> ToolRuntime:
    return ToolRuntime(
        state={
            "thread_data": _thread_data(tmp_path),
            "sandbox": {"sandbox_id": sandbox_id},
        },
        context={"thread_id": "thread-1"},
        config={"configurable": {"thread_id": "thread-1"}},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="tc-tool-cancel",
        store=None,
    )


@pytest.mark.asyncio
async def test_view_image_ainvoke_drains_download_before_lease_release(tmp_path, monkeypatch):
    sandbox = _BlockingRemoteSandbox()
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
    runtime = _runtime(tmp_path, sandbox.id)

    async def invoke_under_lease():
        try:
            return await view_image_tool.ainvoke(
                {
                    "args": {
                        "runtime": runtime,
                        "image_path": "/mnt/user-data/outputs/plot.png",
                    },
                    "name": "view_image",
                    "type": "tool_call",
                    "id": "tc-tool-cancel",
                }
            )
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

        assert sandbox.downloads == ["/mnt/user-data/outputs/plot.png"]
        assert provider.release_calls == [sandbox.id]
        assert sandbox.released_scopes == ["run-owner"]
    finally:
        sandbox.allow_download.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        if manager.binding_for("run-owner") is not None:
            await manager.release_async("run-owner")
        manager.close()
