"""Tests for AioSandbox concurrent command serialization (#1433)."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest


class _TeardownFirstScopeLock:
    """Let teardown clean a scope before one already-admitted waiter runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.command_waiting = threading.Event()
        self.allow_command = threading.Event()
        self.command_done = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "queued-command":
            self.command_waiting.set()
            self.allow_command.wait(timeout=2)
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()
        if threading.current_thread().name == "scope-teardown":
            self.allow_command.set()
            self.command_done.wait(timeout=2)


def test_local_sandbox_client_bypasses_environment_proxy():
    """Local sandbox API calls must not inherit HTTP_PROXY (#3441)."""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    sentinel_httpx = MagicMock()
    with (
        patch("deerflow.community.aio_sandbox.aio_sandbox.httpx.Client", return_value=sentinel_httpx) as client_cls,
        patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient") as sdk_cls,
    ):
        AioSandbox(id="test-sandbox", base_url="http://host.docker.internal:8080")

    client_cls.assert_called_once_with(timeout=600, follow_redirects=True, trust_env=False)
    sdk_cls.assert_called_once_with(
        base_url="http://host.docker.internal:8080",
        timeout=600,
        httpx_client=sentinel_httpx,
    )


def test_local_sandbox_client_forwards_trusted_relay_headers():
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    sentinel_httpx = MagicMock()
    headers = {"X-DeerFlow-Relay-Token": "secret-token"}
    with (
        patch("deerflow.community.aio_sandbox.aio_sandbox.httpx.Client", return_value=sentinel_httpx),
        patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient") as sdk_cls,
    ):
        AioSandbox(
            id="test-sandbox",
            base_url="http://host.docker.internal:8080",
            request_headers=headers,
        )

    sdk_cls.assert_called_once_with(
        base_url="http://host.docker.internal:8080",
        timeout=600,
        headers=headers,
        httpx_client=sentinel_httpx,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://sandbox.example.com",
        "http://8.8.8.8:8080",
        "http://[2606:4700:4700::1111]:8080",
    ],
)
def test_external_sandbox_client_keeps_environment_proxy_support(base_url: str):
    """Externally hosted sandbox URLs retain the SDK's default proxy behavior."""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    with (
        patch("deerflow.community.aio_sandbox.aio_sandbox.httpx.Client") as client_cls,
        patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient") as sdk_cls,
    ):
        AioSandbox(id="test-sandbox", base_url=base_url)

    client_cls.assert_not_called()
    sdk_cls.assert_called_once_with(base_url=base_url, timeout=600)


@pytest.fixture()
def sandbox():
    """Create an AioSandbox with a mocked client."""
    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        sb = AioSandbox(id="test-sandbox", base_url="http://localhost:8080")
        return sb


def test_exec_command_appends_exit_marker_when_failure_has_output(sandbox):
    """The legacy exec path must propagate the structured exit_code into the
    output text (LocalSandbox parity) instead of discarding it."""
    sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="5 passed, 1 error\n", exit_code=1)))

    assert sandbox.execute_command("make test") == "5 passed, 1 error\n\nExit Code: 1"


def test_bash_exec_appends_exit_marker_when_failure_has_output(sandbox):
    """The bash.exec (env-bearing) path must propagate exit_code the same way."""
    sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="5 passed, 1 error\n", stderr="", exit_code=1)))

    assert sandbox.execute_command("make test", env={"A": "1"}) == "5 passed, 1 error\n\nExit Code: 1"


