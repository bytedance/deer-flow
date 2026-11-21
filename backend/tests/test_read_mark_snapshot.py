"""A successful read mark must identify the version returned to the model."""

import asyncio
import hashlib
import threading
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from support.shell import require_script_bash

from deerflow.agents.middlewares.read_before_write_middleware import READ_MARK_KEY, ReadBeforeWriteMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.config.app_config import AppConfig
from deerflow.sandbox import tools
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.read_file_contract import READ_FILE_EMPTY, READ_FILE_TRUNCATION_PREFIX

_ORIGINAL = "user_setting=old\n\nhidden=original\n"
_LONG_ORIGINAL = "user_setting=old\n" + "".join(f"row_{index}=original value\n" for index in range(200))


@pytest.mark.asyncio
@pytest.mark.parametrize("invocation", ["sync", "async"])
@pytest.mark.parametrize("update_between_read_and_mark", [False, True], ids=["unchanged-control", "parallel-bash-update"])
@pytest.mark.parametrize(
    "original,read_args,expected_view,max_chars",
    [
        pytest.param(_ORIGINAL, {}, _ORIGINAL, 50000, id="full"),
        pytest.param(_ORIGINAL, {"start_line": 1, "end_line": 1}, "user_setting=old", 50000, id="range"),
        pytest.param(_ORIGINAL, {"start_line": 2, "end_line": 2}, READ_FILE_EMPTY, 50000, id="blank-range"),
        pytest.param(_ORIGINAL.replace("\n", "\r\n"), {"start_line": 1, "end_line": 2}, "user_setting=old\n", 50000, id="crlf-range"),
        pytest.param(_LONG_ORIGINAL, {}, None, 700, id="truncated"),
        pytest.param(_LONG_ORIGINAL, {"start_line": 2, "end_line": 80}, None, 700, id="ranged-truncated"),
        pytest.param("", {}, READ_FILE_EMPTY, 50000, id="empty-file"),
    ],
)
async def test_default_gate_cannot_authorize_a_version_the_read_did_not_return(tmp_path, monkeypatch, invocation, update_between_read_and_mark, original, read_args, expected_view, max_chars):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "settings.txt"
    external = "user_setting=external-update\n"
    stale_edit = original + "agent_note=added\n"
    target.write_bytes(original.encode())
    virtual_path = "/mnt/user-data/workspace/settings.txt"
    sandbox = LocalSandbox("local:read-mark", path_mappings=[PathMapping("/mnt/user-data/workspace", str(workspace))])
    shell = require_script_bash()
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: shell))
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": sandbox.id}, "thread_data": {"workspace_path": workspace.as_posix()}, "messages": []},
        context={"thread_id": "read-mark-race", "user_id": "test-user"},
        config={"configurable": {"thread_id": "read-mark-race"}},
    )

    async def initialize_async(runtime):
        return sandbox

    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize_async)
    monkeypatch.setattr(tools, "is_host_bash_allowed", lambda: True)
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "allow_host_bash": True, "read_file_output_max_chars": max_chars}})
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    middlewares = build_lead_runtime_middlewares(app_config=config)
    assert config.read_before_write.enabled is True
    assert any(isinstance(item, ReadBeforeWriteMiddleware) for item in middlewares)

    def wrap_result(request, tool, content):
        return ToolMessage(content=content, name=tool.name, tool_call_id=request.tool_call["id"], status="error" if content.startswith("Error:") else "success")

    def execute_sync(request):
        tool = {"read_file": tools.read_file_tool, "write_file": tools.write_file_tool, "bash": tools.bash_tool}[request.tool_call["name"]]
        return wrap_result(request, tool, tool.func(runtime=request.runtime, **request.tool_call["args"]))

    async def execute_async(request):
        tool = {"read_file": tools.read_file_tool, "write_file": tools.write_file_tool, "bash": tools.bash_tool}[request.tool_call["name"]]
        content = await tool.coroutine(runtime=request.runtime, **request.tool_call["args"])
        return wrap_result(request, tool, content)

    handler = execute_sync if invocation == "sync" else execute_async
    for middleware in reversed(middlewares):
        method_name = "wrap_tool_call" if invocation == "sync" else "awrap_tool_call"
        if getattr(type(middleware), method_name) is getattr(AgentMiddleware, method_name):
            continue
        inner = handler

        if invocation == "sync":

            def wrapped(request, middleware=middleware, inner=inner):
                return middleware.wrap_tool_call(request, inner)

        else:

            async def wrapped(request, middleware=middleware, inner=inner):
                return await middleware.awrap_tool_call(request, inner)

        handler = wrapped

    async def invoke(name, args, call_id):
        request = ToolCallRequest(tool_call={"name": name, "args": args, "id": call_id}, tool=None, state=runtime.state, runtime=runtime)
        return await asyncio.to_thread(handler, request) if invocation == "sync" else await handler(request)

    captured = asyncio.Event()
    release_read = threading.Event()
    real_read = sandbox.read_file
    first_read = True
    source_reads = []
    loop = asyncio.get_running_loop()

    def pause_after_real_read(path, *args, **kwargs):
        nonlocal first_read
        source_reads.append((kwargs.get("start_line"), kwargs.get("end_line")))
        value = real_read(path, *args, **kwargs)
        if first_read:
            first_read = False
            loop.call_soon_threadsafe(captured.set)
            assert release_read.wait(5), "read worker was not released"
        return value

    monkeypatch.setattr(sandbox, "read_file", pause_after_real_read)
    pending_read = asyncio.create_task(invoke("read_file", {"path": virtual_path, **read_args}, "read-version"))
    try:
        await asyncio.wait_for(captured.wait(), 5)
        if update_between_read_and_mark:
            bash_result = await invoke("bash", {"command": f"printf 'user_setting=external-update\\n' > {virtual_path}"}, "external-update")
            assert bash_result.status == "success", bash_result.content
            assert target.read_bytes() == external.encode()
        release_read.set()
        read_result = await asyncio.wait_for(pending_read, 5)
    finally:
        release_read.set()
        await asyncio.gather(pending_read, return_exceptions=True)

    assert read_result.status == "success"
    assert source_reads == [(None, None)], "source evidence and the displayed range must come from one complete read"
    if expected_view is not None:
        assert read_result.content == expected_view
    else:
        assert READ_FILE_TRUNCATION_PREFIX in read_result.content
        assert len(read_result.content) <= max_chars
    runtime.state["messages"].append(read_result)
    write_result = await invoke("write_file", {"path": virtual_path, "content": stale_edit}, "stale-overwrite")

    observed = (read_result.additional_kwargs.get(READ_MARK_KEY), write_result.status, target.read_bytes())
    if update_between_read_and_mark:
        assert write_result.status == "error", f"A read of the old content authorized overwriting a newer bash edit: {observed!r}"
        assert target.read_bytes() == external.encode()
    else:
        assert write_result.status == "success"
        assert target.read_bytes() == stale_edit.encode()
    mark = read_result.additional_kwargs.get(READ_MARK_KEY)
    assert mark["hash"] == hashlib.sha256(original.encode()).hexdigest()
