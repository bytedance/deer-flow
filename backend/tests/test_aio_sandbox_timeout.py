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
