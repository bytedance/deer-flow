"""Tests for the GitHub App installation-token plumbing.

Covers the end-to-end path that lets a GitHub-driven agent actually push
code and open PRs:

  dispatcher carries ``installation_id`` + a deterministic
  ``preferred_thread_id`` in ``InboundMessage.metadata``
    -> ChannelManager mints an installation token and injects it into
       ``run_context["github_token"]``
    -> the value flows through ``context=`` into ``runtime.context``
    -> the bash tool exposes it as ``GH_TOKEN`` / ``GITHUB_TOKEN`` via a
       per-call ``env`` overlay on ``Sandbox.execute_command``

The per-call overlay (rather than mutating ``os.environ``) is what keeps
concurrent runs on different repos from clobbering each other's token.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from langgraph_sdk.errors import ConflictError

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.channels.store import ChannelStore
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import _github_env_from_runtime, bash_tool


def _make_conflict_error(detail: str = "thread_id already exists") -> ConflictError:
    """Mint a ConflictError that matches what langgraph_sdk would raise on a
    409 from ``POST /threads``. Constructing the SDK error directly requires
    an httpx.Response with an attached Request, so this helper hides the
    boilerplate.
    """
    req = httpx.Request("POST", "http://gateway/api/threads")
    resp = httpx.Response(409, json={"detail": detail}, request=req)
    return ConflictError(detail, response=resp, body={"detail": detail})


# ---------------------------------------------------------------------------
# Sandbox.execute_command env
# ---------------------------------------------------------------------------


def test_local_sandbox_env_overlay_reaches_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """``env`` is layered on top of a sanitized os.environ for the subprocess
    call — inherited benign vars survive, the injected secret wins."""
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    captured: dict = {}

    def fake_run_posix(args, timeout, env=None):
        captured["env"] = env
        return ("", "", 0, False)

    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(fake_run_posix))
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "/bin/bash"))
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": "/usr/bin", "EXISTING": "kept"})

    LocalSandbox("local:t").execute_command("echo $GITHUB_TOKEN", env={"GITHUB_TOKEN": "tok-123"})

    env = captured["env"]
    assert env["GITHUB_TOKEN"] == "tok-123"
    # Inherited vars survive the overlay.
    assert env["EXISTING"] == "kept"


def test_local_sandbox_no_env_passes_sanitized_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``env`` the subprocess still gets a sanitized environ — platform
    secrets are scrubbed (#3861), only benign inherited vars survive."""
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    captured: dict = {}

    def fake_run_posix(args, timeout, env=None):
        captured["env"] = env
        return ("", "", 0, False)

    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(fake_run_posix))
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "/bin/bash"))
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": "/usr/bin", "OPENAI_API_KEY": "sk-leak"})

    LocalSandbox("local:t").execute_command("echo hi")

    env = captured["env"]
    # Platform credentials are scrubbed (#3861) — never inherited by skills.
    assert "OPENAI_API_KEY" not in env
    # Benign vars survive.
    assert env["PATH"] == "/usr/bin"


def test_aio_sandbox_env_routes_through_bash_exec() -> None:
    """Per-call ``env`` is forwarded to the ``bash.exec`` API (structured env
    field on a fresh session) so secrets like ``GITHUB_TOKEN`` reach the
    command without being spliced into the command string. Replaces the old
    persistent-shell ``export … unset`` overlay, which could not keep secrets
    out of the command string.
    """
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    captured: dict = {}

    class _FakeBash:
        def exec(self, *, command, env=None, **kwargs):
            captured["command"] = command
            captured["env"] = env
            return SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None))

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(bash=_FakeBash())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30
    sbx._DEFAULT_HARD_TIMEOUT = 30
    sbx._bash_exec_unsupported = False

    out = sbx.execute_command("gh pr create", env={"GH_TOKEN": "tok-123"})

    assert out == "ok"
    assert captured["command"] == "gh pr create"
    assert captured["env"] == {"GH_TOKEN": "tok-123"}


def test_aio_sandbox_no_env_leaves_command_unchanged() -> None:
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    captured: dict = {}

    class _FakeData:
        output = "ok"

    class _FakeResult:
        data = _FakeData()

    class _FakeShell:
        def exec_command(self, *, command, no_change_timeout=None, **kwargs):
            captured["command"] = command
            return _FakeResult()

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(shell=_FakeShell())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30

    sbx.execute_command("echo hello")

    assert captured["command"] == "echo hello"


