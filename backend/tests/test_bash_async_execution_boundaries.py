"""Bash execution keeps filesystem-backed output processing off the loop."""

import threading
from types import SimpleNamespace

import pytest

from deerflow.sandbox import tools

pytestmark = pytest.mark.asyncio


async def test_async_bash_finishing_runs_offloop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    invocation = tools._BashInvocation(
        sandbox=object(),
        command="echo hi",
        env=None,
        timeout=None,
        max_chars=20000,
        redaction_env=None,
        thread_data=None,
    )
    monkeypatch.setattr(tools, "_prepare_bash_invocation", lambda *args: invocation)

    async def execute(*args, **kwargs):
        return "hi"

    def finish(output, prepared):
        assert threading.get_ident() != loop_thread
        assert prepared is invocation
        return output

    monkeypatch.setattr(tools, "_execute_bash_command_async", execute)
    monkeypatch.setattr(tools, "_finish_bash_output", finish)
    assert await tools._bash_tool_body_async(SimpleNamespace(context={}), "echo hi") == "hi"


async def test_async_bash_error_sanitization_runs_offloop(monkeypatch) -> None:
    loop_thread = threading.get_ident()

    def prepare(*args):
        raise RuntimeError("failure")

    def sanitize(error, runtime):
        assert threading.get_ident() != loop_thread
        return str(error)

    monkeypatch.setattr(tools, "_prepare_bash_invocation", prepare)
    monkeypatch.setattr(tools, "_sanitize_error", sanitize)
    assert await tools._bash_tool_body_async(SimpleNamespace(context={}), "echo hi") == "Error: Unexpected error executing command: failure"


async def test_scoped_provider_without_async_scope_keeps_sync_scope(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    calls = []

    class Provider:
        def execute_command_in_scope(self, command, env=None, timeout=None, *, scope_id=None):
            assert threading.get_ident() != loop_thread
            calls.append(scope_id)
            return "scoped"

        async def execute_command_async(self, *args, **kwargs):
            pytest.fail("plain async execution must not bypass session isolation")

    monkeypatch.setattr(tools, "sandbox_command_scope", lambda _: "scope")
    output = await tools._execute_bash_command_async(Provider(), "echo hi", runtime=SimpleNamespace(context={}), env=None)
    assert output == "scoped"
    assert calls == ["scope"]
