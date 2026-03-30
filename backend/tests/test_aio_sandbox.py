from types import SimpleNamespace
from unittest.mock import Mock

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox


def _shell_result(output: str) -> SimpleNamespace:
    return SimpleNamespace(data=SimpleNamespace(output=output))


def test_execute_command_retries_with_fresh_session_on_error_observation() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    sandbox._client = SimpleNamespace(
        shell=SimpleNamespace(
            exec_command=Mock(
                side_effect=[
                    _shell_result("'ErrorObservation' object has no attribute 'exit_code'"),
                    _shell_result("command output"),
                ]
            )
        )
    )

    output = sandbox.execute_command("echo hello")

    assert output == "command output"
    assert sandbox._client.shell.exec_command.call_count == 2
    first_call = sandbox._client.shell.exec_command.call_args_list[0].kwargs
    second_call = sandbox._client.shell.exec_command.call_args_list[1].kwargs
    assert first_call == {"command": "echo hello"}
    assert second_call["command"] == "echo hello"
    assert isinstance(second_call["id"], str)
    assert second_call["id"]


def test_execute_command_returns_first_output_when_no_retry_marker() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    sandbox._client = SimpleNamespace(shell=SimpleNamespace(exec_command=Mock(return_value=_shell_result("ok"))))

    output = sandbox.execute_command("echo hello")

    assert output == "ok"
    sandbox._client.shell.exec_command.assert_called_once_with(command="echo hello")


def test_execute_command_returns_no_output_placeholder_when_output_empty() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    sandbox._client = SimpleNamespace(shell=SimpleNamespace(exec_command=Mock(return_value=_shell_result(""))))

    output = sandbox.execute_command("true")

    assert output == "(no output)"


def test_execute_command_handles_none_data() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    result_with_none = SimpleNamespace(data=None)
    sandbox._client = SimpleNamespace(shell=SimpleNamespace(exec_command=Mock(return_value=result_with_none)))

    output = sandbox.execute_command("echo hi")

    assert output == "(no output)"


def test_execute_command_exception_returns_error_string() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    sandbox._client = SimpleNamespace(
        shell=SimpleNamespace(exec_command=Mock(side_effect=RuntimeError("connection refused")))
    )

    output = sandbox.execute_command("echo hi")

    assert "connection refused" in output.lower() or output.startswith("Error")


def test_exec_shell_command_retry_uses_unique_session_ids() -> None:
    """Each retry invocation must use a distinct uuid session ID."""
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    marker = "'ErrorObservation' object has no attribute 'exit_code'"

    # Both commands trigger a retry (first response always the error marker)
    sandbox._client = SimpleNamespace(
        shell=SimpleNamespace(
            exec_command=Mock(
                side_effect=[
                    _shell_result(marker),  # cmd1 first attempt
                    _shell_result("done1"),  # cmd1 retry
                    _shell_result(marker),  # cmd2 first attempt
                    _shell_result("done2"),  # cmd2 retry
                ]
            )
        )
    )

    sandbox.execute_command("cmd1")
    sandbox.execute_command("cmd2")

    all_calls = sandbox._client.shell.exec_command.call_args_list
    retry_ids = [c.kwargs["id"] for c in all_calls if "id" in c.kwargs]
    assert len(retry_ids) == 2, "Both retried commands should supply a session ID"
    assert retry_ids[0] != retry_ids[1], "Each retry should use a unique session ID"


def test_list_dir_retries_on_error_observation_marker() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    marker = "'ErrorObservation' object has no attribute 'exit_code'"
    listing = "/tmp\n/tmp/file.txt"
    sandbox._client = SimpleNamespace(
        shell=SimpleNamespace(
            exec_command=Mock(
                side_effect=[
                    _shell_result(marker),
                    _shell_result(listing),
                ]
            )
        )
    )

    result = sandbox.list_dir("/tmp")

    assert "/tmp" in result
    assert "/tmp/file.txt" in result
    assert sandbox._client.shell.exec_command.call_count == 2


def test_list_dir_returns_empty_list_when_no_output() -> None:
    sandbox = AioSandbox(id="sandbox-1", base_url="http://sandbox.test")
    sandbox._client = SimpleNamespace(shell=SimpleNamespace(exec_command=Mock(return_value=_shell_result(""))))

    result = sandbox.list_dir("/nonexistent")

    assert result == []