# ---------------------------------------------------------------------------
# extra_env key validation (regression pin for willem-bd #5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        # Shell metachar in key — the actual injection vector flagged by
        # the review (would render as `export X;rm -rf /;Y='v'; <cmd>`).
        "X;rm -rf /mnt/user-data;Y",
        "X`whoami`",
        "X$(id)",
        "X&Y",
        "X|Y",
        "X>Y",
        "X<Y",
        "X Y",  # space
        "X\tY",  # tab
        "X\nY",  # newline
        # Leading digit — not a valid POSIX env-var name even though it
        # contains no metacharacters; rejecting these too keeps the rule
        # simple and matches POSIX.
        "1FOO",
        # Empty / whitespace-only.
        "",
        "   ",
        # Non-str keys (a dict can have int keys at runtime).
        123,
    ],
)
def test_extra_env_rejects_invalid_keys(bad_key) -> None:
    """Regression pin for willem-bd's finding #5 on PR #3754.

    The abstract ``Sandbox.execute_command(env=...)`` contract validates
    keys against the POSIX env-var rule ``^[A-Za-z_][A-Za-z0-9_]*$``. Today
    no implementation splices a key into a shell string — the local sandbox
    merges them into ``subprocess.run(env=...)`` (no shell), the AIO sandbox
    forwards them via the ``bash.exec`` structured env field, and e2b
    forwards them as the SDK's ``envs``. The rule is defense-in-depth for
    the contract: future callers deriving a key from config / payload /
    user input fail fast with ``ValueError`` rather than producing a latent
    injection should a future implementation regress to splicing keys into
    a shell command string.

    The same rule applies to all implementations even though none currently
    route a key through a shell — the contract is what matters, not each
    implementation's current escaping rules.
    """
    from deerflow.sandbox.sandbox import _validate_extra_env

    with pytest.raises(ValueError, match="extra_env key"):
        _validate_extra_env({bad_key: "value"})


@pytest.mark.parametrize(
    "good_key",
    [
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "_HIDDEN",
        "foo123",
        "MIXED_case_42",
        "X",
    ],
)
def test_extra_env_accepts_valid_keys(good_key: str) -> None:
    """POSIX env-var names round-trip cleanly."""
    from deerflow.sandbox.sandbox import _validate_extra_env

    # No exception => acceptance.
    _validate_extra_env({good_key: "any value with spaces and $metachars"})


def test_extra_env_none_and_empty_pass_through() -> None:
    """``None`` and empty dicts are the common case — must not raise."""
    from deerflow.sandbox.sandbox import _validate_extra_env

    _validate_extra_env(None)
    _validate_extra_env({})


