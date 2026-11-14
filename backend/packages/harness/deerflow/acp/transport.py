"""Explicit ACP exchanges and subprocess ownership, independent of delegation."""

import asyncio
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)
_STDERR_TAIL_BYTES = 8 * 1024
_EXIT_DRAIN_SECONDS = 2.0


@dataclass(frozen=True)
class ACPOutcome:
    text: str = ""
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None


def _build_permission_response(options: list[Any], *, auto_approve: bool) -> Any:
    """Build an ACP permission response.

    When ``auto_approve`` is True, selects the first ``allow_once`` (preferred)
    or ``allow_always`` option.  When False (the default), always cancels —
    permission requests must be handled by the ACP agent's own policy or the
    agent must be configured to operate without requesting permissions.
    """
    from acp import RequestPermissionResponse
    from acp.schema import AllowedOutcome, DeniedOutcome

    if auto_approve:
        for preferred_kind in ("allow_once", "allow_always"):
            for option in options:
                if getattr(option, "kind", None) != preferred_kind:
                    continue

                option_id = getattr(option, "option_id", None)
                if option_id is None:
                    option_id = getattr(option, "optionId", None)
                if option_id is None:
                    continue

                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", optionId=option_id),
                )

    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def _agent_path(env: dict[str, str] | None) -> str | None:
    """Return the ``PATH`` the ACP SDK will give the agent subprocess.

    The SDK builds the child environment by inheriting a trimmed copy of the
    Gateway's environment and then applying ``acp_agents.<name>.env`` on top, so
    a configured ``PATH`` -- not the Gateway's -- decides which launcher the
    agent actually finds. ``None`` means the agent does not override ``PATH``,
    which lets ``shutil.which`` fall back to the Gateway's own.

    The lookup is case-insensitive because environment variable names are on
    Windows, where ``Path`` and ``PATH`` name the same variable.
    """
    if not env:
        return None
    return next((value for key, value in env.items() if key.upper() == "PATH"), None)


def _resolve_agent_command(command: str, path: str | None = None) -> str:
    r"""Return the host path to spawn for a configured ACP agent command.

    ``asyncio.create_subprocess_exec``, which the ACP SDK's stdio transport
    uses, does not apply ``PATHEXT`` on Windows: a bare ``npx`` or ``mcode``
    raises ``FileNotFoundError`` even though the npm shim (``npx.cmd``) is on
    ``PATH``, and an absolute ``C:\npm\mcode`` spawns npm's extensionless shell
    script instead of ``mcode.CMD`` and dies with ``WinError 193``. Resolve
    the command the way the MCP Python SDK normalizes stdio commands, and keep
    the configured value when nothing matches so the not-found remediation
    still fires.

    Bare names and absolute paths are resolved. A relative configured path is
    handed to the spawn unchanged: it refers to the ACP workspace the spawn
    runs in, not to the Gateway's cwd. An absolute path keeps its own
    directory -- ``shutil.which`` searches that directory and probes
    ``PATHEXT`` there.

    ``path`` is the ``PATH`` the agent subprocess will actually see (see
    ``_agent_path``); the Gateway's own is only the fallback. A successful
    lookup is returned absolute: for a relative ``PATH`` entry ``shutil.which``
    yields a result relative to the Gateway's cwd, while the spawn runs with
    ``cwd`` set to the ACP workspace, where that path resolves elsewhere -- or
    not at all.

    An already-absolute result is returned unchanged: a lexical ``abspath``
    would collapse a ``..`` that follows a symlink, changing which file the
    spawn actually runs.

    The lookup stats the filesystem (``shutil.which`` -> ``os.access``), so
    callers must run it off the event loop.
    """
    if os.path.dirname(command) and not os.path.isabs(command):
        return command
    try:
        resolved = shutil.which(command, path=path)
    except OSError:
        return command
    if not resolved:
        return command
    return resolved if os.path.isabs(resolved) else os.path.abspath(resolved)