class TestExecuteCommandSerialization:
    """Verify that concurrent exec_command calls are serialized."""

    def test_lock_prevents_concurrent_execution(self, sandbox):
        """Concurrent threads should not overlap inside execute_command."""
        call_log = []
        barrier = threading.Barrier(3)

        def slow_exec(command, **kwargs):
            call_log.append(("enter", command))
            import time

            time.sleep(0.05)
            call_log.append(("exit", command))
            return SimpleNamespace(data=SimpleNamespace(output=f"ok: {command}"))

        sandbox._client.shell.exec_command = slow_exec

        def worker(cmd):
            barrier.wait()  # ensure all threads contend for the lock simultaneously
            sandbox.execute_command(cmd)

        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(f"cmd-{i}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify serialization: each "enter" should be followed by its own
        # "exit" before the next "enter" (no interleaving).
        enters = [i for i, (action, _) in enumerate(call_log) if action == "enter"]
        exits = [i for i, (action, _) in enumerate(call_log) if action == "exit"]
        assert len(enters) == 3
        assert len(exits) == 3
        for e_idx, x_idx in zip(enters, exits):
            assert x_idx == e_idx + 1, f"Interleaved execution detected: {call_log}"


class TestErrorObservationRetry:
    """Verify ErrorObservation detection and fresh-session retry."""

    def test_retry_on_error_observation(self, sandbox):
        """When output contains ErrorObservation, retry with a fresh session."""
        call_count = 0

        def mock_exec(command, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="success"))

        sandbox._client.shell.exec_command = mock_exec

        result = sandbox.execute_command("echo hello")
        assert result == "success"
        assert call_count == 2

    def test_retry_creates_fresh_session_before_targeting_it(self, sandbox):
        """Recovery must explicitly create a session, then exec against that id.

        The sandbox image only auto-creates a session when exec_command is
        called with *no* id; an exec carrying an unknown id returns HTTP 404
        "Session not found". So the retry must obtain a real, distinct session
        via create_session() first and target that id, rather than fabricating
        an id and handing it straight to exec_command (the regression that
        404'd every recovery and looped runs to the recursion limit).
        """
        exec_calls = []
        created_ids = []
        cleaned_ids = []

        def mock_exec(command, **kwargs):
            exec_calls.append(kwargs)
            if len(exec_calls) == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        def mock_create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def mock_cleanup_session(session_id, **kwargs):
            cleaned_ids.append(session_id)

        sandbox._client.shell.exec_command = mock_exec
        sandbox._client.shell.create_session = mock_create_session
        sandbox._client.shell.cleanup_session = mock_cleanup_session

        result = sandbox.execute_command("test")

        assert result == "ok"
        assert len(exec_calls) == 2
        # First attempt runs on the default session (no id).
        assert "id" not in exec_calls[0]
        # A fresh session was explicitly created...
        assert len(created_ids) == 1
        assert len(created_ids[0]) == 36  # UUID format
        # ...and the retry targets exactly that created session, never an
        # uncreated/fabricated id (which would 404).
        assert exec_calls[1].get("id") == created_ids[0]
        # The recovered session is promoted: future commands must not return
        # to the corrupted implicit default session.
        assert cleaned_ids == []
        assert sandbox.execute_command("again") == "ok"
        assert exec_calls[-1].get("id") == created_ids[0]

        sandbox.close()
        assert cleaned_ids == [created_ids[0]]

    @pytest.mark.parametrize("status", ["running", "pending"])
    def test_unknown_legacy_status_is_ambiguous_and_invalidates_default_session(self, sandbox, status):
        executions = 0

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=0,
                    status=status,
                )
            )

        sandbox._client.shell.exec_command = exec_command

        out = sandbox.execute_command("unsafe-to-repeat")

        assert executions == 1
        assert f"unexpected status '{status}'" in out
        assert "outcome is unknown" in out
        assert "not retried" in out
        assert "Exit Code:" not in out
        assert sandbox._default_shell_corrupted is True
        assert sandbox._recovery_session_id is None

    def test_unknown_legacy_status_cleans_up_explicit_recovery_session(self, sandbox):
        cleaned = []
        sandbox._recovery_session_id = "recovery-session"
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="partial", exit_code=0, status="weird_future_status")))
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command("unsafe-to-repeat")

        assert "unexpected status 'weird_future_status'" in out
        assert "Exit Code:" not in out
        assert sandbox._recovery_session_id is None
        assert sandbox._default_shell_corrupted is True
        assert cleaned == [
            (
                "recovery-session",
                {
                    "request_options": {
                        "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                        "max_retries": 0,
                    }
                },
            )
        ]

    def test_no_change_timeout_invalidates_default_recovery_session(self, sandbox):
        executions = 0
        cleaned = []
        sandbox._recovery_session_id = "recovery-session"

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=None,
                    status="no_change_timeout",
                )
            )

        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command("quiet-command")

        assert executions == 1
        assert "may still be running" in out
        assert sandbox._recovery_session_id is None
        assert sandbox._default_shell_corrupted is True
        assert cleaned == [
            (
                "recovery-session",
                {
                    "request_options": {
                        "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                        "max_retries": 0,
                    }
                },
            )
        ]

    def test_error_observation_retry_unknown_status_is_authoritative(self, sandbox):
        executions = 0
        created_ids = []
        cleaned = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            if executions == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="'ErrorObservation' object has no attribute 'exit_code'",
                        exit_code=None,
                        status="completed",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="retry partial",
                    exit_code=0,
                    status="pending",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command("unsafe-to-repeat")

        assert executions == 2
        assert len(created_ids) == 1
        assert "unexpected status 'pending'" in out
        assert "retry partial" in out
        assert "Exit Code:" not in out
        assert sandbox._recovery_session_id is None
        assert sandbox._default_shell_corrupted is True
        assert [session_id for session_id, _ in cleaned] == [created_ids[0]]

    def test_error_observation_replacement_no_change_timeout_is_not_retained(self, sandbox):
        executions = 0
        created_ids = []
        cleaned = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            if executions == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="'ErrorObservation' object has no attribute 'exit_code'",
                        exit_code=None,
                        status="completed",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="replacement partial",
                    exit_code=None,
                    status="no_change_timeout",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command("unsafe-to-repeat")

        assert executions == 2
        assert "may still be running" in out
        assert "replacement partial" in out
        assert sandbox._recovery_session_id is None
        assert cleaned == [
            (
                created_ids[0],
                {
                    "request_options": {
                        "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                        "max_retries": 0,
                    }
                },
            )
        ]

    def test_cleanup_failure_does_not_mask_successful_retry(self, sandbox):
        """A failure releasing the recovery session must not lose the retry output."""

        def mock_exec(command, **kwargs):
            if "id" not in kwargs:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="recovered"))

        def mock_cleanup_session(session_id, **kwargs):
            raise RuntimeError("cleanup boom")

        sandbox._client.shell.exec_command = mock_exec
        sandbox._client.shell.create_session = lambda id, **kwargs: SimpleNamespace(data=SimpleNamespace(session_id=id))
        sandbox._client.shell.cleanup_session = mock_cleanup_session

        # The retry succeeded; the swallowed cleanup error must not turn this
        # into an "Error: ..." result.
        assert sandbox.execute_command("test") == "recovered"

    def test_failed_replacement_never_falls_back_to_corrupt_default(self, sandbox):
        created_ids: list[str] = []
        exec_ids: list[str | None] = []

        def mock_create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def mock_exec(command, **kwargs):
            session_id = kwargs.get("id")
            exec_ids.append(session_id)
            if len(exec_ids) <= 2:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="healthy"))

        sandbox._client.shell.create_session = mock_create_session
        sandbox._client.shell.exec_command = mock_exec

        assert "ErrorObservation" in sandbox.execute_command("first")
        assert sandbox.execute_command("second") == "healthy"
        assert exec_ids[0] is None
        assert exec_ids[1] == created_ids[0]
        # The next call creates another explicit session instead of touching
        # the already-proven-corrupt implicit default again.
        assert exec_ids[2] == created_ids[1]
        assert all(session_id is not None for session_id in exec_ids[1:])

    def test_no_retry_on_clean_output(self, sandbox):
        """Normal output should not trigger a retry."""
        call_count = 0

        def mock_exec(command, **kwargs):
            nonlocal call_count
            call_count += 1
            return SimpleNamespace(data=SimpleNamespace(output="all good"))

        sandbox._client.shell.exec_command = mock_exec

        result = sandbox.execute_command("echo hello")
        assert result == "all good"
        assert call_count == 1

    def test_missing_recovery_session_is_recreated_once_and_reused(self, sandbox):
        """An evicted lead recovery session must not poison every later call."""
        from agent_sandbox.core.api_error import ApiError

        created_ids: list[str] = []
        exec_ids: list[str | None] = []
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = "evicted-lead-session"

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            session_id = kwargs.get("id")
            exec_ids.append(session_id)
            if session_id == "evicted-lead-session":
                raise ApiError(
                    status_code=404,
                    body={"message": f"Shell session not found: {session_id}"},
                )
            return SimpleNamespace(data=SimpleNamespace(output="healthy", exit_code=0))

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        assert sandbox.execute_command("first") == "healthy"
        assert sandbox.execute_command("second") == "healthy"
        assert len(created_ids) == 1
        assert exec_ids == ["evicted-lead-session", created_ids[0], created_ids[0]]

    def test_transport_timeout_marks_default_shell_untrusted_without_replay(self, sandbox):
        executions = 0

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            raise httpx.ReadTimeout("response stalled")

        sandbox._client.shell.exec_command = exec_command

        out = sandbox.execute_command("side-effect; sleep 30", timeout=3)

        assert executions == 1
        assert "outcome is unknown" in out
        assert "not retried" in out
        assert sandbox._default_shell_corrupted is True
        assert sandbox._recovery_session_id is None

        assert sandbox._lock.acquire(blocking=False) is True
        sandbox._lock.release()

    def test_transport_timeout_invalidates_default_recovery_session_without_replay(self, sandbox):
        cleaned_ids = []
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = "recovery-session"
        sandbox._client.shell.exec_command = MagicMock(side_effect=httpx.ReadTimeout("response stalled"))
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append((session_id, kwargs))

        out = sandbox.execute_command("side-effect; sleep 30", timeout=3)

        assert "outcome is unknown" in out
        assert "not retried" in out
        assert sandbox._default_shell_corrupted is True
        assert sandbox._recovery_session_id is None
        assert cleaned_ids == [
            (
                "recovery-session",
                {
                    "request_options": {
                        "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                        "max_retries": 0,
                    }
                },
            )
        ]

    def test_terminated_default_session_cleanup_failure_preserves_terminal_outcome(self, sandbox):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        executions = 0
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = "terminated-session"

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=None,
                    status="terminated",
                )
            )

        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = MagicMock(side_effect=RuntimeError("cleanup failed"))

        out = sandbox.execute_command("unsafe-to-repeat", timeout=3)

        assert executions == 1
        assert "Command was terminated because its shell session ended." in out
        assert sandbox._recovery_session_id is None
        assert sandbox._default_shell_corrupted is True
        sandbox._client.shell.cleanup_session.assert_called_once_with(
            "terminated-session",
            request_options={
                "timeout_in_seconds": AioSandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                "max_retries": 0,
            },
        )

    def test_terminated_recovery_session_is_invalidated_without_replay(self, sandbox):
        created_ids: list[str] = []
        exec_ids: list[str | None] = []
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = "terminated-session"

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs.get("id"))
            if len(exec_ids) == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="partial",
                        exit_code=None,
                        status="terminated",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="next-ok",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        first = sandbox.execute_command("unsafe-to-repeat", timeout=3)
        second = sandbox.execute_command("next-command", timeout=3)

        assert "terminated" in first.lower()
        assert second == "next-ok"
        assert exec_ids == ["terminated-session", created_ids[0]]
        assert len(created_ids) == 1

    def test_terminated_replacement_session_is_not_reused(self, sandbox):
        created_ids: list[str] = []
        exec_ids: list[str | None] = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs.get("id"))
            if len(exec_ids) == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="'ErrorObservation' object has no attribute 'exit_code'",
                        status="completed",
                    )
                )
            if len(exec_ids) == 2:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="partial",
                        exit_code=None,
                        status="terminated",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="next-ok",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        first = sandbox.execute_command("unsafe-to-repeat", timeout=3)
        second = sandbox.execute_command("next-command", timeout=3)

        assert "terminated" in first.lower()
        assert second == "next-ok"
        assert exec_ids == [None, created_ids[0], created_ids[1]]
        assert len(created_ids) == 2


