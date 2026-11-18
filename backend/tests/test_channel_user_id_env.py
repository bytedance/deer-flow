"""Tests for exposing caller identity to sandbox commands (#3914, #3919).

Two halves:
- Gateway: only an internally authenticated caller's top-level ``body.context``
  may supply ``channel_user_id``; free-form RunnableConfig values are cleared.
- Sandbox: ``bash_tool`` exposes both identities as fixed env vars via an
  ``export`` prefix on the command string — ``DEERFLOW_CHANNEL_USER_ID`` for the
  IM platform sender (#3914) and ``DEERFLOW_USER_ID`` for the authenticated
  DeerFlow user (#3919). Neither must ride the ``env=`` parameter: on
  ``AioSandbox`` a non-empty env switches execution to the ``bash.exec`` API,
  which requires image >= 1.9.3 and abandons the persistent shell session —
  that channel is reserved for request-scoped secrets.

The two differ in applicability: the channel id is absent for non-IM runs so
its prefix is skipped, whereas the user id always resolves (falling back to
``default``) so its prefix is always emitted, and it comes first.
"""

from types import SimpleNamespace

from deerflow.sandbox.tools import (
    CHANNEL_USER_ID_ENV,
    USER_ID_ENV,
    _channel_identity_prefix,
    _user_identity_prefix,
    bash_tool,
)

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}

# Pinned so expected command strings do not depend on whichever identity the
# ambient test fixture happens to install.
_USER_ID = "u-test"
_USER_PREFIX = f"export {USER_ID_ENV}={_USER_ID}; "


