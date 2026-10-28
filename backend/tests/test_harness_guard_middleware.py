"""Unit tests for HarnessGuardMiddleware (RFC-003, Route C Phase 1)."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.harness_guard_middleware import (
    HARNESS_GUARD_KEY,
    HarnessGuardMiddleware,
    classify_tool_error,
    verify_content_syntax,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.config.harness_guard_config import HarnessGuardConfig


def _make_request(
    name: str,
    args: dict,
    tool_call_id: str = "call-1",
    thread_id: str | None = "t-1",
    run_id: str | None = "r-1",
):
    runtime = MagicMock()
    if thread_id is not None or run_id is not None:
        ctx: dict[str, str] = {}
        if thread_id is not None:
            ctx["thread_id"] = thread_id
        if run_id is not None:
            ctx["run_id"] = run_id
        runtime.context = ctx
    else:
        runtime.context = None
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

    def test_syntax_with_null_bytes(self):
        err = verify_content_syntax("evil.py", "print('hello')\x00")
        assert err is not None
        assert "error" in err.lower()

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
        # Verify normalized tool metadata is stamped
        assert TOOL_META_KEY in res.additional_kwargs
        assert res.additional_kwargs[TOOL_META_KEY]["status"] == "error"

    def test_write_verify_skips_append_chunks(self):
        """Append writes of middle chunks must not be blocked as invalid syntax."""
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        # This snippet has unexpected indent if standalone, but is valid in an append chunk
        req = _make_request(
            "write_file",
            {"path": "big.py", "content": "    total = a + b\n    return total\n", "append": True},
        )

        def dummy_handler(r):
            return ToolMessage(content="Appended successfully", tool_call_id=r.tool_call["id"], name="write_file")

        res = middleware.wrap_tool_call(req, dummy_handler)
        assert res.status != "error"
        assert res.content == "Appended successfully"

    def test_str_replace_syntax_validation(self):
        """str_replace on .py that introduces broken syntax is blocked."""
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        req = _make_request(
            "str_replace",
            {"path": "module.py", "old_str": "return 42", "new_str": "return ("},
        )

        def dummy_handler(r):
            return ToolMessage(content="Replaced", tool_call_id=r.tool_call["id"], name="str_replace")

        with patch(
            "deerflow.agents.middlewares.harness_guard_middleware.read_current_file_content",
            return_value="def foo():\n    return 42\n",
        ):
            res = middleware.wrap_tool_call(req, dummy_handler)

        assert isinstance(res, ToolMessage)
        assert res.status == "error"
        assert "WRITE BLOCKED" in res.content
        assert TOOL_META_KEY in res.additional_kwargs

    def test_str_replace_valid_passes(self):
        """str_replace on .py that produces valid syntax passes cleanly."""
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        req = _make_request(
            "str_replace",
            {"path": "module.py", "old_str": "return 42", "new_str": "return 100"},
        )

        def dummy_handler(r):
            return ToolMessage(content="Replaced successfully", tool_call_id=r.tool_call["id"], name="str_replace")

        with patch(
            "deerflow.agents.middlewares.harness_guard_middleware.read_current_file_content",
            return_value="def foo():\n    return 42\n",
        ):
            res = middleware.wrap_tool_call(req, dummy_handler)

        assert res.status != "error"
        assert res.content == "Replaced successfully"

    def test_write_verify_passes_valid_python(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(block_on_syntax_error=True))
        req = _make_request("write_file", {"path": "main.py", "content": "print('ok')"})

        def dummy_handler(r):
            return ToolMessage(content="File written successfully", tool_call_id=r.tool_call["id"], name="write_file")

        res = middleware.wrap_tool_call(req, dummy_handler)
        assert res.status != "error"
        assert res.content == "File written successfully"

    def test_multimodal_list_content_preserved(self):
        """When ToolMessage content is a list of blocks, hints are appended as text blocks rather than stringifying."""
        middleware = HarnessGuardMiddleware(HarnessGuardConfig())
        req = _make_request("bash", {"command": "fetch_plot.sh"})

        image_block = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo"}}
        text_block = {"type": "text", "text": "Traceback:\nModuleNotFoundError: No module named 'matplotlib'"}

        def handler(r):
            return ToolMessage(
                content=[text_block, image_block],
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            )

        res = middleware.wrap_tool_call(req, handler)
        assert isinstance(res.content, list)
        assert len(res.content) == 3
        assert res.content[0] == text_block
        assert res.content[1] == image_block
        assert res.content[2]["type"] == "text"
        assert "[HARNESS GUARD]" in res.content[2]["text"]
        assert "pip install matplotlib" in res.content[2]["text"]

    def test_cross_thread_isolation_no_poisoning(self):
        """Context-less requests from different runtimes do not share history deque."""
        middleware = HarnessGuardMiddleware(HarnessGuardConfig(max_repeated_error_signatures=2))

        # Runtime A experiences an error
        req_a = _make_request("bash", {"command": "cmd_a"}, thread_id=None, run_id=None)
        res_a = middleware.wrap_tool_call(
            req_a,
            lambda r: ToolMessage(
                content="ModuleNotFoundError: No module named 'isolated_pkg'",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            ),
        )
        assert "CRITICAL REPETITION" not in res_a.content

        # Runtime B experiences the same error in its first call
        req_b = _make_request("bash", {"command": "cmd_b"}, thread_id=None, run_id=None)
        res_b = middleware.wrap_tool_call(
            req_b,
            lambda r: ToolMessage(
                content="ModuleNotFoundError: No module named 'isolated_pkg'",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            ),
        )
        # Because Runtime A and Runtime B are distinct, B must NOT see A's history
        assert "CRITICAL REPETITION" not in res_b.content

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
        req_a1 = _make_request("bash", {"command": "cat output.txt"}, thread_id="t-osc", run_id="r-osc")
        _ = middleware.wrap_tool_call(
            req_a1,
            lambda r: ToolMessage(
                content="cat: output.txt: No such file or directory",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            ),
        )

        req_b1 = _make_request("read_file", {"path": "output.txt"}, thread_id="t-osc", run_id="r-osc")
        _ = middleware.wrap_tool_call(
            req_b1,
            lambda r: ToolMessage(
                content="FileNotFoundError: [Errno 2] No such file or directory: 'output.txt'",
                tool_call_id=r.tool_call["id"],
                name="read_file",
                status="error",
            ),
        )

        req_a2 = _make_request("bash", {"command": "cat ./output.txt"}, thread_id="t-osc", run_id="r-osc")
        _ = middleware.wrap_tool_call(
            req_a2,
            lambda r: ToolMessage(
                content="cat: ./output.txt: No such file or directory",
                tool_call_id=r.tool_call["id"],
                name="bash",
                status="error",
            ),
        )

        req_b2 = _make_request("read_file", {"path": "./output.txt"}, thread_id="t-osc", run_id="r-osc")
        res_b2 = middleware.wrap_tool_call(
            req_b2,
            lambda r: ToolMessage(
                content="FileNotFoundError: [Errno 2] No such file or directory: './output.txt'",
                tool_call_id=r.tool_call["id"],
                name="read_file",
                status="error",
            ),
        )

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

    def test_command_result_processing(self):
        from langgraph.types import Command

        middleware = HarnessGuardMiddleware(HarnessGuardConfig())
        req = _make_request("subagent_task", {"subtask": "fetch data"}, tool_call_id="call-sub")

        inner_msg = ToolMessage(
            content="ModuleNotFoundError: No module named 'polars'",
            tool_call_id="call-sub",
            name="subagent_task",
            status="error",
        )
        cmd = Command(update={"messages": [inner_msg]})

        res = middleware.wrap_tool_call(req, lambda r: cmd)
        assert isinstance(res, Command)
        assert "[HARNESS GUARD]" in inner_msg.content
        assert "pip install polars" in inner_msg.content

    def test_huge_output_error_classification(self):
        middleware = HarnessGuardMiddleware(HarnessGuardConfig())
        req = _make_request("bash", {"command": "big_log.sh"})

        huge_content = "Normal log line\n" * 5000 + "ModuleNotFoundError: No module named 'torch_geometric'"
        res = middleware.wrap_tool_call(
            req,
            lambda r: ToolMessage(content=huge_content, tool_call_id=r.tool_call["id"], name="bash", status="error"),
        )
        assert "[HARNESS GUARD]" in res.content
        assert "pip install torch_geometric" in res.content
