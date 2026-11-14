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


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", ["sync", "async"])
@pytest.mark.parametrize(
    "source,args,budget,status",
    [
        ("Error: example file text\n", {}, 50000, "success"),
        ("example ... [truncated: showing 1 of 10 chars] ...", {}, 50000, "success"),
        ("one\n\nthree\n", {"start_line": 2, "end_line": 2}, 50000, "success"),
        ("one\n", {"start_line": 99}, 50000, "error"),
        ("row=data\n" * 200, {}, 300, "partial_success"),
        ("row=data\n" * 200, {"start_line": 2, "end_line": 100}, 300, "partial_success"),
    ],
)
async def test_snapshot_preserves_producer_state_and_original_version(tmp_path, monkeypatch, invocation, source, args, budget, status):
    path = "/mnt/user-data/workspace/report.txt"
    target = tmp_path / "report.txt"
    target.write_bytes(source.encode())
    sandbox = LocalSandbox("snapshot-meta", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=budget)))
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)

    async def initialize_async(runtime):
        return sandbox

    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize_async)
    request = _request(path, args)
    request.runtime.tool_call_id = "read"
    gate = ReadBeforeWriteMiddleware()

    def finish(message):
        # The external write occurs after the read but before mark attachment.
        target.write_bytes(b"externally changed\n")
        return message

    if invocation == "sync":
        result = gate.wrap_tool_call(request, lambda req: finish(tools.read_file_tool.func(runtime=req.runtime, **req.tool_call["args"])))
    else:

        async def execute(req):
            return finish(await tools.read_file_tool.coroutine(runtime=req.runtime, **req.tool_call["args"]))

        result = await gate.awrap_tool_call(request, execute)
    assert isinstance(result, ToolMessage)
    assert result.additional_kwargs["deerflow_tool_meta"]["status"] == status
    assert result.additional_kwargs["deerflow_tool_meta"]["source"] == "tool_return"
    assert result.status == ("error" if status == "error" else "success")
    if status == "error":
        assert READ_MARK_KEY not in result.additional_kwargs
    else:
        assert result.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(source.encode()).hexdigest()


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
@pytest.mark.parametrize("returned", ["", "(empty)", []], ids=["literal-empty-string", "empty-display-sentinel", "nontext-empty-list"])
@pytest.mark.parametrize("original", ["", "not empty"], ids=["empty-file", "nonempty-control"])
async def test_custom_empty_views_only_authorize_actual_text_reads_of_empty_files(tmp_path, invocation, returned, original):
    path = tmp_path / "empty.txt"
    path.write_bytes(original.encode())
    request = _request(str(path))
    gate = ReadBeforeWriteMiddleware(content_reader=lambda runtime, name: path.read_bytes().decode())

    def read(req):
        assert path.read_bytes() == original.encode()
        return ToolMessage(content=returned, tool_call_id="read")

    if invocation == "sync":
        result = gate.wrap_tool_call(request, read)
    else:

        async def aread(req):
            return read(req)

        result = await gate.awrap_tool_call(request, aread)
    can_authorize = original == "" and isinstance(returned, str)
    if can_authorize:
        assert result.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(b"").hexdigest()
    else:
        assert READ_MARK_KEY not in result.additional_kwargs
    write_request = ToolCallRequest(
        tool_call={"name": "write_file", "args": {"path": str(path), "content": "updated"}, "id": "write"},
        tool=None,
        state={"messages": [result]},
        runtime=request.runtime,
    )

    def write(req):
        path.write_bytes(req.tool_call["args"]["content"].encode())
        return ToolMessage(content="OK", tool_call_id="write")

    if invocation == "sync":
        written = gate.wrap_tool_call(write_request, write)
    else:

        async def awrite(req):
            return write(req)

        written = await gate.awrap_tool_call(write_request, awrite)
    assert written.status == ("success" if can_authorize else "error")
    assert path.read_bytes() == (b"updated" if can_authorize else original.encode())


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", ["sync", "async"])
@pytest.mark.parametrize("runtime_id", ["local:log-reader", "independent-test-id"])
@pytest.mark.parametrize(
    "line_range,expected",
    [
        pytest.param({}, "Error: initial failure\nrecovered=true\n\n", id="full"),
        pytest.param({"start_line": 2, "end_line": 2}, "recovered=true", id="second-line"),
        pytest.param({"start_line": 3, "end_line": 3}, "(empty)", id="blank-line"),
    ],
)
async def test_local_error_prefixed_logs_keep_requested_view_and_source_evidence(tmp_path, monkeypatch, invocation, runtime_id, line_range, expected):
    content = "Error: initial failure\nrecovered=true\n\n"
    (tmp_path / "report.log").write_bytes(content.encode())
    sandbox = LocalSandbox("local:actual-reader", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    acquisitions = []

    def initialize(runtime):
        acquisitions.append(runtime)
        return sandbox

    async def initialize_async(runtime):
        return initialize(runtime)

    monkeypatch.setattr(tools, "ensure_sandbox_initialized", initialize)
    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize_async)
    request = _request("/mnt/user-data/workspace/report.log", line_range)
    request.runtime.state.update(sandbox={"sandbox_id": runtime_id}, thread_data={"workspace_path": str(tmp_path)})
    gate = ReadBeforeWriteMiddleware()

    def result(text):
        return ToolMessage(content=text, tool_call_id="read", status="success")

    if invocation == "sync":
        actual = gate.wrap_tool_call(request, lambda req: result(tools.read_file_tool.func(runtime=req.runtime, **req.tool_call["args"])))
    else:

        async def read(req):
            return result(await tools.read_file_tool.coroutine(runtime=req.runtime, **req.tool_call["args"]))

        actual = await gate.awrap_tool_call(request, read)
    assert actual.content == expected
    assert actual.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(content.encode()).hexdigest()
    if invocation == "sync":
        assert len(acquisitions) == 1
    else:
        # The async bridge initializes once before its sync tool body; the
        # snapshot source must not add another lookup beyond the body entry.
        assert len(acquisitions) == 2


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


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", ["sync", "async"])
async def test_snapshot_keeps_source_line_labels_and_original_hash(tmp_path, monkeypatch, invocation):
    path = "/mnt/user-data/workspace/report.txt"
    source = "first\nsecond\nthird\n"
    target = tmp_path / "report.txt"
    target.write_text(source)
    sandbox = LocalSandbox("snapshot-numbered", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=50000)))
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)

    async def initialize(runtime):
        return sandbox

    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize)
    request = _request(path, {"start_line": 2, "end_line": 3})
    request.runtime.tool_call_id = "read"
    gate = ReadBeforeWriteMiddleware()

    def finish(result):
        target.write_text("external change\n")
        return result

    if invocation == "sync":
        result = gate.wrap_tool_call(request, lambda req: finish(tools.read_file_tool.func(runtime=req.runtime, **req.tool_call["args"])))
    else:

        async def execute(req):
            return finish(await tools.read_file_tool.coroutine(runtime=req.runtime, **req.tool_call["args"]))

        result = await gate.awrap_tool_call(request, execute)
    assert result.content == "Source lines (for exact edits, copy the text after the first ' | '):\n2 | second\n3 | third"
    assert result.additional_kwargs[READ_MARK_KEY]["hash"] == hashlib.sha256(source.encode()).hexdigest()