class _StderrTail:
    """Drain an agent's stderr pipe, keeping only a bounded tail.

    The SDK spawns agents with ``stderr=PIPE`` but never reads it. Once an agent
    has logged more than asyncio's pipe buffering absorbs, its next stderr write
    blocks, the agent stops answering, and the invocation stalls until the
    timeout. Draining continuously keeps verbose agents running.
    """

    def __init__(self, stream: asyncio.StreamReader | None) -> None:
        self._data = bytearray()
        self._task = asyncio.create_task(self._drain(stream)) if stream is not None else None

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(65536):
            self._data += chunk
            del self._data[:-_STDERR_TAIL_BYTES]

    async def text(self, *, wait: float = 0.0) -> str:
        """Return the tail, waiting up to ``wait`` seconds for the pipe to reach EOF."""
        if self._task is not None and wait > 0:
            await asyncio.wait({self._task}, timeout=wait)
        return self._data.decode("utf-8", errors="replace").strip()

    async def aclose(self) -> None:
        if self._task is not None:
            # A descendant can keep the pipe open after the agent itself is reaped.
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


class _AgentExitedError(Exception):
    """The agent process ended before answering an outstanding ACP request."""

    def __init__(self, returncode: int | None) -> None:
        super().__init__(returncode)
        self.returncode = returncode


async def _await_while_agent_runs(awaitable: Any, proc: asyncio.subprocess.Process) -> Any:
    """Await an ACP exchange, failing fast if the agent process goes away.

    Older SDK releases never fail a pending request when the agent closes its
    stdout, so a crash at startup would otherwise wait out the whole timeout.
    Newer releases raise ``ConnectionError`` instead; both are reported as the
    agent having exited, which is what the operator needs to know.
    """
    exchange = asyncio.ensure_future(awaitable)
    exited = asyncio.ensure_future(proc.wait())
    try:
        await asyncio.wait({exchange, exited}, return_when=asyncio.FIRST_COMPLETED)
        if not exchange.done():
            # A response may still sit in the stdout pipe behind the exit.
            await asyncio.wait({exchange}, timeout=_EXIT_DRAIN_SECONDS)
        if exchange.done() and not isinstance(exchange.exception(), ConnectionError):
            return exchange.result()
        await asyncio.wait({exited}, timeout=_EXIT_DRAIN_SECONDS)
        raise _AgentExitedError(proc.returncode)
    finally:
        exchange.cancel()
        exited.cancel()
        await asyncio.gather(exchange, exited, return_exceptions=True)


def _format_invocation_error(agent: str, cmd: str, exc: Exception) -> str:
    """Return a user-facing ACP invocation error with actionable remediation."""
    if not isinstance(exc, FileNotFoundError):
        return f"Error invoking ACP agent '{agent}': {exc}"

    message = f"Error invoking ACP agent '{agent}': Command '{cmd}' was not found on PATH."
    if cmd == "codex-acp" and shutil.which("codex"):
        return f"{message} The installed `codex` CLI does not speak ACP directly. Install a Codex ACP adapter (for example `npx @zed-industries/codex-acp`) or update `acp_agents.codex.command` and `args` in config.yaml."

    if agent == "mcode":
        return (
            f"{message} Install it with `npm install --global @minimax-ai/code`, run `mcode login`, and restart DeerFlow so it inherits the updated PATH. "
            "If the Gateway runs in Docker, ensure `mcode` is installed and authenticated inside the Gateway container/image."
        )
    return f"{message} Install the agent binary or update `acp_agents.{agent}.command` in config.yaml."


