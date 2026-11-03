"""Snapshot scope, provider-error and custom-read compatibility regressions."""

import asyncio
import hashlib
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.read_before_write_middleware import READ_MARK_KEY, ReadBeforeWriteMiddleware
from deerflow.sandbox import tools
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.read_snapshot import capture_read_snapshot, read_snapshot_requested, record_read_snapshot


def _request(path, args=None, call_id="read"):
    state = {"sandbox": {"sandbox_id": "remote-snapshot"}, "messages": []}
    runtime = SimpleNamespace(state=state, context={"thread_id": "snapshot-tests", "user_id": "test-user"})
    return ToolCallRequest(tool_call={"name": "read_file", "args": {"path": path, **(args or {})}, "id": call_id}, tool=None, state=state, runtime=runtime)


@pytest.mark.parametrize("line_range", [{}, {"start_line": 1, "end_line": 1}, {"start_line": 99}])
@pytest.mark.parametrize("error", ["Error: file not found or unreadable", "Error: " + "long remote failure " * 4000], ids=["ordinary-error", "over-output-budget-error"])
@pytest.mark.parametrize("invocation", ["sync", "async"])
def test_remote_error_string_never_becomes_snapshot_evidence(monkeypatch, line_range, error, invocation):
    sandbox = SimpleNamespace(read_file=lambda path, **kwargs: error)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=300)))
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)

    async def initialize_async(runtime):
        return sandbox

    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize_async)
    request = _request("/remote/report.txt", line_range)
    gate = ReadBeforeWriteMiddleware()

    def result(content):
        # Legacy custom wrappers may retain success on an in-band provider error.
        return ToolMessage(content=content, tool_call_id="read", status="success")

    if invocation == "sync":
        actual = gate.wrap_tool_call(request, lambda req: result(tools.read_file_tool.func(runtime=req.runtime, **req.tool_call["args"])))
    else:

        async def execute(req):
            return result(await tools.read_file_tool.coroutine(runtime=req.runtime, **req.tool_call["args"]))

        actual = asyncio.run(gate.awrap_tool_call(request, execute))
    if len(error) <= 300:
        assert actual.content == error
    else:
        assert actual.content.startswith("Error:")
        assert "[truncated:" in actual.content
        assert len(actual.content) <= 300
    assert READ_MARK_KEY not in actual.additional_kwargs


@pytest.mark.parametrize("view", ["full", "range", "truncated", "formatted", "range-hidden-update", "full-update"])
def test_custom_reader_grants_evidence_only_for_an_observed_complete_version(tmp_path, view):
    path = tmp_path / "custom.txt"
    original = "visible=old\nhidden=old\n"
    path.write_bytes(original.encode())
    args = {"start_line": 1, "end_line": 1} if view.startswith("range") else {}
    request = _request(str(path), args)
    gate = ReadBeforeWriteMiddleware(content_reader=lambda runtime, name: path.read_bytes().decode())

    def read(req):
        content = path.read_bytes().decode()
        if view.startswith("range"):
            content = content.split("\n")[0]
        elif view == "truncated":
            content = content[:7] + "... [truncated]"
        elif view == "formatted":
            content = "File contents:\n" + content
        if view.endswith("update"):
            path.write_bytes(original.replace("hidden=old", "hidden=new").encode())
        return ToolMessage(content=content, tool_call_id="read")

    actual = gate.wrap_tool_call(request, read)
    if view == "full":
        assert actual.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(original.encode()).hexdigest()
    else:
        assert READ_MARK_KEY not in actual.additional_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", ["sync", "async"])
async def test_parallel_first_party_reads_bind_each_result_to_its_own_source(tmp_path, monkeypatch, invocation):
    sources = {"first.txt": "alpha source\n", "second.txt": "header\r\nbeta source\r\n"}
    for name, content in sources.items():
        (tmp_path / name).write_bytes(content.encode())
    sandbox = LocalSandbox("local:parallel-reads", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)

    async def initialize_async(runtime):
        return sandbox

    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize_async)
    barrier = threading.Barrier(2)
    real_read = sandbox.read_file

    def synchronized_read(path, **kwargs):
        content = real_read(path, **kwargs)
        barrier.wait(timeout=5)
        return content

    monkeypatch.setattr(sandbox, "read_file", synchronized_read)
    gate = ReadBeforeWriteMiddleware()

    async def read(name, args):
        request = _request(f"/mnt/user-data/workspace/{name}", args, call_id=name)
        request.runtime.state.update(sandbox={"sandbox_id": sandbox.id}, thread_data={"workspace_path": str(tmp_path)})

        def result(content):
            return ToolMessage(content=content, tool_call_id=name)

        if invocation == "sync":
            return await asyncio.to_thread(
                gate.wrap_tool_call,
                request,
                lambda req: result(tools.read_file_tool.func(runtime=req.runtime, **req.tool_call["args"])),
            )

        async def execute(req):
            return result(await tools.read_file_tool.coroutine(runtime=req.runtime, **req.tool_call["args"]))

        return await gate.awrap_tool_call(request, execute)

    pending = [asyncio.create_task(read("first.txt", {})), asyncio.create_task(read("second.txt", {"start_line": 2}))]
    try:
        first, second = await asyncio.wait_for(asyncio.gather(*pending), 10)
    finally:
        barrier.abort()
        await asyncio.gather(*pending, return_exceptions=True)
    assert first.content == sources["first.txt"]
    assert second.content == "beta source"
    for result, source in ((first, sources["first.txt"]), (second, sources["second.txt"])):
        assert result.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.asyncio
async def test_parallel_to_thread_captures_keep_their_own_source_versions():
    both_started = asyncio.Event()
    release = asyncio.Event()
    started = 0

    async def read(path, content):
        nonlocal started
        with capture_read_snapshot(path) as capture:
            started += 1
            if started == 2:
                both_started.set()
            await release.wait()
            await asyncio.to_thread(record_read_snapshot, path, content, content[:3])
            return capture.snapshot

    pending = [asyncio.create_task(read("/first", "alpha-source")), asyncio.create_task(read("/second", "beta-source"))]
    try:
        await asyncio.wait_for(both_started.wait(), 5)
        release.set()
        first, second = await asyncio.gather(*pending)
    finally:
        release.set()
        await asyncio.gather(*pending, return_exceptions=True)
    assert first.content_hash == hashlib.sha256(b"alpha-source").hexdigest()
    assert second.content_hash == hashlib.sha256(b"beta-source").hexdigest()
    assert first.displayed_content == "alp"
    assert second.displayed_content == "bet"
    assert not read_snapshot_requested("/first")
    assert not read_snapshot_requested("/second")


def test_snapshot_capture_restores_nested_and_failed_scopes():
    with capture_read_snapshot("/outer") as outer:
        with pytest.raises(RuntimeError), capture_read_snapshot("/inner") as inner:
            record_read_snapshot("/outer", "wrong call", "wrong call")
            assert inner.snapshot is None
            raise RuntimeError("read failed")
        assert read_snapshot_requested("/outer")
        assert not read_snapshot_requested("/inner")
        record_read_snapshot("/outer", "complete source", "display")
    assert outer.snapshot.content_hash == hashlib.sha256(b"complete source").hexdigest()
    assert not read_snapshot_requested("/outer")


@pytest.mark.asyncio
async def test_snapshot_capture_is_reset_when_the_read_is_cancelled():
    started = asyncio.Event()
    after_scope = []

    async def read():
        try:
            with capture_read_snapshot("/cancelled"):
                started.set()
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            after_scope.append(read_snapshot_requested("/cancelled"))
            raise

    task = asyncio.create_task(read())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert after_scope == [False]