class TestScopedShellSessions:
    """Concurrent subagents use independent persistent shell sessions (#5128)."""

    def test_scoped_command_forwards_same_timeout_budget(self, sandbox):
        sandbox._client.shell.create_session = MagicMock()
        sandbox._client.shell.exec_command = MagicMock(
            return_value=SimpleNamespace(
                data=SimpleNamespace(
                    output="ok",
                    exit_code=0,
                    status="completed",
                )
            )
        )

        assert (
            sandbox.execute_command_in_scope(
                "echo ok",
                timeout=3,
                scope_id="subagent-a",
            )
            == "ok"
        )

        kwargs = sandbox._client.shell.exec_command.call_args.kwargs
        assert kwargs["hard_timeout"] == 3
        assert kwargs["request_options"] == {
            "timeout_in_seconds": 8,
            "max_retries": 0,
        }

    def test_transport_timeout_invalidates_scoped_session_without_replay(self, sandbox):
        executions = 0
        cleaned_ids = []

        sandbox._client.shell.create_session = MagicMock()

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            raise httpx.ReadTimeout("response stalled")

        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append((session_id, kwargs))

        out = sandbox.execute_command_in_scope(
            "side-effect; sleep 30",
            timeout=3,
            scope_id="subagent-a",
        )

        assert executions == 1
        assert "outcome is unknown" in out
        assert "not retried" in out
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None
        assert len(cleaned_ids) == 1
        assert cleaned_ids[0][1]["request_options"] == {
            "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
            "max_retries": 0,
        }

    def test_terminated_scoped_session_is_invalidated_without_replay(self, sandbox):
        executions = 0
        created_ids = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            if executions == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="partial",
                        exit_code=None,
                        status="terminated",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="next-ok",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        first = sandbox.execute_command_in_scope(
            "unsafe-to-repeat",
            timeout=3,
            scope_id="subagent-a",
        )
        second = sandbox.execute_command_in_scope(
            "next-command",
            timeout=3,
            scope_id="subagent-a",
        )

        assert "terminated" in first.lower()
        assert second == "next-ok"
        assert executions == 2
        assert len(created_ids) == 2

    def test_no_change_timeout_invalidates_scoped_session_without_replay(self, sandbox):
        executions = 0
        created_ids = []
        cleaned = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=None,
                    status="no_change_timeout",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command_in_scope("quiet-command", scope_id="subagent-a")

        assert executions == 1
        assert "may still be running" in out
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None
        assert cleaned == [
            (
                created_ids[0],
                {
                    "request_options": {
                        "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                        "max_retries": 0,
                    }
                },
            )
        ]

    def test_transport_timeout_cleanup_failure_does_not_replace_primary_outcome(self, sandbox):
        sandbox._client.shell.create_session = MagicMock()
        sandbox._client.shell.exec_command = MagicMock(side_effect=httpx.ReadTimeout("response stalled"))
        sandbox._client.shell.cleanup_session = MagicMock(side_effect=RuntimeError("cleanup failed"))

        out = sandbox.execute_command_in_scope(
            "unsafe-to-repeat",
            timeout=3,
            scope_id="subagent-a",
        )

        assert "outcome is unknown" in out
        assert "cleanup failed" not in out

    def test_transport_timeout_during_replacement_is_ambiguous_without_replay(self, sandbox):
        from agent_sandbox.core.api_error import ApiError

        executions = 0
        created_ids = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            if executions == 1:
                raise ApiError(
                    status_code=404,
                    body={"message": "session not found"},
                )
            raise httpx.ReadTimeout("response stalled")

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        out = sandbox.execute_command_in_scope(
            "unsafe-to-repeat",
            timeout=3,
            scope_id="subagent-a",
        )

        assert "outcome is unknown" in out
        assert "not retried" in out
        assert executions == 2
        assert len(created_ids) == 2
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None

    def test_different_scopes_execute_concurrently(self, sandbox):
        active = 0
        max_active = 0
        active_lock = threading.Lock()
        start_barrier = threading.Barrier(2)
        session_ids: list[str] = []

        def create_session(id, **kwargs):
            session_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def overlapping_exec(command, **kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            start_barrier.wait(timeout=1)
            with active_lock:
                active -= 1
            return SimpleNamespace(data=SimpleNamespace(output=command, exit_code=0))

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = overlapping_exec

        outputs: list[str] = []

        def worker(scope_id: str):
            outputs.append(
                sandbox.execute_command_in_scope(
                    scope_id,
                    scope_id=scope_id,
                )
            )

        threads = [
            threading.Thread(target=worker, args=("subagent-a",)),
            threading.Thread(target=worker, args=("subagent-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outputs) == ["subagent-a", "subagent-b"]
        assert max_active == 2
        assert len(set(session_ids)) == 2

    def test_same_scope_remains_serialized(self, sandbox):
        call_log: list[tuple[str, str]] = []
        start_barrier = threading.Barrier(3)

        sandbox._client.shell.create_session = lambda id, **kwargs: SimpleNamespace(data=SimpleNamespace(session_id=id))

        def slow_exec(command, **kwargs):
            call_log.append(("enter", command))
            import time

            time.sleep(0.03)
            call_log.append(("exit", command))
            return SimpleNamespace(data=SimpleNamespace(output=command, exit_code=0))

        sandbox._client.shell.exec_command = slow_exec

        def worker(command: str):
            start_barrier.wait()
            sandbox.execute_command_in_scope(command, scope_id="one-subagent")

        threads = [threading.Thread(target=worker, args=(f"cmd-{index}",)) for index in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        for index in range(0, len(call_log), 2):
            assert call_log[index][0] == "enter"
            assert call_log[index + 1] == ("exit", call_log[index][1])

    def test_corrupt_scoped_session_is_replaced_and_reused(self, sandbox):
        created_ids: list[str] = []
        cleaned_ids: list[str] = []
        exec_ids: list[str] = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs["id"])
            if len(exec_ids) == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="'ErrorObservation' object has no attribute 'exit_code'",
                        exit_code=None,
                    )
                )
            return SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0))

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append(session_id)

        assert sandbox.execute_command_in_scope("first", scope_id="subagent-a") == "ok"
        assert len(created_ids) == 2
        assert cleaned_ids == [created_ids[0]]
        assert exec_ids == [created_ids[0], created_ids[1]]

        assert sandbox.execute_command_in_scope("second", scope_id="subagent-a") == "ok"
        assert exec_ids[-1] == created_ids[1]

        sandbox.release_command_scope("subagent-a")
        assert cleaned_ids == created_ids

    def test_missing_scoped_session_is_recreated_and_reused(self, sandbox):
        """A server-side session loss must not pin the scope to a stale id."""
        from agent_sandbox.core.api_error import ApiError

        created_ids: list[str] = []
        exec_ids: list[str] = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs["id"])
            if len(exec_ids) == 1:
                raise ApiError(
                    headers={"server": "nginx/1.18.0 (Ubuntu)"},
                    status_code=404,
                    body={"success": False, "message": "Session not found", "data": None, "hint": None},
                )
            return SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0))

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        assert sandbox.execute_command_in_scope("first", scope_id="subagent-a") == "ok"
        assert len(created_ids) == 2
        assert exec_ids == created_ids

        assert sandbox.execute_command_in_scope("second", scope_id="subagent-a") == "ok"
        assert exec_ids[-1] == created_ids[1]

    def test_missing_scoped_session_recovery_is_bounded(self, sandbox):
        """A missing replacement session is reported after one recovery attempt."""
        from agent_sandbox.core.api_error import ApiError

        created_ids: list[str] = []
        exec_ids: list[str] = []
        cleaned_ids: list[str] = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs["id"])
            raise ApiError(
                headers={"server": "nginx/1.18.0 (Ubuntu)"},
                status_code=404,
                body={"success": False, "message": "Session not found", "data": None},
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append(session_id)

        result = sandbox.execute_command_in_scope("first", scope_id="subagent-a")

        assert result.startswith("Error:")
        assert len(created_ids) == 2
        assert exec_ids == created_ids
        assert cleaned_ids == [created_ids[1]]
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None

    def test_other_scoped_404_does_not_rotate_session(self, sandbox):
        """Only the structured missing-session response is recoverable."""
        from agent_sandbox.core.api_error import ApiError

        created_ids: list[str] = []
        exec_ids: list[str] = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_ids.append(kwargs["id"])
            raise ApiError(
                headers={"server": "nginx/1.18.0 (Ubuntu)"},
                status_code=404,
                body={"success": False, "message": "Not Found", "data": None},
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        result = sandbox.execute_command_in_scope("first", scope_id="subagent-a")

        assert result.startswith("Error:")
        assert len(created_ids) == 1
        assert exec_ids == created_ids
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id == created_ids[0]

    def test_queued_command_cannot_restart_session_after_scope_release(self, sandbox):
        created_ids: list[str] = []
        executed_commands: list[str] = []
        cleaned_ids: list[str] = []

        sandbox._client.shell.create_session = lambda id, **kwargs: created_ids.append(id)
        sandbox._client.shell.exec_command = lambda command, **kwargs: executed_commands.append(command) or SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0))
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append(session_id)

        assert sandbox.execute_command_in_scope("initial", scope_id="subagent-a") == "ok"
        scoped = sandbox._scoped_shell_sessions["subagent-a"]
        controlled_lock = _TeardownFirstScopeLock()
        scoped.lock = controlled_lock
        queued_results: list[str] = []

        def queued_command() -> None:
            try:
                queued_results.append(sandbox.execute_command_in_scope("late", scope_id="subagent-a"))
            finally:
                controlled_lock.command_done.set()

        command_thread = threading.Thread(target=queued_command, name="queued-command")
        command_thread.start()
        assert controlled_lock.command_waiting.wait(timeout=1)
        teardown_thread = threading.Thread(
            target=sandbox.release_command_scope,
            args=("subagent-a",),
            name="scope-teardown",
        )
        teardown_thread.start()
        command_thread.join(timeout=2)
        teardown_thread.join(timeout=2)

        assert not command_thread.is_alive()
        assert not teardown_thread.is_alive()
        assert queued_results == ["Error: sandbox command scope is no longer active"]
        assert len(created_ids) == 1
        assert executed_commands == ["initial"]
        assert cleaned_ids == created_ids

    def test_queued_command_cannot_restart_session_while_sandbox_closes(self, sandbox):
        created_ids: list[str] = []
        executed_commands: list[str] = []
        cleaned_ids: list[str] = []

        sandbox._client.shell.create_session = lambda id, **kwargs: created_ids.append(id)
        sandbox._client.shell.exec_command = lambda command, **kwargs: executed_commands.append(command) or SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0))
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned_ids.append(session_id)

        assert sandbox.execute_command_in_scope("initial", scope_id="subagent-a") == "ok"
        scoped = sandbox._scoped_shell_sessions["subagent-a"]
        controlled_lock = _TeardownFirstScopeLock()
        scoped.lock = controlled_lock
        queued_results: list[str] = []

        def queued_command() -> None:
            try:
                queued_results.append(sandbox.execute_command_in_scope("late", scope_id="subagent-a"))
            finally:
                controlled_lock.command_done.set()

        command_thread = threading.Thread(target=queued_command, name="queued-command")
        command_thread.start()
        assert controlled_lock.command_waiting.wait(timeout=1)
        teardown_thread = threading.Thread(target=sandbox.close, name="scope-teardown")
        teardown_thread.start()
        command_thread.join(timeout=2)
        teardown_thread.join(timeout=2)

        assert not command_thread.is_alive()
        assert not teardown_thread.is_alive()
        assert queued_results == ["Error: sandbox command scope is no longer active"]
        assert len(created_ids) == 1
        assert executed_commands == ["initial"]
        assert cleaned_ids == created_ids

    def test_scoped_unknown_status_is_ambiguous_without_replay(self, sandbox):
        executions = 0
        created_ids = []
        cleaned = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=0,
                    status="running",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.cleanup_session = lambda session_id, **kwargs: cleaned.append((session_id, kwargs))

        out = sandbox.execute_command_in_scope("unsafe-to-repeat", scope_id="subagent-a")

        assert executions == 1
        assert len(created_ids) == 1
        assert "unexpected status 'running'" in out
        assert "Exit Code:" not in out
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None
        assert [session_id for session_id, _ in cleaned] == [created_ids[0]]
        assert cleaned[0][1]["request_options"] == {
            "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
            "max_retries": 0,
        }

    @pytest.mark.parametrize("status", ["pending", "weird_future_status"])
    def test_env_unknown_status_is_ambiguous_without_success_rendering(self, sandbox, status):
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="partial", stderr="", exit_code=0, status=status)))

        out = sandbox.execute_command("unsafe-to-repeat", env={"TOKEN": "secret"})

        assert sandbox._client.bash.exec.call_count == 1
        assert f"unexpected status '{status}'" in out
        assert "outcome is unknown" in out
        assert "not retried" in out
        assert "Exit Code:" not in out

    def test_env_command_keeps_fresh_bash_exec_semantics(self, sandbox):
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr="", exit_code=0)))

        assert (
            sandbox.execute_command_in_scope(
                "echo $TOKEN",
                env={"TOKEN": "secret"},
                scope_id="subagent-a",
            )
            == "ok"
        )
        sandbox._client.bash.exec.assert_called_once()
        session_id = sandbox._client.bash.create_session.call_args.kwargs["session_id"]
        assert sandbox._client.bash.exec.call_args.kwargs["session_id"] == session_id
        sandbox._client.bash.close_session.assert_called_once_with(
            session_id,
            request_options={
                "timeout_in_seconds": sandbox._CLEANUP_REQUEST_TIMEOUT_SECONDS,
                "max_retries": 0,
            },
        )
        sandbox._client.shell.create_session.assert_not_called()
        assert sandbox._scoped_shell_sessions == {}

    def test_env_session_cleanup_failure_does_not_mask_command_output(self, sandbox):
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr="", exit_code=0)))
        sandbox._client.bash.close_session = MagicMock(side_effect=RuntimeError("cleanup failed"))

        assert sandbox.execute_command("echo $TOKEN", env={"TOKEN": "secret"}) == "ok"

    def test_missing_session_with_failed_replacement_does_not_execute_third_time(self, sandbox):
        from agent_sandbox.core.api_error import ApiError

        executions = 0

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            if executions == 1:
                raise ApiError(
                    status_code=404,
                    body={"message": "session not found while executing command"},
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="'ErrorObservation' object has no attribute 'exit_code'",
                    exit_code=None,
                )
            )

        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.create_session = lambda id, **kwargs: SimpleNamespace(data=SimpleNamespace(session_id=id))

        result = sandbox.execute_command_in_scope("unsafe-to-repeat", scope_id="subagent-a")

        assert "ErrorObservation" in result
        assert executions == 2
        assert sandbox._scoped_shell_sessions["subagent-a"].session_id is None

    def test_closed_sandbox_rejects_new_scope_without_leaking_session(self, sandbox):
        client = sandbox._client

        sandbox.close()

        assert sandbox.execute_command_in_scope("echo late", scope_id="subagent-late") == "Error: sandbox client is closed"
        assert sandbox._scoped_shell_sessions == {}
        client.shell.create_session.assert_not_called()


