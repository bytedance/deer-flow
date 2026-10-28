"""A business argument named ``runtime`` must survive the MCP wrappers.

Both DeerFlow-owned wrappers declared the framework ``ToolRuntime`` under the
name ``runtime`` while keeping the remote ``args_schema``. A model that supplies
a perfectly valid business field with that name therefore had its value bound to
the framework parameter and dropped from ``**arguments`` (issue #7675).

These tests call the wrappers directly with a runtime object and a business
``runtime`` value, which is exactly the call the framework makes after
injection.
"""

from types import SimpleNamespace

import pytest

from deerflow.mcp import tools

SCHEMA = {
    "type": "object",
    "properties": {
        "runtime": {"type": "string"},
        "code": {"type": "string"},
    },
    "required": ["runtime", "code"],
}


def _runtime():
    return SimpleNamespace(
        context={"run_id": "run-1"},
        config={"configurable": {"thread_id": "thread-1"}},
        tool_call_id="call-1",
    )


class _Pool:
    def ensure_binding(self, server_name, fingerprint, domain="deployment"):
        return SimpleNamespace(domain=domain)

    async def get_session(self, *args, **kwargs):
        return SimpleNamespace()


def _remote_tool():
    return SimpleNamespace(name="code_run", description="run code", args_schema=SCHEMA)


@pytest.mark.anyio
async def test_pooled_wrapper_keeps_business_runtime_argument(monkeypatch):
    captured = {}

    async def fake_call(session, pool, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=[], structuredContent=None, isError=False)

    monkeypatch.setattr(tools, "call_pooled_session_tool", fake_call)
    monkeypatch.setattr(tools, "_convert_call_tool_result", lambda result, **kw: result)
    monkeypatch.setattr(tools, "_result_has_text_content", lambda result: False)

    wrapped = tools._make_session_pool_tool(
        _remote_tool(),
        "code",
        {"transport": "sse", "url": "http://example.test/mcp"},
        pool=_Pool(),
        tool_name_prefix=False,
    )

    await wrapped.coroutine(
        _deerflow_runtime=_runtime(),
        runtime="python",
        code="print(1)",
    )

    assert captured["arguments"] == {"runtime": "python", "code": "print(1)"}
