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