class TestBashExecUnsupportedFailFast:
    """Regression tests for #3921: sandbox images older than all-in-one-sandbox
    1.9.x have no ``/v1/bash/exec`` route, so every env-bearing command (skills
    declaring ``required-secrets``) hit a bare nginx 404 that the model kept
    retrying. The sandbox must fail fast with an actionable, operator-facing
    error instead."""

    def _api_error_404(self):
        from agent_sandbox.core.api_error import ApiError

        return ApiError(
            headers={"server": "nginx/1.18.0 (Ubuntu)"},
            status_code=404,
            body={"success": False, "message": "Not Found", "data": None},
        )

    def test_bash_exec_404_returns_actionable_error(self, sandbox):
        """A 404 from bash.exec must explain the image capability gap and the
        remediation (upgrade image), not surface the raw nginx error."""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())

        out = sandbox.execute_command("echo $TOK", env={"TOK": "secret-v"})

        assert out.startswith("Error:")
        # Actionable: names the missing capability and the minimum image version.
        assert "/v1/bash/exec" in out
        assert "1.9.3" in out
        assert "required-secrets" in out
        # Not the raw upstream 404 body the model can't act on.
        assert "nginx" not in out

    def test_bash_exec_404_is_cached_and_stops_retry_storm(self, sandbox):
        """After one 404 the capability gap is remembered on the instance:
        follow-up env-bearing calls return the same actionable error without
        another HTTP round-trip (the original bug produced 4 consecutive 404s
        as the model retried variants of the command)."""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert sandbox._client.bash.exec.call_count == 1
        assert first == second
        assert "1.9.3" in second

    def test_bash_exec_non_404_error_is_not_cached(self, sandbox):
        """Transient failures (e.g. 500) must not permanently disable the env
        path — the next env-bearing call should try bash.exec again."""
        from agent_sandbox.core.api_error import ApiError

        sandbox._client.bash.exec = MagicMock(side_effect=ApiError(status_code=500, body="boom"))

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert sandbox._client.bash.exec.call_count == 2
        assert first.startswith("Error:")
        assert "1.9.3" not in first
        assert second.startswith("Error:")

    def test_env_less_path_unaffected_after_404(self, sandbox):
        """The legacy persistent-shell path must keep working on an image
        without bash.exec — only env injection is unavailable there."""
        sandbox._client.bash.exec = MagicMock(side_effect=self._api_error_404())
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="plain ok")))

        sandbox.execute_command("cmd", env={"TOK": "v"})
        out = sandbox.execute_command("echo plain")

        assert out == "plain ok"
        sandbox._client.shell.exec_command.assert_called_once()

    def test_bash_exec_success_does_not_mark_unsupported(self, sandbox):
        """A healthy bash.exec keeps the env path fully enabled."""
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None)))

        first = sandbox.execute_command("cmd-1", env={"TOK": "v"})
        second = sandbox.execute_command("cmd-2", env={"TOK": "v"})

        assert first == "ok"
        assert second == "ok"
        assert sandbox._client.bash.exec.call_count == 2

    def test_bash_exec_missing_session_retries_without_latching_unsupported(self, sandbox):
        """A transient loss after explicit creation must retry once and keep the
        capability enabled for subsequent env-bearing commands."""
        from agent_sandbox.core.api_error import ApiError

        missing = ApiError(status_code=404, body={"message": "Session not found: transient"})
        sandbox._client.bash.exec = MagicMock(side_effect=[missing, SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None))])

        assert sandbox.execute_command("cmd", env={"TOK": "v"}) == "ok"
        assert sandbox._bash_exec_unsupported is False
        assert sandbox._client.bash.exec.call_count == 2
        assert sandbox._client.bash.create_session.call_count == 2

    def test_bash_exec_repeated_missing_session_does_not_latch_capability_gap(self, sandbox):
        from agent_sandbox.core.api_error import ApiError

        missing = ApiError(status_code=404, body={"message": "Session not found"})
        sandbox._client.bash.exec = MagicMock(side_effect=missing)

        out = sandbox.execute_command("cmd", env={"TOK": "v"})

        assert out == "Error: bash.exec session disappeared after retry"
        assert sandbox._bash_exec_unsupported is False
        assert sandbox._client.bash.exec.call_count == 2