def test_local_sandbox_rejects_invalid_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a bad key reaches the implementation's ``execute_command``
    and is rejected before any subprocess is spawned.
    """
    import deerflow.sandbox.local.local_sandbox as local_sandbox

    fake_run_called = False

    def fake_run(*args, **kwargs):
        nonlocal fake_run_called
        fake_run_called = True
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(local_sandbox.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="extra_env key"):
        LocalSandbox("local:t").execute_command(
            "echo hi",
            env={"X;rm -rf /mnt/user-data;Y": "v"},
        )
    assert fake_run_called is False, "subprocess.run must not run when key is invalid"


def test_aio_sandbox_rejects_invalid_env_key() -> None:
    """End-to-end on the AIO sandbox path — the injection vector flagged in
    the review never reaches the shell's ``exec_command``.
    """
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    exec_called = False

    class _FakeShell:
        def exec_command(self, *, command, no_change_timeout=None, **kwargs):
            nonlocal exec_called
            exec_called = True
            return SimpleNamespace(data=SimpleNamespace(output="ok"))

    sbx = AioSandbox.__new__(AioSandbox)
    sbx._lock = __import__("threading").Lock()
    sbx._client = SimpleNamespace(shell=_FakeShell())
    sbx._DEFAULT_NO_CHANGE_TIMEOUT = 30

    with pytest.raises(ValueError, match="extra_env key"):
        sbx.execute_command(
            "echo hi",
            env={"X;rm -rf /mnt/user-data;Y": "v"},
        )
    assert exec_called is False, "shell.exec_command must not run when key is invalid"


# ---------------------------------------------------------------------------
# bash_tool token read-through
# ---------------------------------------------------------------------------


def test_github_env_from_runtime_returns_token_pair() -> None:
    runtime = SimpleNamespace(context={"github_token": "tok-abc"})
    env = _github_env_from_runtime(runtime)
    assert env == {"GH_TOKEN": "tok-abc", "GITHUB_TOKEN": "tok-abc"}


def test_github_env_from_runtime_resolves_provider_callable() -> None:
    """A callable in context["github_token"] is invoked per bash call.

    This is the refresh seam: long autonomous github runs that span past
    the 60-minute installation-token TTL need every bash invocation to
    re-ask the provider, which transparently re-mints via the app-side
    cache when the token's leeway tripped.
    """
    calls = {"n": 0}

    def _provider() -> str:
        calls["n"] += 1
        return f"tok-call-{calls['n']}"

    runtime = SimpleNamespace(context={"github_token": _provider})

    env_1 = _github_env_from_runtime(runtime)
    assert env_1 == {"GH_TOKEN": "tok-call-1", "GITHUB_TOKEN": "tok-call-1"}

    env_2 = _github_env_from_runtime(runtime)
    assert env_2 == {"GH_TOKEN": "tok-call-2", "GITHUB_TOKEN": "tok-call-2"}
    assert calls["n"] == 2  # called once per bash invocation


def test_github_env_from_runtime_returns_none_when_provider_raises() -> None:
    """A misbehaving provider must NOT crash the bash tool — it just falls
    back to the no-token path so the run can still execute read-only.
    """

    def _broken() -> str:
        raise RuntimeError("mint failed")

    runtime = SimpleNamespace(context={"github_token": _broken})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_returns_none_when_provider_returns_empty() -> None:
    runtime = SimpleNamespace(context={"github_token": lambda: ""})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_none_when_no_token() -> None:
    runtime = SimpleNamespace(context={"thread_id": "t1"})
    assert _github_env_from_runtime(runtime) is None


def test_github_env_from_runtime_none_when_empty() -> None:
    runtime = SimpleNamespace(context={"github_token": ""})
    assert _github_env_from_runtime(runtime) is None


def test_bash_tool_passes_token_as_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When runtime.context carries github_token, bash forwards it to the sandbox."""
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio:xyz"}},  # non-local -> simpler branch
        context={"thread_id": "t1", "github_token": "tok-from-manager"},
        config={},
    )

    captured: dict = {}

    class _Sandbox:
        def execute_command(self, command, env=None, timeout=None):
            captured["command"] = command
            captured["env"] = env
            return "done"

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = bash_tool.func(runtime=runtime, description="push", command="git push")

    assert "done" in result
    assert captured["env"] == {"GH_TOKEN": "tok-from-manager", "GITHUB_TOKEN": "tok-from-manager"}


def test_bash_tool_no_env_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio:xyz"}},
        context={"thread_id": "t1"},  # no github_token
        config={},
    )

    captured: dict = {}

    class _Sandbox:
        def execute_command(self, command, env=None, timeout=None):
            captured["env"] = env
            return "done"

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    bash_tool.func(runtime=runtime, description="ls", command="ls")
    assert captured["env"] is None


# ---------------------------------------------------------------------------
# ChannelManager._apply_channel_policy — the unified per-channel run-policy
# hook. The github channel registers (is_interactive=False,
# default_recursion_limit=250, credentials_provider=inject_github_credentials,
# requires_bound_identity=False) via CHANNEL_RUN_POLICY; this section
# exercises that one hook for github and the no-op path for unregistered
# channels (Slack, Telegram, …).
# ---------------------------------------------------------------------------


def _github_msg(installation_id: int | None = 140594274) -> InboundMessage:
    return InboundMessage(
        channel_name="github",
        chat_id="zhfeng/llm-gateway",
        user_id="zhfeng",
        text="a PR was opened",
        msg_type=InboundMessageType.CHAT,
        # topic_id pairs PR number with agent name to keep each agent on
        # its own deterministic thread; see app/gateway/github/dispatcher.py.
        topic_id="7:coding-llm-gateway",
        owner_user_id="default",
        metadata={
            "agent_name": "coding-llm-gateway",
            "github": {
                "repo": "zhfeng/llm-gateway",
                "number": 7,
                "installation_id": installation_id,
            },
            "preferred_thread_id": "uuid5-fixed",
        },
    )


def _new_manager() -> ChannelManager:
    bus = MessageBus()
    store = ChannelStore(path=Path("/tmp/nonexistent-store-test.json"))
    return ChannelManager(bus=bus, store=store)


