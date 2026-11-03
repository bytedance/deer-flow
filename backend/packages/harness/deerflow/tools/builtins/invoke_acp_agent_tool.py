"""Built-in tool for invoking external ACP-compatible agents."""

import asyncio
import logging
import os
import shutil
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Bytes of agent stderr kept for the Gateway log when an invocation fails.
_STDERR_TAIL_BYTES = 8 * 1024
# After the agent process exits, how long the SDK receive loop may keep reading
# responses still buffered in the stdout pipe before the call is declared failed.
_EXIT_DRAIN_SECONDS = 2.0


class _InvokeACPAgentInput(BaseModel):
    agent: str = Field(description="Name of the ACP agent to invoke")
    prompt: str = Field(description="The concise task prompt to send to the agent")


def _get_work_dir(thread_id: str | None) -> str:
    """Get the per-thread ACP workspace directory.

    Each thread gets an isolated workspace under
    ``{base_dir}/threads/{thread_id}/acp-workspace/`` so that concurrent
    sessions cannot read or overwrite each other's ACP agent outputs.

    Falls back to the legacy global ``{base_dir}/acp-workspace/`` when
    ``thread_id`` is not available (e.g. embedded / direct invocation).

    The directory is created automatically if it does not exist.

    Returns:
        An absolute physical filesystem path to use as the working directory.
    """
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import get_effective_user_id

    paths = get_paths()
    if thread_id:
        try:
            work_dir = paths.acp_workspace_dir(thread_id, user_id=get_effective_user_id())
        except ValueError:
            logger.warning("Invalid thread_id %r for ACP workspace, falling back to global", thread_id)
            work_dir = paths.base_dir / "acp-workspace"
    else:
        work_dir = paths.base_dir / "acp-workspace"

    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("ACP agent work_dir: %s", work_dir)
    return str(work_dir)


def _build_mcp_servers() -> dict[str, dict[str, Any]]:
    """Build ACP ``mcpServers`` config from DeerFlow's enabled MCP servers."""
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.client import build_servers_config

    return build_servers_config(ExtensionsConfig.from_file())


def _build_acp_mcp_servers() -> list[dict[str, Any]]:
    """Build ACP ``mcpServers`` payload for ``new_session``.

    The ACP client expects a list of server objects, while DeerFlow's MCP helper
    returns a name -> config mapping for the LangChain MCP adapter. This helper
    converts the enabled servers into the ACP wire format.
    """
    from deerflow.config.extensions_config import ExtensionsConfig

    extensions_config = ExtensionsConfig.from_file()
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    mcp_servers: list[dict[str, Any]] = []
    for name, server_config in enabled_servers.items():
        transport_type = server_config.type or "stdio"
        payload: dict[str, Any] = {"name": name, "type": transport_type}

        if transport_type == "stdio":
            if not server_config.command:
                raise ValueError(f"MCP server '{name}' with stdio transport requires 'command' field")
            payload["command"] = server_config.command
            payload["args"] = server_config.args
            payload["env"] = [{"name": key, "value": value} for key, value in server_config.env.items()]
        elif transport_type in ("http", "sse"):
            if not server_config.url:
                raise ValueError(f"MCP server '{name}' with {transport_type} transport requires 'url' field")
            payload["url"] = server_config.url
            payload["headers"] = [{"name": key, "value": value} for key, value in server_config.headers.items()]
        else:
            raise ValueError(f"MCP server '{name}' has unsupported transport type: {transport_type}")

        mcp_servers.append(payload)

    return mcp_servers


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


