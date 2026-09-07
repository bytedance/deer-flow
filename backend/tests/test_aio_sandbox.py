"""Tests for AioSandbox concurrent command serialization (#1433)."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


class TestScopedShellSessions:
    """Concurrent subagents use independent persistent shell sessions (#5128)."""

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
        sandbox._client.shell.create_session.assert_not_called()
        assert sandbox._scoped_shell_sessions == {}

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


class TestListDirSerialization:
    """Verify that list_dir also acquires the lock."""

    def test_list_dir_uses_lock(self, sandbox):
        """list_dir should hold the lock during execution."""
        lock_was_held = []

        original_exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/a\n/b")))

        def tracking_exec(command, **kwargs):
            lock_was_held.append(sandbox._lock.locked())
            return original_exec(command, **kwargs)

        sandbox._client.shell.exec_command = tracking_exec

        result = sandbox.list_dir("/test")
        assert result == ["/a", "/b"]
        assert lock_was_held == [True], "list_dir must hold the lock during exec_command"


class TestNoChangeTimeout:
    """Verify that no_change_timeout is forwarded to every exec_command call."""

    def test_execute_command_passes_no_change_timeout(self, sandbox):
        """execute_command should pass no_change_timeout to exec_command."""
        calls = []

        def mock_exec(command, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

        sandbox._client.shell.exec_command = mock_exec

        sandbox.execute_command("echo hello")

        assert len(calls) == 1
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT

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
        assert calls[0].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT
        assert calls[1].get("no_change_timeout") == sandbox._DEFAULT_NO_CHANGE_TIMEOUT

    def test_list_dir_passes_no_change_timeout(self, sandbox):
        """list_dir should pass no_change_timeout to exec_command."""
        calls = []

        def mock_exec(command, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=SimpleNamespace(output="/a\n/b"))

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


class TestConcurrentFileWrites:
    """Verify file write paths do not lose concurrent updates."""

    def test_append_should_preserve_both_parallel_writes(self, sandbox):
        storage = {"content": "seed\n"}
        active_reads = 0
        state_lock = threading.Lock()
        overlap_detected = threading.Event()

        def overlapping_read_file(path):
            nonlocal active_reads
            with state_lock:
                active_reads += 1
                snapshot = storage["content"]
                if active_reads == 2:
                    overlap_detected.set()

            overlap_detected.wait(0.05)

            with state_lock:
                active_reads -= 1

            return snapshot

        def write_back(*, file, content, **kwargs):
            storage["content"] = content
            return SimpleNamespace(data=SimpleNamespace())

        sandbox.read_file = overlapping_read_file
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
    sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="/test/notes.txt \n/test/sub\n")))

    assert sandbox.list_dir("/test") == ["/test/notes.txt ", "/test/sub"]
