"""AIO transport failures must not leave a shell generation reusable."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from agent_sandbox.core.api_error import ApiError

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox, _ScopedShellSession


@pytest.fixture
def sandbox():
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        yield AioSandbox(id="recovery-test", base_url="http://localhost:8080")


def completed(output="/test\n/test/file\n\n__DF_FIND_STATUS__:0\n"):
    return SimpleNamespace(data=SimpleNamespace(output=output, exit_code=0, status="completed"))


@pytest.mark.parametrize("session_id", [None, "old-session"])
@pytest.mark.parametrize("error_type", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
def test_list_dir_transport_failure_fences_before_cleanup_and_recovers(sandbox, session_id, error_type):
    sandbox._default_shell_corrupted = session_id is not None
    sandbox._recovery_session_id = session_id
    client = sandbox._client
    client.shell.exec_command.side_effect = [error_type("connection lost"), completed()]

    cleanup_states = []

    def cleanup(*args, **kwargs):
        cleanup_states.append((sandbox._recovery_session_id, sandbox._default_shell_corrupted))
        raise httpx.ReadError("cleanup also failed")

    client.shell.cleanup_session.side_effect = cleanup
    with pytest.raises(OSError, match="unknown"):
        sandbox.list_dir("/test")
    assert client.shell.exec_command.call_count == 1
    assert sandbox._default_shell_corrupted
    assert sandbox._recovery_session_id is None
    assert sandbox._lock.acquire(blocking=False)
    sandbox._lock.release()
    if session_id:
        assert cleanup_states == [(None, True)]
        client.shell.cleanup_session.assert_called_once_with(session_id, request_options={"timeout_in_seconds": 5, "max_retries": 0})
    else:
        client.shell.cleanup_session.assert_not_called()
    assert sandbox.list_dir("/test") == ["/test", "/test/file"]
    replacement = client.shell.create_session.call_args.kwargs["id"]
    assert replacement != session_id
    assert client.shell.exec_command.call_args.kwargs["id"] == replacement


@pytest.mark.parametrize("session_id", [None, "missing-session"])
def test_list_dir_missing_session_is_forgotten_without_replaying(sandbox, session_id):
    sandbox._default_shell_corrupted = session_id is not None
    sandbox._recovery_session_id = session_id
    client = sandbox._client
    client.shell.exec_command.side_effect = [ApiError(status_code=404, body={"message": "Shell session not found"}), completed()]
    with pytest.raises(OSError):
        sandbox.list_dir("/test")
    assert client.shell.exec_command.call_count == 1
    assert sandbox._default_shell_corrupted
    assert sandbox._recovery_session_id is None
    client.shell.cleanup_session.assert_not_called()
    assert sandbox.list_dir("/test") == ["/test", "/test/file"]
    replacement = client.shell.create_session.call_args.kwargs["id"]
    assert replacement != session_id
    assert client.shell.exec_command.call_args.kwargs["id"] == replacement


@pytest.mark.parametrize("status,body", [(404, {"message": "route not found"}), (503, {"message": "session not found"}), (404, "session not found")])
def test_list_dir_other_api_errors_do_not_discard_recovery_session(sandbox, status, body):
    sandbox._default_shell_corrupted = True
    sandbox._recovery_session_id = "keep-session"
    sandbox._client.shell.exec_command.side_effect = ApiError(status_code=status, body=body)
    with pytest.raises(OSError):
        sandbox.list_dir("/test")
    assert sandbox._recovery_session_id == "keep-session"
    sandbox._client.shell.create_session.assert_not_called()
    sandbox._client.shell.cleanup_session.assert_not_called()


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("error_type", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
def test_command_transport_failure_fences_without_replay(sandbox, scoped, error_type):
    client = sandbox._client
    sandbox._default_shell_corrupted = True
    sandbox._recovery_session_id = "default-session"
    sandbox._scoped_shell_sessions["task"] = _ScopedShellSession(session_id="scoped-session")
    client.shell.exec_command.side_effect = [error_type("connection lost"), completed("recovered")]
    invoke = (lambda: sandbox.execute_command_in_scope("echo test", scope_id="task")) if scoped else (lambda: sandbox.execute_command("echo test"))
    result = invoke()
    assert "unknown" in result
    assert "not retried" in result
    assert client.shell.exec_command.call_count == 1
    if scoped:
        assert sandbox._scoped_shell_sessions["task"].session_id is None
        assert sandbox._recovery_session_id == "default-session"
    else:
        assert sandbox._recovery_session_id is None
        assert sandbox._scoped_shell_sessions["task"].session_id == "scoped-session"
    client.shell.cleanup_session.assert_called_once_with("scoped-session" if scoped else "default-session", request_options={"timeout_in_seconds": 5, "max_retries": 0})
    assert invoke() == "recovered"
    assert client.shell.exec_command.call_args.kwargs["id"] == client.shell.create_session.call_args.kwargs["id"]


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_replacement_transport_failure_is_cleaned_up_without_third_attempt(sandbox, scoped, missing):
    client = sandbox._client
    sandbox._default_shell_corrupted = True
    sandbox._recovery_session_id = "default-session"
    sandbox._scoped_shell_sessions["task"] = _ScopedShellSession(session_id="scoped-session")
    first = ApiError(status_code=404, body={"message": "Session not found"}) if missing else completed("'ErrorObservation' object has no attribute 'exit_code'")
    client.shell.exec_command.side_effect = [first, httpx.RemoteProtocolError("connection dropped during recovery")]
    result = sandbox.execute_command_in_scope("echo test", scope_id="task") if scoped else sandbox.execute_command("echo test")
    assert "unknown" in result
    assert "not retried" in result
    assert client.shell.exec_command.call_count == 2
    replacement = client.shell.create_session.call_args.kwargs["id"]
    assert client.shell.cleanup_session.call_args.args == (replacement,)
    assert client.shell.cleanup_session.call_args.kwargs == {"request_options": {"timeout_in_seconds": 5, "max_retries": 0}}
    assert (sandbox._scoped_shell_sessions["task"].session_id if scoped else sandbox._recovery_session_id) is None
