"""Exact-name MCP calls used by the durable ordinary-task driver."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import get_paths
from deerflow.constants import MCP_TMP_SUBDIR
from deerflow.mcp.client import build_server_params
from deerflow.mcp.context_headers import build_context_headers_interceptor
from deerflow.mcp.headers import apply_header_overrides
from deerflow.mcp.interceptors import build_mcp_tool_interceptors
from deerflow.mcp.oauth import OAuthTokenManager, build_oauth_tool_interceptor
from deerflow.mcp.session_pool import get_session_pool

logger = logging.getLogger(__name__)


def mcp_task_session_scope_key(*, user_id: str, thread_id: str) -> str:
    """Keep background calls in the same per-user/per-thread session scope."""
    return f"{user_id}:{thread_id}"


def _prepare_stdio_connection(
    connection: dict[str, Any],
    *,
    user_id: str,
    thread_id: str,
) -> dict[str, Any]:
    paths = get_paths()
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    work_dir = paths.sandbox_work_dir(thread_id, user_id=user_id)
    tmp_dir = work_dir / MCP_TMP_SUBDIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.chmod(0o700)

    prepared = dict(connection)
    prepared.setdefault("cwd", str(work_dir))
    env = dict(prepared.get("env") or {})
    env.setdefault("TMPDIR", str(tmp_dir))
    env.setdefault("TMP", str(tmp_dir))
    env.setdefault("TEMP", str(tmp_dir))
    prepared["env"] = env
    return prepared


class McpTaskToolCaller:
    """Call configured raw MCP tools without exposing them back to the Agent."""

    def __init__(
        self,
        extensions_config: ExtensionsConfig,
        *,
        oauth_token_manager: OAuthTokenManager | None = None,
    ) -> None:
        self._extensions_config = extensions_config
        self._oauth_token_manager = oauth_token_manager or OAuthTokenManager.from_extensions_config(extensions_config)
        context_headers_interceptor = build_context_headers_interceptor(extensions_config)
        # Built once so the two chains keep an identical interceptor order and a
        # custom ``mcpInterceptors`` builder is invoked exactly once.
        self._submit_interceptors = build_mcp_tool_interceptors(
            extensions_config,
            oauth_builder=lambda config: build_oauth_tool_interceptor(
                config,
                token_manager=self._oauth_token_manager,
            ),
            context_headers_builder=lambda _config: context_headers_interceptor,
        )
        # Submitting a durable task is awaited inline inside the Agent's tool
        # call, so ``config.context.secrets`` is still reachable through the
        # ambient LangGraph runtime and the submit goes out under the caller's
        # own credential. The later status/cancel polls are driven by the task
        # runtime long after that run ended: there is no run context to read, so
        # the fail-closed interceptor would deny every poll. Those keep using
        # server-level credentials (see docs/MCP_SERVER.md), which is what
        # ``build_context_headers_interceptor`` warns about at startup.
        if context_headers_interceptor is None:
            self._interceptors = self._submit_interceptors
        else:
            self._interceptors = [interceptor for interceptor in self._submit_interceptors if interceptor is not context_headers_interceptor]

    async def call_tool(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str,
        thread_id: str,
        request_scoped_headers: bool = False,
    ) -> Any:
        """Call a raw MCP tool.

        ``request_scoped_headers`` opts this call into the ``headers_from_context``
        interceptor. Only the durable *submit* may set it: submit is awaited
        inside the Agent run that carries the secrets, while status and cancel
        run after that run ended.
        """
        interceptors = self._submit_interceptors if request_scoped_headers else self._interceptors
        server_config = self._extensions_config.get_enabled_mcp_servers().get(server_name)
        if server_config is None:
            raise LookupError(f"MCP task server {server_name!r} is missing or disabled in the startup configuration")
        connection = build_server_params(server_name, server_config)
        transport = connection.get("transport", "stdio")
        scope_key = mcp_task_session_scope_key(user_id=user_id, thread_id=thread_id)

        if transport == "stdio":
            connection = await asyncio.to_thread(
                _prepare_stdio_connection,
                connection,
                user_id=user_id,
                thread_id=thread_id,
            )
            pool = get_session_pool()
            session_init_timeout = server_config.session_init_timeout
            if session_init_timeout is not None:
                try:
                    session = await asyncio.wait_for(
                        pool.get_session(server_name, scope_key, connection),
                        timeout=session_init_timeout,
                    )
                except TimeoutError:
                    logger.warning(
                        "MCP task session initialization for server '%s' timed out after %.1fs",
                        server_name,
                        session_init_timeout,
                    )
                    raise
            else:
                session = await pool.get_session(server_name, scope_key, connection)
            try:
                return await self._invoke(
                    session=session,
                    connection=connection,
                    server_name=server_name,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout_seconds=server_config.tool_call_timeout,
                    session_init_timeout_seconds=None,
                    persistent_session=True,
                    interceptors=interceptors,
                )
            except Exception:
                # A dead pooled subprocess must not poison every later status
                # poll. The next retry recreates this exact scoped session.
                await pool.close_session(server_name, scope_key)
                raise

        authorization = await self._oauth_token_manager.get_authorization_header(server_name)
        if authorization:
            connection["headers"] = apply_header_overrides(
                connection.get("headers") or {},
                {"Authorization": authorization},
            )
        return await self._invoke(
            session=None,
            connection=connection,
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            timeout_seconds=server_config.tool_call_timeout,
            session_init_timeout_seconds=server_config.session_init_timeout,
            persistent_session=False,
            interceptors=interceptors,
        )

    async def _invoke(
        self,
        *,
        session: Any | None,
        connection: dict[str, Any],
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float | None,
        session_init_timeout_seconds: float | None,
        persistent_session: bool,
        interceptors: list[Any],
    ) -> Any:
        from langchain_mcp_adapters.interceptors import MCPToolCallRequest
        from langchain_mcp_adapters.sessions import create_session

        async def execute(request: MCPToolCallRequest) -> Any:
            call_kwargs: dict[str, Any] = {}
            if timeout_seconds:
                call_kwargs["read_timeout_seconds"] = timedelta(seconds=timeout_seconds)

            if persistent_session:
                assert session is not None
                if request.headers:
                    if isinstance(request.headers, Mapping):
                        call_kwargs["meta"] = {"headers": dict(request.headers)}
                    else:
                        logger.warning(
                            "Ignoring MCP interceptor headers with unsupported type: %s",
                            type(request.headers).__name__,
                        )
                return await session.call_tool(request.name, request.args, **call_kwargs)

            effective_connection = dict(connection)
            if request.headers:
                effective_connection["headers"] = apply_header_overrides(
                    effective_connection.get("headers") or {},
                    dict(request.headers),
                )
            captured: BaseException | None = None
            call_result: Any | None = None
            async with create_session(effective_connection) as remote_session:
                initialize = remote_session.initialize()
                if session_init_timeout_seconds is not None:
                    await asyncio.wait_for(
                        initialize,
                        timeout=session_init_timeout_seconds,
                    )
                else:
                    await initialize
                try:
                    call = remote_session.call_tool(
                        request.name,
                        request.args,
                        **call_kwargs,
                    )
                    if timeout_seconds:
                        call_result = await asyncio.wait_for(
                            call,
                            timeout=timeout_seconds,
                        )
                    else:
                        call_result = await call
                except BaseException as exc:  # preserve adapter disconnect semantics
                    captured = exc
            if captured is not None:
                raise captured
            if call_result is None:
                raise RuntimeError(f"MCP task tool {request.name!r} returned no result")
            return call_result

        handler = execute
        for interceptor in reversed(interceptors):
            inner = handler

            async def wrapped(request: Any, _interceptor: Any = interceptor, _inner: Any = inner) -> Any:
                return await _interceptor(request, _inner)

            handler = wrapped

        return await handler(
            MCPToolCallRequest(
                name=tool_name,
                args=arguments,
                server_name=server_name,
                runtime=None,
            )
        )