def build_invoke_acp_agent_tool(agents: dict) -> BaseTool:
    """Create the ``invoke_acp_agent`` tool with a description generated from configured agents.

    The tool description includes the list of available agents so that the LLM
    knows which agents it can invoke without requiring hardcoded names.

    Args:
        agents: Mapping of agent name -> ``ACPAgentConfig``.

    Returns:
        A LangChain ``BaseTool`` ready to be included in the tool list.
    """
    agent_lines = "\n".join(f"- {name}: {cfg.description}" for name, cfg in agents.items())
    description = (
        "Invoke an external ACP-compatible agent and return its final response.\n\n"
        "Available agents:\n"
        f"{agent_lines}\n\n"
        "IMPORTANT: ACP agents operate in their own independent workspace. "
        "Do NOT include /mnt/user-data paths in the prompt. "
        "Give the agent a self-contained task description — it will produce results in its own workspace. "
        "After the agent completes, its output files are accessible at /mnt/acp-workspace/ (read-only)."
    )

    # Capture agents in closure so the function can reference it
    _agents = dict(agents)

    async def _invoke(agent: str, prompt: str, config: Annotated[RunnableConfig, InjectedToolArg] = None) -> str:
        logger.info("Invoking ACP agent %s (prompt length: %d)", agent, len(prompt))
        logger.debug("Invoking ACP agent %s with prompt: %.200s%s", agent, prompt, "..." if len(prompt) > 200 else "")
        if agent not in _agents:
            available = ", ".join(_agents.keys())
            return f"Error: Unknown agent '{agent}'. Available: {available}"

        agent_config = _agents[agent]
        thread_id: str | None = ((config or {}).get("configurable") or {}).get("thread_id")

        try:
            from acp import PROTOCOL_VERSION, Client, text_block
            from acp.schema import ClientCapabilities, Implementation
        except ImportError:
            return "Error: agent-client-protocol package is not installed. Run `uv sync` to install project dependencies."

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
        agent_env: dict[str, str] | None = None
        if agent_config.env:
            # $VARS in config.yaml are already resolved by AppConfig.resolve_env_variables;
            # resolving again would rewrite a secret that itself starts with $.
            agent_env = dict(agent_config.env)
        # Resolve against the PATH the agent subprocess will see, not the Gateway's:
        # the SDK merges agent_env over its inherited environment at spawn time.
        cmd = await asyncio.to_thread(_resolve_agent_command, agent_config.command, _agent_path(agent_env))
        args = agent_config.args or []
        physical_cwd = await asyncio.to_thread(_get_work_dir, thread_id)
        try:
            mcp_servers = await asyncio.to_thread(_build_acp_mcp_servers)
        except ValueError as exc:
            logger.warning(
                "Invalid MCP server configuration for ACP agent '%s'; continuing without MCP servers: %s",
                agent,
                exc,
            )
            mcp_servers = []

        async def _converse(conn) -> None:
            await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="deerflow", title="DeerFlow", version="0.1.0"),
            )
            session_kwargs: dict[str, Any] = {"cwd": physical_cwd, "mcp_servers": mcp_servers}
            if agent_config.model:
                session_kwargs["model"] = agent_config.model
            session = await conn.new_session(**session_kwargs)
            await conn.prompt(
                session_id=session.session_id,
                prompt=[text_block(prompt)],
            )

        stderr_tail: _StderrTail | None = None
        timed_out = False
        try:
            from acp import spawn_agent_process

            async with spawn_agent_process(client, cmd, *args, env=agent_env, cwd=physical_cwd) as (conn, proc):
                stderr_tail = _StderrTail(proc.stderr)
                logger.info("Spawning ACP agent '%s' with command '%s' and args %s in cwd %s", agent, cmd, args, physical_cwd)
                try:
                    async with asyncio.timeout(agent_config.timeout_seconds) as deadline:
                        await _await_while_agent_runs(_converse(conn), proc)
                except TimeoutError:
                    if not deadline.expired():
                        raise
                    # Leave the SDK context first: it terminates and reaps the
                    # agent, so the lines a stalled agent wrote last reach the tail.
                    timed_out = True
                except _AgentExitedError as exc:
                    status = f"exited with code {exc.returncode}" if exc.returncode is not None else "closed its ACP connection"
                    logger.error(
                        "ACP agent '%s' %s before completing the ACP invocation. stderr tail:\n%s",
                        agent,
                        status,
                        await stderr_tail.text(wait=_EXIT_DRAIN_SECONDS),
                    )
                    return (
                        f"Error: ACP agent '{agent}' {status} before completing the ACP invocation. "
                        f"Check that the agent is installed and authenticated and that acp_agents.{agent} in config.yaml is correct; "
                        "the agent's stderr is recorded in the Gateway log."
                    )
            if timed_out:
                logger.error(
                    "ACP agent '%s' timed out after %s seconds during initialization, session creation, or prompt; subprocess terminated. stderr tail:\n%s",
                    agent,
                    agent_config.timeout_seconds,
                    await stderr_tail.text(wait=_EXIT_DRAIN_SECONDS),
                )
                return (
                    f"Error: ACP agent '{agent}' timed out after {agent_config.timeout_seconds} seconds "
                    "without completing the ACP invocation. The agent subprocess has been terminated. If this agent handles "
                    f"long-running tasks, increase acp_agents.{agent}.timeout_seconds in config.yaml."
                )
            result = client.collected_text
            logger.info("ACP agent '%s' returned %s", agent, result[:1000])
            logger.info("ACP agent '%s' returned %d characters", agent, len(result))
            return result or "(no response)"
        except Exception as e:
            logger.error("ACP agent '%s' invocation failed: %s", agent, e)
            # Report the configured command, not the resolved path: remediation
            # text has to match what the operator wrote in config.yaml.
            return await asyncio.to_thread(_format_invocation_error, agent, agent_config.command, e)
        finally:
            if stderr_tail is not None:
                await stderr_tail.aclose()

    return StructuredTool.from_function(
        name="invoke_acp_agent",
        description=description,
        coroutine=_invoke,
        args_schema=_InvokeACPAgentInput,
    )
