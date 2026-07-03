"""Tests for exposing the IM-channel platform user id to sandbox commands (#3914).

Two halves:
- Gateway: ``merge_run_context_overrides`` forwards ``channel_user_id`` from
  ``body.context`` into ``config['context']`` (runtime context) only — never
  into ``configurable`` (which is checkpointed).
- Sandbox: ``bash_tool`` exposes the id as the fixed env var
  ``DEERFLOW_CHANNEL_USER_ID`` via an ``export`` prefix on the command string.
  It must NOT ride the ``env=`` parameter: on ``AioSandbox`` a non-empty env
  switches execution to the ``bash.exec`` API, which requires image >= 1.9.3
  and abandons the persistent shell session — that channel is reserved for
  request-scoped secrets.
"""

from types import SimpleNamespace

from deerflow.sandbox.tools import (
    CHANNEL_USER_ID_ENV,
    _channel_identity_prefix,
    bash_tool,
)

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


def _aio_runtime(context: dict) -> SimpleNamespace:
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio-sandbox-1"}, "thread_data": _THREAD_DATA.copy()},
        context=context,
    )


class _CapturingSandbox:
    def __init__(self, output: str = "ok"):
        self.calls: list[dict] = []
        self._output = output

    def execute_command(self, command: str, env=None, timeout=None) -> str:
        self.calls.append({"command": command, "env": env})
        return self._output


def _run_bash(monkeypatch, runtime, command: str = "echo hi") -> _CapturingSandbox:
    sandbox = _CapturingSandbox()
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    bash_tool.func(runtime=runtime, description="test", command=command)
    return sandbox


class TestMergeRunContextOverridesChannelUserId:
    def test_channel_user_id_propagates_to_runtime_context_only(self):
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        merge_run_context_overrides(config, {"channel_user_id": "ou_feishu_123"})

        assert config["context"]["channel_user_id"] == "ou_feishu_123"
        # Never into configurable: that mapping is checkpointed with the thread.
        assert "channel_user_id" not in config["configurable"]

    def test_existing_runtime_context_value_wins(self):
        """setdefault semantics: a server-side value stamped earlier must not be
        overridden by the client-supplied body.context."""
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        config.setdefault("context", {})["channel_user_id"] = "server-stamped"
        merge_run_context_overrides(config, {"channel_user_id": "client-supplied"})

        assert config["context"]["channel_user_id"] == "server-stamped"

    def test_absent_channel_user_id_adds_nothing(self):
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        merge_run_context_overrides(config, {"model_name": "gpt"})

        assert "channel_user_id" not in config.get("context", {})


class TestBashToolChannelIdentityPrefix:
    def test_identity_exported_and_env_stays_none(self, monkeypatch):
        """The id rides the command string; env must stay None so AioSandbox
        keeps the legacy persistent-shell path (regression guard for the
        #3921/#3922 bash.exec capability gap)."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "ou_feishu_123"}))

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_feishu_123; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_no_channel_user_id_leaves_command_unchanged(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        assert sandbox.calls[0]["command"] == "echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_per_call_identity_follows_current_context(self, monkeypatch):
        """Group chats share one thread/sandbox: each message's run carries that
        sender's id, so consecutive commands must each export their own value."""
        first = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        second = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-b"}))

        assert "sender-a" in first.calls[0]["command"]
        assert "sender-b" in second.calls[0]["command"]

    def test_value_is_shell_quoted(self, monkeypatch):
        """A hostile platform id must not be able to inject shell syntax."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "x'; rm -rf /tmp/y; '"}))

        command = sandbox.calls[0]["command"]
        assert command.endswith("; echo hi")
        # shlex.quote wraps the value; the raw injection payload must not appear
        # as executable syntax outside the quoted region.
        assert "export " + CHANNEL_USER_ID_ENV + "='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; echo hi" == command

    def test_secrets_and_identity_compose(self, monkeypatch):
        """Active skill secrets keep the env= channel; the identity keeps the
        command-string channel. They must not mix."""
        runtime = _aio_runtime(
            {
                "channel_user_id": "ou_1",
                "__active_skill_secrets": {"ERP_TOKEN": "secret-value"},
            }
        )
        sandbox = _run_bash(monkeypatch, runtime)

        call = sandbox.calls[0]
        assert call["env"] == {"ERP_TOKEN": "secret-value"}
        assert call["command"].startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert "secret-value" not in call["command"]

    def test_non_string_or_empty_values_are_ignored(self):
        assert _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": ""})) is None
        assert _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": 123})) is None
        assert _channel_identity_prefix(SimpleNamespace(context=None)) is None

    def test_overlong_value_is_ignored(self):
        """body.context is client-writable on web requests; a pathological value
        must not bloat every command sent to the sandbox. Real platform ids are
        well under the cap."""
        assert _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": "x" * 5000})) is None

    def test_windows_local_sandbox_skips_prefix(self, monkeypatch):
        """On Windows the local sandbox may execute via PowerShell/cmd.exe where
        POSIX ``export`` is not valid syntax — skip injection rather than break
        every IM-channel command."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        assert "export" not in sandbox.calls[0]["command"]

    def test_posix_local_sandbox_gets_prefix(self, monkeypatch):
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        command = sandbox.calls[0]["command"]
        assert command.startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert command.endswith("echo hi")