class TestListDirSerialization:
    """Verify that list_dir also acquires the lock."""

    def test_list_dir_uses_lock(self, sandbox):
        """list_dir should hold the lock during execution."""
        lock_was_held = []

        original_exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/a\n/b\n\n__DF_FIND_STATUS__:0\n", exit_code=0)))

        def tracking_exec(command, **kwargs):
            lock_was_held.append(sandbox._lock.locked())
            return original_exec(command, **kwargs)

        sandbox._client.shell.exec_command = tracking_exec

        result = sandbox.list_dir("/test")
        assert result == ["/a", "/b"]
        assert lock_was_held == [True], "list_dir must hold the lock during exec_command"

    def test_list_dir_raises_when_exec_fails(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(side_effect=RuntimeError("sandbox down"))

        with pytest.raises(OSError, match="Failed to list directory"):
            sandbox.list_dir("/test")

    @pytest.mark.parametrize("marker, error", [("missing", FileNotFoundError), ("1", OSError)])
    def test_list_dir_classifies_empty_failure(self, sandbox, marker, error):
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output=f"\n__DF_FIND_STATUS__:{marker}\n", exit_code=1)))

        with pytest.raises(error) as exc:
            sandbox.list_dir("/missing")
        assert type(exc.value) is error

    def test_list_dir_raises_oserror_when_result_data_is_none(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=None))

        with pytest.raises(OSError, match="Failed to list directory"):
            sandbox.list_dir("/test")

    def test_list_dir_raises_oserror_when_find_exit_is_not_missing_path(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="", exit_code=127)))

        with pytest.raises(OSError, match="exited with code 127"):
            sandbox.list_dir("/test")

    def test_list_dir_uses_find_H(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/test\n\n__DF_FIND_STATUS__:0\n", exit_code=0)))

        sandbox.list_dir("/test")

        command = sandbox._client.shell.exec_command.call_args.kwargs["command"]
        assert "find -H " in command
        assert "\\( -type f -o -type d \\)" in command

    def test_list_dir_uses_recovery_session_after_ambiguous_command(self, sandbox):
        created_ids = []
        exec_calls = []

        def create_session(id, **kwargs):
            created_ids.append(id)
            return SimpleNamespace(data=SimpleNamespace(session_id=id))

        def exec_command(command, **kwargs):
            exec_calls.append(kwargs)
            if len(exec_calls) == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="partial",
                        exit_code=None,
                        status="no_change_timeout",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="/a\n\n__DF_FIND_STATUS__:0\n",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.create_session = create_session
        sandbox._client.shell.exec_command = exec_command

        command_result = sandbox.execute_command("quiet-command", timeout=3)
        listing = sandbox.list_dir("/test")

        assert "may still be running" in command_result
        assert sandbox._default_shell_corrupted is True
        assert listing == ["/a"]
        assert len(created_ids) == 1
        assert exec_calls[0].get("id") is None
        assert exec_calls[1]["id"] == created_ids[0]
        assert sandbox._recovery_session_id == created_ids[0]

    def test_list_dir_reuses_existing_recovery_session(self, sandbox):
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = "recovery-session"
        sandbox._client.shell.create_session = MagicMock()
        sandbox._client.shell.exec_command = MagicMock(
            return_value=SimpleNamespace(
                data=SimpleNamespace(
                    output="/a\n\n__DF_FIND_STATUS__:0\n",
                    exit_code=0,
                    status="completed",
                )
            )
        )

        assert sandbox.list_dir("/test") == ["/a"]

        kwargs = sandbox._client.shell.exec_command.call_args.kwargs
        assert kwargs["id"] == "recovery-session"
        sandbox._client.shell.create_session.assert_not_called()

    def test_list_dir_keeps_healthy_implicit_shell(self, sandbox):
        sandbox._client.shell.create_session = MagicMock()
        sandbox._client.shell.exec_command = MagicMock(
            return_value=SimpleNamespace(
                data=SimpleNamespace(
                    output="/a\n\n__DF_FIND_STATUS__:0\n",
                    exit_code=0,
                    status="completed",
                )
            )
        )

        assert sandbox.list_dir("/test") == ["/a"]

        kwargs = sandbox._client.shell.exec_command.call_args.kwargs
        assert "id" not in kwargs
        sandbox._client.shell.create_session.assert_not_called()

    def test_list_dir_keeps_implicit_shell_after_hard_timeout(self, sandbox):
        calls = []

        def exec_command(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    data=SimpleNamespace(
                        output="partial",
                        exit_code=None,
                        status="hard_timeout",
                    )
                )
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="/a\n\n__DF_FIND_STATUS__:0\n",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.exec_command = exec_command
        sandbox._client.shell.create_session = MagicMock()

        command_result = sandbox.execute_command("sleep 30", timeout=3)
        listing = sandbox.list_dir("/test")

        assert "Exit Code: 124" in command_result
        assert listing == ["/a"]
        assert sandbox._default_shell_corrupted is False
        assert "id" not in calls[1]
        sandbox._client.shell.create_session.assert_not_called()

    def test_list_dir_does_not_fall_back_to_implicit_shell_when_recovery_creation_fails(
        self,
        sandbox,
    ):
        sandbox._default_shell_corrupted = True
        sandbox._recovery_session_id = None
        sandbox._client.shell.create_session = MagicMock(side_effect=RuntimeError("session creation failed"))
        sandbox._client.shell.exec_command = MagicMock()

        with pytest.raises(OSError, match="Failed to list directory"):
            sandbox.list_dir("/test")

        assert sandbox._default_shell_corrupted is True
        assert sandbox._recovery_session_id is None
        sandbox._client.shell.exec_command.assert_not_called()


class TestNoChangeTimeout:
    """Verify that no_change_timeout is forwarded to every exec_command call."""

    def test_execute_command_forwards_hard_timeout_and_bounded_request(self, sandbox):
        calls = []

        def exec_command(command, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="ok",
                    exit_code=0,
                    status="completed",
                )
            )

        sandbox._client.shell.exec_command = exec_command

        assert sandbox.execute_command("echo ok", timeout=3) == "ok"

        assert calls == [
            {
                "no_change_timeout": 600,
                "hard_timeout": 3,
                "request_options": {
                    "timeout_in_seconds": 8,
                    "max_retries": 0,
                },
            }
        ]

    @pytest.mark.parametrize(
        ("configured_timeout", "explicit_timeout", "expected_hard_timeout", "expected_request_timeout"),
        [
            (42, None, 42, 47),
            (42.5, None, 42.5, 48),
            (42, 10, 10, 15),
        ],
    )
    def test_execute_command_uses_configured_default_or_explicit_timeout(
        self,
        configured_timeout,
        explicit_timeout,
        expected_hard_timeout,
        expected_request_timeout,
    ):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
            configured_sandbox = AioSandbox(
                id="configured-timeout-sandbox",
                base_url="http://localhost:8080",
                default_command_timeout=configured_timeout,
            )
        configured_sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0, status="completed")))

        configured_sandbox.execute_command("echo ok", timeout=explicit_timeout)

        kwargs = configured_sandbox._client.shell.exec_command.call_args.kwargs
        assert kwargs["hard_timeout"] == expected_hard_timeout
        assert kwargs["request_options"] == {
            "timeout_in_seconds": expected_request_timeout,
            "max_retries": 0,
        }

    @pytest.mark.parametrize("invalid_timeout", [float("nan"), float("inf"), float("-inf"), 0, -1])
    def test_default_command_timeout_must_be_positive_and_finite(self, invalid_timeout):
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
            with pytest.raises(ValueError, match="default_command_timeout must be positive"):
                AioSandbox(
                    id="invalid-timeout-sandbox",
                    base_url="http://localhost:8080",
                    default_command_timeout=invalid_timeout,
                )

    def test_execute_command_without_injected_default_preserves_default_timeout(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="ok", exit_code=0, status="completed")))

        sandbox.execute_command("echo ok")

        kwargs = sandbox._client.shell.exec_command.call_args.kwargs
        assert kwargs["hard_timeout"] == sandbox._DEFAULT_HARD_TIMEOUT
        assert kwargs["request_options"] == {
            "timeout_in_seconds": 605,
            "max_retries": 0,
        }

    def test_execute_command_uses_default_hard_timeout_when_timeout_is_none(self, sandbox):
        sandbox._client.shell.exec_command = MagicMock(
            return_value=SimpleNamespace(
                data=SimpleNamespace(
                    output="ok",
                    exit_code=0,
                    status="completed",
                )
            )
        )

        assert sandbox.execute_command("echo ok") == "ok"

        kwargs = sandbox._client.shell.exec_command.call_args.kwargs
        assert kwargs["hard_timeout"] == sandbox._DEFAULT_HARD_TIMEOUT
        assert kwargs["request_options"]["max_retries"] == 0
        assert kwargs["request_options"]["timeout_in_seconds"] > kwargs["hard_timeout"]

    def test_hard_timeout_is_rendered_as_timeout_without_replay(self, sandbox):
        executions = 0

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=None,
                    status="hard_timeout",
                )
            )

        sandbox._client.shell.exec_command = exec_command

        out = sandbox.execute_command("side-effect; sleep 30", timeout=3)

        assert executions == 1
        assert "partial" in out
        assert "Command timed out after 3 seconds and was terminated." in out
        assert out.endswith("Exit Code: 124")

    def test_hard_timeout_keeps_default_recovery_session(self, sandbox):
        calls = []
        sandbox._default_shell_corrupted = False
        sandbox._recovery_session_id = "recovery-session"
        sandbox._client.shell.exec_command = lambda command, **kwargs: (
            calls.append(kwargs)
            or SimpleNamespace(
                data=SimpleNamespace(
                    output="partial" if len(calls) == 1 else "ok",
                    exit_code=None if len(calls) == 1 else 0,
                    status="hard_timeout" if len(calls) == 1 else "completed",
                )
            )
        )
        sandbox._client.shell.cleanup_session = MagicMock()

        first = sandbox.execute_command("sleep 30", timeout=3)
        second = sandbox.execute_command("echo ok", timeout=3)

        assert "Command timed out after 3 seconds" in first
        assert second == "ok"
        assert [call["id"] for call in calls] == ["recovery-session", "recovery-session"]
        assert sandbox._recovery_session_id == "recovery-session"
        assert sandbox._default_shell_corrupted is False
        sandbox._client.shell.cleanup_session.assert_not_called()

    def test_hard_timeout_keeps_scoped_session(self, sandbox):
        from deerflow.community.aio_sandbox.aio_sandbox import _ScopedShellSession

        calls = []
        sandbox._scoped_shell_sessions["scope"] = _ScopedShellSession(session_id="scoped-session")
        sandbox._client.shell.exec_command = lambda command, **kwargs: (
            calls.append(kwargs)
            or SimpleNamespace(
                data=SimpleNamespace(
                    output="partial" if len(calls) == 1 else "ok",
                    exit_code=None if len(calls) == 1 else 0,
                    status="hard_timeout" if len(calls) == 1 else "completed",
                )
            )
        )
        sandbox._client.shell.cleanup_session = MagicMock()

        first = sandbox.execute_command_in_scope("sleep 30", scope_id="scope", timeout=3)
        second = sandbox.execute_command_in_scope("echo ok", scope_id="scope", timeout=3)

        assert "Command timed out after 3 seconds" in first
        assert second == "ok"
        assert [call["id"] for call in calls] == ["scoped-session", "scoped-session"]
        assert sandbox._scoped_shell_sessions["scope"].session_id == "scoped-session"
        assert sandbox._default_shell_corrupted is False
        sandbox._client.shell.cleanup_session.assert_not_called()

    @pytest.mark.parametrize("status", [None, "completed"])
    def test_terminal_statuses_keep_ordinary_exit_code_rendering(self, sandbox, status):
        out = sandbox._render_shell_output(
            "partial",
            7,
            status=status,
            timeout=3,
        )

        assert out == "partial\nExit Code: 7"

    def test_no_change_timeout_is_reported_without_replay(self, sandbox):
        executions = 0
        calls = []

        def exec_command(command, **kwargs):
            nonlocal executions
            executions += 1
            calls.append(kwargs)
            return SimpleNamespace(
                data=SimpleNamespace(
                    output="partial",
                    exit_code=None,
                    status="no_change_timeout",
                )
            )

        sandbox._client.shell.exec_command = exec_command

        out = sandbox.execute_command("quiet-command", timeout=900)

        assert executions == 1
        assert calls[0]["no_change_timeout"] == 905
        assert "no output change" in out
        assert "905 seconds" in out
        assert "may still be running" in out
        assert "Exit Code: 124" not in out

    def test_execute_command_passes_no_change_timeout(self, sandbox):
        """execute_command should pass no_change_timeout to exec_command."""
        calls = []

        def mock_exec(command, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.execute_command("echo hello")

        assert len(calls) == 1
        assert calls[0].get("no_change_timeout") == 605

    def test_retry_passes_no_change_timeout(self, sandbox):
        """The ErrorObservation retry path should also pass no_change_timeout."""
        calls = []

        def mock_exec(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(data=SimpleNamespace(output="'ErrorObservation' object has no attribute 'exit_code'"))
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.execute_command("echo hello")

        assert len(calls) == 2
        assert calls[0].get("no_change_timeout") == 605
        assert calls[1].get("no_change_timeout") == 605

    def test_list_dir_passes_no_change_timeout(self, sandbox):
        """list_dir should pass no_change_timeout to exec_command."""
        calls = []

        def mock_exec(command, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="/a\n/b\n\n__DF_FIND_STATUS__:0\n", exit_code=0))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.list_dir("/test")

        assert len(calls) == 1
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT


class TestReadFile:
    def test_read_file_forwards_requested_line_range(self, sandbox):
        sandbox._client.file.read_file = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(content="line 1\nline 2")))

        result = sandbox.read_file("/mnt/user-data/workspace/huge.log", start_line=1, end_line=10)

        assert result == "line 1\nline 2"
        sandbox._client.file.read_file.assert_called_once_with(
            file="/mnt/user-data/workspace/huge.log",
            start_line=0,
            end_line=10,
        )


