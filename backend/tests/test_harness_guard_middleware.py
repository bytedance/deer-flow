"""Unit tests for HarnessGuardMiddleware (RFC-003, Route C Phase 1)."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.harness_guard_middleware import (
    HARNESS_GUARD_KEY,
    HarnessGuardMiddleware,
    classify_tool_error,
    verify_content_syntax,
)
from deerflow.config.harness_guard_config import HarnessGuardConfig


def _make_request(name: str, args: dict, tool_call_id: str = "call-1", thread_id: str = "t-1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": tool_call_id},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )


class TestErrorClassification:
    def test_module_not_found(self):
        err = "ModuleNotFoundError: No module named 'scipy'"
        sig = classify_tool_error(err)
        assert sig is not None
        assert sig.category == "MODULE_NOT_FOUND"
        assert sig.entity == "scipy"
        assert "pip install scipy" in sig.targeted_hint

    def test_import_error(self):
        err = "ImportError: cannot import name 'FastTensor' from 'torch'"
        sig = classify_tool_error(err)
        assert sig is not None
        assert sig.category == "MODULE_NOT_FOUND"
        assert sig.entity == "torch"

    def test_command_not_found(self):
        err_linux = "bash: line 1: ffmpeg: command not found"
        sig1 = classify_tool_error(err_linux)
        assert sig1 is not None
        assert sig1.category == "COMMAND_NOT_FOUND"
        assert sig1.entity == "ffmpeg"

        err_win = "'ripgrep' 不是内部或外部命令"
        sig2 = classify_tool_error(err_win)
        assert sig2 is not None
        assert sig2.category == "COMMAND_NOT_FOUND"
        assert sig2.entity == "ripgrep"

    def test_file_not_found(self):
        err_py = "FileNotFoundError: [Errno 2] No such file or directory: 'configs/model.yaml'"
        sig1 = classify_tool_error(err_py)
        assert sig1 is not None
        assert sig1.category == "FILE_NOT_FOUND"
        assert sig1.entity == "configs/model.yaml"

        err_sh = "cat: missing_data.csv: No such file or directory"
        sig2 = classify_tool_error(err_sh)
        assert sig2 is not None
        assert sig2.category == "FILE_NOT_FOUND"
        assert sig2.entity == "missing_data.csv"

    def test_syntax_error(self):
        err = 'SyntaxError: invalid syntax  File "app.py", line 42'
        sig = classify_tool_error(err)
        assert sig is not None
        assert sig.category == "SYNTAX_ERROR"
        assert sig.entity == "42"

    def test_permission_denied(self):
        err = "PermissionError: [Errno 13] Permission denied: '/var/run/docker.sock'"
        sig = classify_tool_error(err)
        assert sig is not None
        assert sig.category == "PERMISSION_DENIED"
        assert sig.entity == "/var/run/docker.sock"

    def test_port_in_use(self):
        err = "OSError: [Errno 98] Address already in use"
        sig = classify_tool_error(err)
        assert sig is not None
        assert sig.category == "PORT_IN_USE"

    def test_normal_output_returns_none(self):
        output = "Process completed successfully. Rows processed: 1000."
        assert classify_tool_error(output) is None


class TestSyntaxVerification:
    def test_valid_python(self):
        code = "def hello():\n    return 42\n"
        assert verify_content_syntax("script.py", code) is None

    def test_invalid_python(self):
        bad_code = "def hello(\nreturn 42\n"
        err = verify_content_syntax("script.py", bad_code)
        assert err is not None
        assert "syntax error" in err.lower()

    def test_valid_json(self):
        content = '{"name": "test", "count": 10}'
        assert verify_content_syntax("data.json", content) is None

    def test_invalid_json(self):
        content = '{"name": "test", trailing}'
        err = verify_content_syntax("data.json", content)
        assert err is not None
        assert "JSON" in err

    def test_untracked_extension(self):
        content = "arbitrary text content"
        assert verify_content_syntax("notes.txt", content) is None


class TestHarnessGuardMiddleware:
    def test_write_verify_blocks_invalid_python(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        req = _make_request("write_file", {"path": "main.py", "content": "def bad_syntax(:"})

        def dummy_handler(r):
            return ToolMessage(content="File written", tool_call_id=r.tool_call["id"], name="write_file")

        res = middleware.wrap_tool_call(req, dummy_handler)
        assert isinstance(res, ToolMessage)
        assert res.status == "error"
        assert "WRITE BLOCKED" in res.content
        assert HARNESS_GUARD_KEY in res.additional_kwargs
        assert res.additional_kwargs[HARNESS_GUARD_KEY]["blocked"] is True

    def test_write_verify_passes_valid_python(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        req = _make_request("write_file", {"path": "main.py", "content": "print('ok')"})

        def dummy_handler(r):
            return ToolMessage(content="File written successfully", tool_call_id=r.tool_call["id"], name="write_file")

        res = middleware.wrap_tool_call(req, dummy_handler)
        assert res.status != "error"
        assert res.content == "File written successfully"

    def test_targeted_hint_injection_on_error(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig())
        req = _make_request("bash", {"command": "python test.py"})

        def error_handler(r):
            return ToolMessage(
                content="Traceback (most recent call last):\nModuleNotFoundError: No module named 'pandas'",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            )

        res = middleware.wrap_tool_call(req, error_handler)
        assert "[HARNESS GUARD]" in res.content
        assert "pip install pandas" in res.content
        assert HARNESS_GUARD_KEY in res.additional_kwargs
        assert res.additional_kwargs[HARNESS_GUARD_KEY]["error_signature"] == "MODULE_NOT_FOUND:pandas"

    def test_consecutive_repetition_warning(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(max_repeated_error_signatures=2))
        req = _make_request("bash", {"command": "python script.py"})

        def error_handler(r):
            return ToolMessage(
                content="ModuleNotFoundError: No module named 'fastapi'",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            )

        # Call 1: Normal targeted hint
        res1 = middleware.wrap_tool_call(req, error_handler)
        assert "CRITICAL REPETITION" not in res1.content

        # Call 2: Consecutive identical error signature -> Triggers CRITICAL REPETITION warning
        res2 = middleware.wrap_tool_call(req, error_handler)
        assert "CRITICAL REPETITION" in res2.content
        assert "has occurred 2 times consecutively" in res2.content

    def test_alternating_oscillation_detection(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(detect_alternating_loops=True))

        # Simulate A -> B -> A -> B loop where both tools fail
        req_a1 = _make_request("bash", {"command": "cat output.txt"}, thread_id="t-osc")
        _ = middleware.wrap_tool_call(req_a1, lambda r: ToolMessage(content="cat: output.txt: No such file or directory", tool_call_id=r.tool_call["id"], name="bash", status="error"))

        req_b1 = _make_request("read_file", {"path": "output.txt"}, thread_id="t-osc")
        _ = middleware.wrap_tool_call(req_b1, lambda r: ToolMessage(content="FileNotFoundError: [Errno 2] No such file or directory: 'output.txt'", tool_call_id=r.tool_call["id"], name="read_file", status="error"))

        req_a2 = _make_request("bash", {"command": "cat ./output.txt"}, thread_id="t-osc")
        _ = middleware.wrap_tool_call(req_a2, lambda r: ToolMessage(content="cat: ./output.txt: No such file or directory", tool_call_id=r.tool_call["id"], name="bash", status="error"))

        req_b2 = _make_request("read_file", {"path": "./output.txt"}, thread_id="t-osc")
        res_b2 = middleware.wrap_tool_call(req_b2, lambda r: ToolMessage(content="FileNotFoundError: [Errno 2] No such file or directory: './output.txt'", tool_call_id=r.tool_call["id"], name="read_file", status="error"))

        assert "OSCILLATION DETECTED" in res_b2.content
        assert "between 'bash' and 'read_file'" in res_b2.content

    @pytest.mark.asyncio
    async def test_async_awrap_tool_call(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig())
        req = _make_request("bash", {"command": "run_bad.sh"})

        async def async_handler(r):
            return ToolMessage(
                content="bash: run_bad.sh: command not found",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            )

        res = await middleware.awrap_tool_call(req, async_handler)
        assert "[HARNESS GUARD]" in res.content
        assert "Command 'run_bad.sh' was not found" in res.content