def _aio_runtime(context: dict) -> SimpleNamespace:
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio-sandbox-1"}, "thread_data": _THREAD_DATA.copy()},
        context={"user_id": _USER_ID, **context},
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
        assert sandbox.calls[0]["command"] == f"{_USER_PREFIX}export {CHANNEL_USER_ID_ENV}=ou_feishu_123; cd /mnt/user-data/workspace; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_no_channel_user_id_omits_identity_prefix(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        # The user id is always present, so only the channel half is skipped.
        assert sandbox.calls[0]["command"] == f"{_USER_PREFIX}cd /mnt/user-data/workspace; echo hi"
        assert CHANNEL_USER_ID_ENV not in sandbox.calls[0]["command"]
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
        assert _USER_PREFIX + "export " + CHANNEL_USER_ID_ENV + "='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; cd /mnt/user-data/workspace; echo hi" == command

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
        assert call["command"] == f"{_USER_PREFIX}export {CHANNEL_USER_ID_ENV}=ou_1; cd /mnt/user-data/workspace; echo hi"
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

        assert a.calls[0]["command"] == f"{_USER_PREFIX}export {CHANNEL_USER_ID_ENV}=sender-a; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["command"] == f"{_USER_PREFIX}unset {CHANNEL_USER_ID_ENV}; cd /mnt/user-data/workspace; echo hi"
        assert b.calls[0]["env"] is None

    def test_windows_local_sandbox_skips_prefix(self, monkeypatch):
        """On Windows the local sandbox may execute via PowerShell/cmd.exe where
        POSIX ``export`` is not valid syntax — skip injection rather than break
        every IM-channel command."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1", "user_id": _USER_ID},
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
            context={"channel_user_id": "ou_1", "thread_id": "t1", "user_id": _USER_ID},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: False)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        command = sandbox.calls[0]["command"]
        assert command.startswith(f"{_USER_PREFIX}export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert command.endswith("echo hi")


class TestBashToolUserIdentityPrefix:
    """#3919 — the authenticated user id is published to every bash command."""

    def test_user_id_exported_and_env_stays_none(self, monkeypatch):
        """The id rides the command string; env must stay None so AioSandbox
        keeps the persistent-shell path (same reason as the channel id)."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"] == f"{_USER_PREFIX}cd /mnt/user-data/workspace; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_prefix_emitted_even_without_an_explicit_user(self, monkeypatch):
        """A run that carries no ``user_id`` still resolves one (``default``), so
        the variable is always defined rather than silently absent."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "aio-sandbox-1"}, "thread_data": _THREAD_DATA.copy()},
            context={"thread_id": "t1"},
        )
        sandbox = _run_bash(monkeypatch, runtime)

        assert sandbox.calls[0]["command"].startswith(f"export {USER_ID_ENV}=")

    def test_user_prefix_precedes_channel_prefix(self, monkeypatch):
        """Both are POSIX exports; the user id is the outer one, so a reader sees
        which user the command runs as before which IM sender it came from."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "ou_1"}))

        command = sandbox.calls[0]["command"]
        assert command.startswith(_USER_PREFIX)
        assert command.index(USER_ID_ENV) < command.index(CHANNEL_USER_ID_ENV)

    def test_value_is_shell_quoted(self, monkeypatch):
        """A hostile user id must not be able to inject shell syntax."""
        sandbox = _run_bash(monkeypatch, _aio_runtime({"user_id": "x'; rm -rf /tmp/y; '"}))

        command = sandbox.calls[0]["command"]
        assert command.endswith("; cd /mnt/user-data/workspace; echo hi")
        assert "export " + USER_ID_ENV + "='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; cd /mnt/user-data/workspace; echo hi" == command

    def test_unusable_value_emits_unset_not_none(self, monkeypatch):
        """A corrupt id must clear the variable rather than skip the prefix, so a
        command cannot inherit a stale value from a reused shell session."""
        for bad in ("", 123, "x" * 5000, None):
            monkeypatch.setattr(
                "deerflow.sandbox.tools.resolve_runtime_user_id",
                lambda runtime, _bad=bad: _bad,
            )
            prefix = _user_identity_prefix(SimpleNamespace(context={}))
            assert prefix == f"unset {USER_ID_ENV}; ", f"value={bad!r}"

    def test_composes_with_channel_prefix_and_secrets(self, monkeypatch):
        """Secrets keep the env= channel; both identities keep the command-string
        channel. They must not mix."""
        runtime = _aio_runtime(
            {
                "channel_user_id": "ou_1",
                "__active_skill_secrets": {"ERP_TOKEN": "secret-value"},
            }
        )
        sandbox = _run_bash(monkeypatch, runtime)

        call = sandbox.calls[0]
        assert call["env"] == {"ERP_TOKEN": "secret-value"}
        assert call["command"] == f"{_USER_PREFIX}export {CHANNEL_USER_ID_ENV}=ou_1; cd /mnt/user-data/workspace; echo hi"
        assert "secret-value" not in call["command"]

    def test_posix_local_sandbox_gets_user_prefix(self, monkeypatch):
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"thread_id": "t1", "user_id": _USER_ID},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: False)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"].startswith(_USER_PREFIX)

    def test_windows_local_sandbox_publishes_user_id_via_env(self, monkeypatch):
        """POSIX ``export`` is invalid under the Windows local sandbox, so the id
        moves to the ``env`` channel there rather than being dropped: the
        contract is that every bash command can see the user id."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"thread_id": "t1", "user_id": _USER_ID},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        call = sandbox.calls[0]
        assert USER_ID_ENV not in call["command"]
        assert "export" not in call["command"]
        assert call["env"] == {USER_ID_ENV: _USER_ID}

    def test_windows_env_channel_keeps_secrets_and_user_id_separate(self, monkeypatch):
        """Secrets stay in ``env`` for redaction; the id rides alongside them
        without entering the redaction set, so echoing it stays readable."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={
                "thread_id": "t1",
                "user_id": _USER_ID,
                "__active_skill_secrets": {"ERP_TOKEN": "secret-value"},
            },
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert sandbox.calls[0]["env"] == {"ERP_TOKEN": "secret-value", USER_ID_ENV: _USER_ID}

    def test_windows_local_sandbox_omits_unusable_user_id(self, monkeypatch):
        """A corrupt id is dropped rather than published — there is no portable
        way to clear a variable across PowerShell/cmd/MSYS, so the env channel
        carries nothing instead of carrying garbage."""
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"thread_id": "t1", "user_id": "x" * 5000},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("deerflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert sandbox.calls[0]["env"] is None