class TestWriteFile:
    def test_append_uses_server_append_without_pre_read(self, sandbox):
        sandbox._client.file.read_file = MagicMock(side_effect=RuntimeError("read timed out"))
        sandbox._client.file.write_file = MagicMock()

        sandbox.write_file("/mnt/user-data/workspace/report.txt", "tail", append=True)

        sandbox._client.file.read_file.assert_not_called()
        sandbox._client.file.write_file.assert_called_once_with(
            file="/mnt/user-data/workspace/report.txt",
            content="tail",
            append=True,
        )

    def test_overwrite_keeps_existing_request_shape(self, sandbox):
        sandbox._client.file.write_file = MagicMock()

        sandbox.write_file("/mnt/user-data/workspace/report.txt", "replacement")

        sandbox._client.file.write_file.assert_called_once_with(
            file="/mnt/user-data/workspace/report.txt",
            content="replacement",
        )


class TestConcurrentFileWrites:
    """Verify file write paths do not lose concurrent updates."""

    def test_append_should_preserve_both_parallel_writes(self, sandbox):
        storage = {"content": "seed\n"}
        state_lock = threading.Lock()

        def write_back(*, file, content, append=False, **kwargs):
            with state_lock:
                if append:
                    storage["content"] += content
                else:
                    storage["content"] = content
            return SimpleNamespace(data=SimpleNamespace())

        sandbox.read_file = MagicMock(side_effect=AssertionError("native append must not pre-read"))
        sandbox._client.file.write_file = write_back

        barrier = threading.Barrier(2)

        def writer(payload: str):
            barrier.wait()
            sandbox.write_file("/tmp/shared.log", payload, append=True)

        threads = [
            threading.Thread(target=writer, args=("A\n",)),
            threading.Thread(target=writer, args=("B\n",)),
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert storage["content"] in {"seed\nA\nB\n", "seed\nB\nA\n"}


class TestDownloadFile:
    """Tests for AioSandbox.download_file."""

    def test_returns_concatenated_bytes(self, sandbox):
        """download_file should join chunks from the client iterator into bytes."""
        sandbox._client.file.download_file = MagicMock(return_value=[b"hel", b"lo"])

        result = sandbox.download_file("/mnt/user-data/outputs/file.bin")

        assert result == b"hello"
        sandbox._client.file.download_file.assert_called_once_with(path="/mnt/user-data/outputs/file.bin")

    def test_returns_empty_bytes_for_empty_file(self, sandbox):
        """download_file should return b'' when the iterator yields nothing."""
        sandbox._client.file.download_file = MagicMock(return_value=iter([]))

        result = sandbox.download_file("/mnt/user-data/outputs/empty.bin")

        assert result == b""

    def test_uses_lock_during_download(self, sandbox):
        """download_file should hold the lock while calling the client."""
        lock_was_held = []

        def tracking_download(path):
            lock_was_held.append(sandbox._lock.locked())
            return iter([b"data"])

        sandbox._client.file.download_file = tracking_download

        sandbox.download_file("/mnt/user-data/outputs/file.bin")

        assert lock_was_held == [True], "download_file must hold the lock during client call"

    def test_raises_oserror_on_client_error(self, sandbox):
        """download_file should wrap client exceptions as OSError."""
        sandbox._client.file.download_file = MagicMock(side_effect=RuntimeError("network error"))

        with pytest.raises(OSError, match="network error"):
            sandbox.download_file("/mnt/user-data/outputs/file.bin")

    def test_preserves_oserror_from_client(self, sandbox):
        """OSError raised by the client should propagate without re-wrapping."""
        sandbox._client.file.download_file = MagicMock(side_effect=OSError("disk error"))

        with pytest.raises(OSError, match="disk error"):
            sandbox.download_file("/mnt/user-data/outputs/file.bin")

    def test_rejects_path_outside_virtual_prefix_and_logs_error(self, sandbox, caplog):
        """download_file must reject downloads outside /mnt/user-data and log the reason."""
        sandbox._client.file.download_file = MagicMock()

        with caplog.at_level("ERROR"):
            with pytest.raises(PermissionError, match="must be under"):
                sandbox.download_file("/etc/passwd")

        assert "outside allowed directory" in caplog.text
        sandbox._client.file.download_file.assert_not_called()

    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/workspace/../../etc/passwd",
            "../secret",
            "/a/b/../../../etc/shadow",
        ],
    )
    def test_rejects_path_traversal(self, sandbox, path):
        """download_file must reject paths containing '..' before calling the client."""
        sandbox._client.file.download_file = MagicMock()

        with pytest.raises(PermissionError, match="path traversal"):
            sandbox.download_file(path)

        sandbox._client.file.download_file.assert_not_called()

    def test_single_chunk(self, sandbox):
        """download_file should work correctly with a single-chunk response."""
        sandbox._client.file.download_file = MagicMock(return_value=[b"single-chunk"])

        result = sandbox.download_file("/mnt/user-data/outputs/single.bin")

        assert result == b"single-chunk"