@pytest.mark.asyncio
async def test_run_context_after_apply_channel_policy_is_json_serializable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression pin: ``run_context`` survives the langgraph SDK's JSON encoder.

    The channel path calls ``client.runs.wait(thread_id, assistant_id,
    context=run_context, …)``. The SDK encodes the body with ``orjson``
    before sending it over HTTP. Anything in ``run_context`` that is not
    JSON-serializable (notably the previous closure-based token provider)
    raises ``TypeError: Type is not JSON serializable: function`` and the
    entire delivery fails. This test pins the contract so we never
    silently regress to shipping a closure again.
    """
    import json

    manager = _new_manager()
    mint = AsyncMock(return_value="ghs_installation_token")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {"thread_id": "t1", "user_id": "u1"}
    await manager._apply_channel_policy(_github_msg(), run_context)

    # Will raise TypeError if anything in run_context is not JSON-serializable.
    encoded = json.dumps(run_context)
    assert '"github_token": "ghs_installation_token"' in encoded


@pytest.mark.asyncio
async def test_apply_channel_policy_degrades_on_mint_failure(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A failed mint must not crash the run; the agent proceeds read-only.

    ``_apply_channel_policy`` catches credential-provider exceptions and
    logs a warning so a transient GitHub API outage or a misconfigured
    installation_id degrades to "no token injected" rather than dropping
    the delivery.
    """
    manager = _new_manager()

    async def boom(_installation_id):
        raise RuntimeError("GITHUB_APP_ID not set")

    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", boom)

    run_context: dict = {}
    with caplog.at_level("WARNING", logger="app.channels.manager"):
        await manager._apply_channel_policy(_github_msg(), run_context)

    # Must not crash, must not set a token, must warn.
    assert "github_token" not in run_context
    assert any("credentials_provider raised" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_apply_channel_policy_skips_token_without_installation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A binding with no ``installation_id`` runs without a minted token —
    no mint call, no ``github_token`` in run_context. The non-interactive
    flag still gets set because that is decided by the channel-policy
    entry, not by the credentials provider.
    """
    manager = _new_manager()
    mint = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {}
    await manager._apply_channel_policy(_github_msg(installation_id=None), run_context)

    mint.assert_not_awaited()
    assert "github_token" not in run_context
    # disable_clarification is set unconditionally for github (it is on
    # the policy entry, not the credentials provider).
    assert run_context["disable_clarification"] is True


# ---------------------------------------------------------------------------
# ChannelRunPolicy registration + _apply_channel_policy
# ---------------------------------------------------------------------------


def test_github_policy_is_registered_on_import() -> None:
    """Importing the gateway.github subpackage registers the run policy.

    The manager doesn't carry GitHub-specific branches anymore — the
    policy entry is the single source of truth. Tests, gateway
    bootstrap, and ad-hoc scripts all get the same registration via the
    same import side-effect.
    """
    # Importing app.gateway.github runs run_policy.register_policy() as
    # an import side-effect.
    import app.gateway.github  # noqa: F401
    from app.channels.run_policy import CHANNEL_RUN_POLICY

    policy = CHANNEL_RUN_POLICY.get("github")
    assert policy is not None
    assert policy.is_interactive is False
    assert policy.default_recursion_limit == 250
    assert policy.credentials_provider is not None


@pytest.mark.asyncio
async def test_apply_channel_policy_installs_token_for_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unified policy hook installs the github credentials and the
    non-interactive flag — both in one call.

    The token in ``run_context`` is the minted **string**, not a closure,
    so the value survives the langgraph SDK's JSON encoder on its way to
    ``client.runs.wait(context=…)``.
    """
    manager = _new_manager()
    mint = AsyncMock(return_value="ghs_unified")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    run_context: dict = {}
    await manager._apply_channel_policy(_github_msg(), run_context)

    mint.assert_awaited_once_with(140594274)
    assert run_context["github_token"] == "ghs_unified"
    # Non-interactive flag is set in the same call — one method, one place.
    assert run_context["disable_clarification"] is True


@pytest.mark.asyncio
async def test_apply_channel_policy_is_noop_for_unregistered_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slack/Telegram/etc. have no entry in CHANNEL_RUN_POLICY and stay untouched."""
    manager = _new_manager()
    mint = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr("app.gateway.github.app_auth.mint_installation_token", mint)

    msg = InboundMessage(channel_name="slack", chat_id="C1", user_id="u", text="hi", metadata={})
    run_context: dict = {}
    await manager._apply_channel_policy(msg, run_context)

    mint.assert_not_awaited()
    assert "github_token" not in run_context
    assert "disable_clarification" not in run_context


# ---------------------------------------------------------------------------
# _create_thread honors preferred_thread_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_thread_uses_preferred_thread_id() -> None:
    manager = _new_manager()
    msg = _github_msg()

    created_kwargs: dict = {}

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                created_kwargs.update(kwargs)
                return {"thread_id": "uuid5-fixed"}

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        thread_id = await manager._create_thread(_FakeClient(), msg)

    assert thread_id == "uuid5-fixed"
    assert created_kwargs["thread_id"] == "uuid5-fixed"
    assert "metadata" in created_kwargs


@pytest.mark.asyncio
async def test_create_thread_without_preferred_id_omits_thread_id_kwarg() -> None:
    manager = _new_manager()
    msg = InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="u",
        text="hi",
        metadata={},  # no preferred_thread_id
    )

    created_kwargs: dict = {}

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                created_kwargs.update(kwargs)
                return {"thread_id": "random-from-gateway"}

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        await manager._create_thread(_FakeClient(), msg)

    assert "thread_id" not in created_kwargs


@pytest.mark.asyncio
async def test_create_thread_handles_race_on_preferred_id() -> None:
    """Two concurrent deliveries for the same (repo, number) collide on the
    deterministic thread id. The losing writer hits a 409 ConflictError
    from the underlying thread_store; we verify the thread actually exists
    and reuse the deterministic id rather than dropping the run.
    """
    manager = _new_manager()
    msg = _github_msg()  # carries preferred_thread_id="uuid5-fixed"

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                raise _make_conflict_error()

            @staticmethod
            async def get(thread_id, **kwargs):
                # The winning concurrent create succeeded; threads.get
                # confirms the row is there before we cache the mapping.
                return {"thread_id": thread_id}

    stored: dict = {}

    async def _fake_store(_msg, thread_id):
        stored["thread_id"] = thread_id

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        thread_id = await manager._create_thread(_FakeClient(), msg)

    # Recovered: returns the deterministic id and persisted the mapping.
    assert thread_id == "uuid5-fixed"
    assert stored["thread_id"] == "uuid5-fixed"


@pytest.mark.asyncio
async def test_create_thread_non_conflict_failure_propagates_and_does_not_poison_store() -> None:
    """Regression pin for willem-bd #1 on PR #3754.

    A transient DB/network failure on threads.create (anything other than a
    409 ConflictError) must propagate cleanly. Previously this branch
    swallowed bare Exception and wrote ``preferred_thread_id`` into the
    store, mapping every subsequent webhook for the same (repo, PR) to a
    thread that never existed — runs.create then 404'd forever with no
    retry path.

    The narrow ``except ConflictError`` lets non-conflict failures surface
    so the caller fails the delivery cleanly and the store stays clean.
    """
    manager = _new_manager()
    msg = _github_msg()  # carries preferred_thread_id="uuid5-fixed"

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                # Anything that is NOT ConflictError: connection error, 500
                # from the underlying store, JSON decode error, etc.
                raise RuntimeError("HTTP 500: Failed to create thread")

            @staticmethod
            async def get(thread_id, **kwargs):
                # Should never be called on the non-conflict path.
                raise AssertionError("threads.get must not be called on non-conflict failure")

    store_calls: list = []

    async def _fake_store(_msg, thread_id):
        store_calls.append(thread_id)

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        with pytest.raises(RuntimeError, match="500"):
            await manager._create_thread(_FakeClient(), msg)

    # The mapping must NOT have been written — that was the bug.
    assert store_calls == []


@pytest.mark.asyncio
async def test_create_thread_conflict_with_get_failure_propagates_and_does_not_poison_store() -> None:
    """If ConflictError fires but the follow-up threads.get also fails, the
    store underneath is in an inconsistent state. Surfacing the failure is
    better than caching a mapping to a thread that may not exist — every
    future delivery on this issue/PR would 404 forever.
    """
    manager = _new_manager()
    msg = _github_msg()

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                raise _make_conflict_error()

            @staticmethod
            async def get(thread_id, **kwargs):
                # Conflict was reported but the thread is not actually there.
                raise RuntimeError("HTTP 404: thread not found")

    store_calls: list = []

    async def _fake_store(_msg, thread_id):
        store_calls.append(thread_id)

    with patch.object(manager, "_store_thread_id", new=_fake_store):
        with pytest.raises(RuntimeError, match="404"):
            await manager._create_thread(_FakeClient(), msg)

    # No mapping was cached — that's the whole point of the verify step.
    assert store_calls == []


@pytest.mark.asyncio
async def test_create_thread_without_preferred_id_propagates_error() -> None:
    """Without a deterministic id we have no recovery anchor — the original
    exception must surface so the dispatch loop can handle/report it.
    """
    manager = _new_manager()
    msg = InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="u",
        text="hi",
        metadata={},  # no preferred_thread_id
    )

    class _FakeClient:
        class threads:
            @staticmethod
            async def create(**kwargs):
                raise RuntimeError("HTTP 500: Failed to create thread")

    with patch.object(manager, "_store_thread_id", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="500"):
            await manager._create_thread(_FakeClient(), msg)