async def invoke_acp(agent: str, agent_config: Any, prompt: str, *, cwd: str, mcp_servers: list[dict], protocol_timeout: float | None = None, command: str | None = None, on_text: Callable[[str], None] | None = None) -> ACPOutcome:
    """Run one session. The caller owns deadlines before spawn and capacity.

    Cancellation leaves the SDK context only after subprocess teardown. A
    protocol timeout is used exclusively by the legacy entry point.
    """
    try:
        from acp import PROTOCOL_VERSION, Client, text_block
        from acp.schema import ClientCapabilities, Implementation
    except ImportError:
        return ACPOutcome(error="Error: agent-client-protocol package is not installed. Run `uv sync` to install project dependencies.", error_code="acp_sdk_unavailable")

    class _CollectingClient(Client):
        """Minimal ACP Client that collects streamed text from session updates."""

        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id: str, update, **kwargs) -> None:  # type: ignore[override]
            try:
                from acp.schema import TextContentBlock

                if getattr(update, "session_update", None) == "agent_message_chunk" and isinstance(update.content, TextContentBlock):
                    self._chunks.append(update.content.text)
                    if on_text is not None:
                        on_text(update.content.text)
            except Exception:
                pass

        async def request_permission(self, options, session_id: str, tool_call, **kwargs):  # type: ignore[override]
            response = _build_permission_response(options, auto_approve=agent_config.auto_approve_permissions)
            outcome = response.outcome.outcome
            if outcome == "selected":
                logger.info("ACP permission auto-approved for tool call %s in session %s", tool_call.tool_call_id, session_id)
            else:
                logger.warning("ACP permission denied for tool call %s in session %s (set auto_approve_permissions: true in config.yaml to enable)", tool_call.tool_call_id, session_id)
            return response

    client = _CollectingClient()
    cmd = command or await await_drained(asyncio.to_thread(_resolve_agent_command, agent_config.command, _agent_path(agent_config.env)))

    async def converse(conn):
        await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=ClientCapabilities(), client_info=Implementation(name="deerflow", title="DeerFlow", version="0.1.0"))
        options = {"cwd": cwd, "mcp_servers": mcp_servers}
        if agent_config.model:
            options["model"] = agent_config.model
        session = await conn.new_session(**options)
        return await conn.prompt(session_id=session.session_id, prompt=[text_block(prompt)])

    stderr_tail = None
    failed = True
    try:
        from acp import spawn_agent_process

        spawn_kwargs = {"cwd": cwd}
        if agent_config.env:
            spawn_kwargs["env"] = dict(agent_config.env)
        async with spawn_agent_process(client, cmd, *agent_config.args, **spawn_kwargs) as (conn, proc):
            stderr_tail = _StderrTail(proc.stderr)
            try:
                async with asyncio.timeout(protocol_timeout) as deadline:
                    response = await _await_while_agent_runs(converse(conn), proc)
            except TimeoutError:
                if not deadline.expired():
                    raise
                return ACPOutcome(
                    error=(
                        f"Error: ACP agent '{agent}' timed out after {protocol_timeout:g} seconds without completing the ACP invocation. "
                        "The agent subprocess has been terminated. If this agent handles long-running tasks, "
                        f"increase acp_agents.{agent}.timeout_seconds in config.yaml."
                    ),
                    error_code="acp_protocol_timeout",
                )
            except _AgentExitedError as exc:
                status = f"exited with code {exc.returncode}" if exc.returncode is not None else "closed its ACP connection"
                return ACPOutcome(
                    error=(
                        f"Error: ACP agent '{agent}' {status} before completing the ACP invocation. "
                        f"Check that the agent is installed and authenticated and that acp_agents.{agent} in config.yaml is correct; "
                        "the agent's stderr is recorded in the Gateway log."
                    ),
                    error_code="acp_process_exited",
                )
        usage = getattr(response, "usage", None)
        if usage is not None:
            usage = usage.model_dump(mode="json", exclude_none=True) if hasattr(usage, "model_dump") else dict(usage)
        failed = False
        return ACPOutcome(text=client.collected_text, stop_reason=getattr(response, "stop_reason", None), usage=usage)
    except Exception as exc:
        return ACPOutcome(error=await asyncio.to_thread(_format_invocation_error, agent, agent_config.command, exc), error_code="acp_protocol_error")
    finally:
        if stderr_tail is not None:
            tail = await stderr_tail.text(wait=_EXIT_DRAIN_SECONDS)
            if tail:
                (logger.error if failed else logger.debug)("ACP agent '%s' stderr tail:\n%s", agent, tail)
            await stderr_tail.aclose()