class TestClose:
    """Verify AioSandbox.close() tears down the host-side HTTP client (#2872)."""

    def test_close_calls_real_nested_httpx_client(self, sandbox):
        """close() must close the real httpx.Client at the bottom of the chain.

        Mirrors the actual Fern structure:
            Sandbox._client_wrapper.httpx_client  -> Fern HttpClient (no close())
                .httpx_client                     -> httpx.Client    (the real owner)

        The intermediate HttpClient deliberately exposes NO close(), so a naive
        one-level lookup (the original bug) would silently close nothing.
        """
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)  # no close on this layer
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()

        real_httpx.close.assert_called_once_with()

    def test_close_clears_client_reference(self, sandbox):
        """After close(), the client reference must be dropped (use-after-close safety)."""
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()

        assert sandbox._client is None
        assert sandbox._closed is True

    def test_close_is_idempotent(self, sandbox):
        """Calling close() multiple times must close the underlying client at most once."""
        real_httpx = MagicMock(spec=["close"])
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        sandbox.close()
        sandbox.close()
        sandbox.close()

        assert real_httpx.close.call_count == 1

    def test_close_swallows_exceptions(self, sandbox, caplog):
        """close() must be best-effort: client errors are logged but never raised."""
        real_httpx = MagicMock(spec=["close"])
        real_httpx.close.side_effect = RuntimeError("teardown boom")
        fern_http = SimpleNamespace(httpx_client=real_httpx)
        sandbox._client._client_wrapper = SimpleNamespace(httpx_client=fern_http)

        with caplog.at_level("WARNING"):
            sandbox.close()

        assert "Error closing AioSandbox client" in caplog.text

    def test_close_falls_back_to_client_close(self, sandbox):
        """If no nested httpx.Client is reachable, close() degrades to the client's own close()."""
        # Replace the mocked client with a stub that exposes only top-level close()
        client = MagicMock(spec=["close"])
        sandbox._client = client

        sandbox.close()

        client.close.assert_called_once_with()

    def test_close_when_no_close_attr_does_not_raise(self, sandbox):
        """A client without any close attribute must not crash close()."""
        sandbox._client = SimpleNamespace()  # no close, no _client_wrapper
        sandbox.close()  # must not raise
        assert sandbox._client is None


def test_list_dir_preserves_trailing_space_in_filename(sandbox):
    """ "notes.txt " (trailing space) is a legal Linux filename; find prints it
    verbatim, one entry per line, so a per-line strip() corrupts the name."""
    sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/test/notes.txt \n/test/sub\n\n__DF_FIND_STATUS__:0\n", exit_code=0)))

    assert sandbox.list_dir("/test") == ["/test/notes.txt ", "/test/sub"]
