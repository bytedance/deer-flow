# SPDX-License-Identifier: Apache-2.0
"""AioSandbox must honor the per-call ``timeout`` (#5628): the deadline rides
the SDK ``hard_timeout`` and a timeout status surfaces as a LocalSandbox-style
notice instead of being silently ignored."""

from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox


@pytest.fixture
def sandbox():
    return AioSandbox(id="test-sandbox", base_url="http://localhost:8080")


def _result(output="", status="completed", stdout=None, stderr=""):
    if stdout is not None:
        return SimpleNamespace(data=SimpleNamespace(status=status, stdout=stdout, stderr=stderr))
    return SimpleNamespace(data=SimpleNamespace(status=status, output=output))


class TestExecuteCommandTimeout:
    def test_timeout_rides_hard_timeout_kwarg(self, sandbox):
        calls = []

        def fake_exec(command, **kwargs):
            calls.append(kwargs)
            return _result(output="ok")

        sandbox._client.shell.exec_command = fake_exec
        assert sandbox.execute_command("sleep 1", timeout=3) == "ok"
        assert calls[0]["hard_timeout"] == 3

    def test_no_timeout_keeps_legacy_kwargs(self, sandbox):
        calls = []

        def fake_exec(command, **kwargs):
            calls.append(kwargs)
            return _result(output="ok")

        sandbox._client.shell.exec_command = fake_exec
        sandbox.execute_command("ls")
        assert "hard_timeout" not in calls[0]

    def test_hard_timeout_status_returns_notice(self, sandbox):
        def fake_exec(command, **kwargs):
            return _result(status="hard_timeout", output="")

        sandbox._client.shell.exec_command = fake_exec
        out = sandbox.execute_command("sleep 25", timeout=3)
        assert "timed out after 3 seconds and was terminated" in out

    def test_recovery_retry_carries_the_same_deadline(self, sandbox):
        from deerflow.community.aio_sandbox.aio_sandbox import (
            _ERROR_OBSERVATION_SIGNATURE,
        )

        calls = []

        def fake_exec(command, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return _result(output=_ERROR_OBSERVATION_SIGNATURE)
            return _result(status="hard_timeout", output="")

        sandbox._client.shell.exec_command = fake_exec
        sandbox._client.shell.create_session = lambda **kwargs: None
        sandbox._client.shell.cleanup_session = lambda *a, **k: None

        out = sandbox.execute_command("sleep 25", timeout=5)
        assert "timed out after 5 seconds and was terminated" in out
        assert all(c["hard_timeout"] == 5 for c in calls)


class TestExecuteWithEnvTimeout:
    def _patch_bash(self, sandbox, fake_bash_exec):
        # main's env path opens an explicit transient session per call; the
        # session lifecycle is mocked too, so nothing touches a live sandbox
        sandbox._client.bash.exec = fake_bash_exec
        sandbox._client.bash.create_session = lambda **kwargs: None
        sandbox._client.bash.close_session = lambda *a, **k: None

    def test_env_path_threads_hard_timeout(self, sandbox):
        calls = []

        def fake_bash_exec(command, **kwargs):
            calls.append(kwargs)
            return _result(status="completed", stdout="ok", stderr="")

        self._patch_bash(sandbox, fake_bash_exec)
        out = sandbox.execute_command("env", env={"A": "1"}, timeout=7)
        assert out == "ok"
        assert calls[0]["hard_timeout"] == 7

    def test_env_path_timeout_status_returns_notice(self, sandbox):
        def fake_bash_exec(command, **kwargs):
            return _result(status="timed_out", stdout="", stderr="")

        self._patch_bash(sandbox, fake_bash_exec)
        out = sandbox.execute_command("sleep 25", env={"A": "1"}, timeout=3)
        assert "timed out after 3 seconds and was terminated" in out

    def test_env_path_default_deadline_unchanged(self, sandbox):
        calls = []

        def fake_bash_exec(command, **kwargs):
            calls.append(kwargs)
            return _result(status="completed", stdout="ok", stderr="")

        self._patch_bash(sandbox, fake_bash_exec)
        sandbox.execute_command("env", env={"A": "1"})
        assert calls[0]["hard_timeout"] == sandbox._DEFAULT_HARD_TIMEOUT


class TestTimeoutKeepsPartialOutput:
    def test_shell_path_timeout_keeps_partial_output(self, sandbox):
        def fake_exec(command, **kwargs):
            return _result(status="hard_timeout", output="line one\nline two")

        sandbox._client.shell.exec_command = fake_exec
        out = sandbox.execute_command("sleep 25", timeout=3)
        assert "line one" in out
        assert "timed out after 3 seconds and was terminated" in out
        assert "Exit Code: 124" in out

    def test_env_path_timeout_keeps_partial_streams(self, sandbox):
        sandbox._client.bash.create_session = lambda session_id: None
        sandbox._client.bash.exec = lambda **kwargs: _result(status="timed_out", stdout="half way", stderr="warn")
        sandbox._cleanup_bash_session_best_effort = lambda client, sid: None
        out = sandbox.execute_command("sleep 25", env={"A": "1"}, timeout=3)
        assert "half way" in out
        assert "warn" in out
        assert "Exit Code: 124" in out


class TestUngatedTimeoutStatus:
    def test_hard_timeout_status_without_deadline_renders_normally(self, sandbox):
        # No deadline was passed, so a sandbox-reported hard_timeout is not
        # ours: surface it as ordinary output, not a fabricated timeout notice.
        def fake_exec(command, **kwargs):
            return _result(status="hard_timeout", output="odd")

        sandbox._client.shell.exec_command = fake_exec
        out = sandbox.execute_command("ls")
        assert "timed out" not in out
        assert "odd" in out


class TestScopedPathTimeout:
    def test_scoped_exec_threads_and_reports_timeout(self, sandbox):
        calls = []

        def fake_exec(command, **kwargs):
            calls.append(kwargs)
            return _result(status="hard_timeout", output="partial")

        sandbox._client.shell.exec_command = fake_exec
        sandbox._create_shell_session = lambda client: "sess-1"
        out = sandbox.execute_command_in_scope("sleep 25", timeout=3, scope_id="sub-1")
        assert calls[0]["hard_timeout"] == 3
        assert "partial" in out
        assert "timed out after 3 seconds and was terminated" in out
        assert "Exit Code: 124" in out


def test_bash_tool_remote_branch_forwards_config_timeout(monkeypatch):
    from types import SimpleNamespace as SN
    from unittest.mock import patch

    from deerflow.sandbox import tools as tools_mod

    captured = {}

    class FakeSandbox:
        def execute_command(self, command, env=None, timeout=None):
            captured["timeout"] = timeout
            return "done"

    runtime = SN(context={}, state={"sandbox": {"sandbox_id": "aio:1"}})
    fake_cfg = SN(sandbox=SN(bash_output_max_chars=321, bash_command_timeout=42))
    with (
        patch.object(tools_mod, "ensure_sandbox_initialized", return_value=FakeSandbox()),
        patch.object(tools_mod, "is_local_sandbox", return_value=False),
        patch.object(tools_mod, "ensure_thread_directories_exist", return_value=None),
        patch("deerflow.config.app_config.get_app_config", return_value=fake_cfg),
    ):
        out = tools_mod.bash_tool.func(runtime=runtime, command="echo hi", description="run")

    assert out == "done"
    assert captured["timeout"] == 42
