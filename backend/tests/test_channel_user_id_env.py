"""Tests for exposing the IM-channel platform user id to sandbox commands (#3914).

Two halves:
- Gateway: only an internally authenticated caller's top-level ``body.context``
  may supply ``channel_user_id``; free-form RunnableConfig values are cleared.
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


class TestGatewayChannelUserIdTrustBoundary:
    @staticmethod
    def _request(auth_source: str):
        return SimpleNamespace(
            state=SimpleNamespace(
                auth_source=auth_source,
                user=SimpleNamespace(id="u1", system_role="user"),
            )
        )

    def test_internal_channel_user_id_propagates_to_runtime_context_only(self):
        from app.gateway.services import build_run_config, inject_authenticated_user_context

        config = build_run_config("thread-1", None, None)
        inject_authenticated_user_context(
            config,
            self._request("internal"),
            request_context={"channel_user_id": "ou_feishu_123"},
        )

        assert config["context"]["channel_user_id"] == "ou_feishu_123"
        # Never into configurable: that mapping is checkpointed with the thread.
        assert "channel_user_id" not in config["configurable"]

    def test_free_form_config_value_cannot_override_internal_sender(self):
        from app.gateway.services import build_run_config, inject_authenticated_user_context

        config = build_run_config(
            "thread-1",
            {"context": {"channel_user_id": "forged-config-sender"}},
            None,
        )
        inject_authenticated_user_context(
            config,
            self._request("internal"),
            request_context={"channel_user_id": "trusted-im-sender"},
        )

        assert config["context"]["channel_user_id"] == "trusted-im-sender"

    def test_absent_channel_user_id_adds_nothing(self):
        from app.gateway.services import build_run_config, inject_authenticated_user_context

        config = build_run_config("thread-1", None, None)
        inject_authenticated_user_context(config, self._request("internal"), request_context={"model_name": "gpt"})

        assert "channel_user_id" not in config.get("context", {})


class TestBashToolChannelIdentityPrefix:
    def test_identity_exported_and_env_stays_none(self, monkeypatch):
        """The id rides the command string; env must stay None so AioSandbox
        keeps the legacy persistent-shell path (regression guard for the
        #3921/#3922 bash.exec capability gap)."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "ou_feishu_123"}))

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_feishu_123; cd /mnt/user-data/workspace; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_no_channel_user_id_omits_identity_prefix(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        assert sandbox.calls[0]["command"] == "cd /mnt/user-data/workspace; echo hi"
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
        assert command.endswith("; cd /mnt/user-data/workspace; echo hi")
        # shlex.quote wraps the value; the raw injection payload must not appear
        # as executable syntax outside the quoted region.
        assert "export " + CHANNEL_USER_ID_ENV + "='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; cd /mnt/user-data/workspace; echo hi" == command

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
        assert call["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_1; cd /mnt/user-data/workspace; echo hi"
        assert "secret-value" not in call["command"]

    def test_non_im_run_leaves_command_untouched(self):
        """No channel_user_id key at all → non-IM run → prefix is None so the
        command (the vast majority: Web/API/subagent) is unchanged."""
        assert _channel_identity_prefix(SimpleNamespace(context={"thread_id": "t1"})) is None
        assert _channel_identity_prefix(SimpleNamespace(context={})) is None
        assert _channel_identity_prefix(SimpleNamespace(context=None)) is None

    def test_unusable_value_emits_unset_not_none(self, monkeypatch):
        """An IM run whose id is unusable (empty / non-str / over the cap) must
        emit ``unset`` — not skip the prefix. Skipping would let a bare command
        resolve a stale value left in the AIO persistent shell by an earlier
        sender (willem-bd's group-chat leak window)."""
        for bad in ("", 123, "x" * 5000, None):
            prefix = _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": bad}))
            assert prefix == f"unset {CHANNEL_USER_ID_ENV}; ", f"value={bad!r}"

    def test_group_chat_dropped_id_clears_previous_sender(self, monkeypatch):
        """Sender A (valid) then sender B (over-cap id, dropped): B's command must
        carry ``unset`` so it cannot inherit A's exported id in a shared
        persistent-shell sandbox — per-call correctness independent of session
        persistence."""
        a = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        b = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "b" * 5000}))

        assert a.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=sender-a; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["command"] == f"unset {CHANNEL_USER_ID_ENV}; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["env"] is None

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
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: False)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        command = sandbox.calls[0]["command"]
        assert command.startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert command.endswith("echo hi")
