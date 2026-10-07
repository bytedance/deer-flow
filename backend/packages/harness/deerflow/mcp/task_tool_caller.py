"""Exact-name MCP calls used by the durable ordinary-task driver."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import get_paths
from deerflow.constants import MCP_TMP_SUBDIR
from deerflow.mcp.client import build_server_params
from deerflow.mcp.context_headers import build_context_headers_interceptor
from deerflow.mcp.headers import apply_header_overrides
from deerflow.mcp.interceptors import build_mcp_tool_interceptors
from deerflow.mcp.oauth import OAuthTokenManager, build_oauth_tool_interceptor
from deerflow.mcp.personal_access import require_personal_mcp_access
from deerflow.mcp.session_pool import (
    MCPPoolDomain,
    MCPSessionPool,
    call_pooled_session_tool,
    get_session_pool,
)
from deerflow.mcp.tasks.runtime import get_mcp_task_oauth_token_manager
from deerflow.mcp.user_config import PersonalMcpConfigSnapshot, load_user_mcp_config_if_changed
from deerflow.mcp_scope import mcp_session_scope_key
from deerflow.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)
# Cached callers retain personal credentials and OAuth state in memory.
_MAX_PERSONAL_CALLERS = 128


@dataclass
class _TaskOwner:
    """ID-only CurrentUser for background MCP auth; no profile or role data."""

    id: str


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
        self._personal_callers: OrderedDict[str, tuple[PersonalMcpConfigSnapshot, McpTaskToolCaller | None]] = OrderedDict()
        self._personal_callers_lock = threading.Lock()
        self._oauth_token_manager = oauth_token_manager or get_mcp_task_oauth_token_manager(extensions_config)
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
        # configured credentials, including user_auth for the persisted owner
        # (see docs/MCP_SERVER.md), which is what
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
        thread_incarnation: str | None = None,
        request_scoped_headers: bool = False,
        connection_scope: Literal["deployment", "personal"] = "deployment",
    ) -> Any:
        """Call a raw MCP tool.

        ``request_scoped_headers`` opts this call into the ``headers_from_context``
        interceptor. Only the durable *submit* may set it: submit is awaited
        inside the Agent run that carries the secrets, while status and cancel
        run after that run ended. ``connection_scope`` is captured in the task
        binding, so an equal deployment server name cannot change its owner.
        """
        if connection_scope == "personal":
            caller = await asyncio.to_thread(self._personal_caller_for, user_id, server_name)
            await require_personal_mcp_access(user_id, caller._extensions_config.mcp_servers[server_name])
            return await caller._call_configured_tool(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                user_id=user_id,
                thread_id=thread_id,
                thread_incarnation=thread_incarnation,
                request_scoped_headers=request_scoped_headers,
                connection_scope="personal",
            )
        if connection_scope != "deployment":
            raise ValueError("Invalid MCP task connection scope")
        return await self._call_configured_tool(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            user_id=user_id,
            thread_id=thread_id,
            thread_incarnation=thread_incarnation,
            request_scoped_headers=request_scoped_headers,
            connection_scope="deployment",
        )

    def _personal_caller_for(self, user_id: str, server_name: str) -> McpTaskToolCaller:
        with self._personal_callers_lock:
            previous = self._personal_callers.get(user_id)
            snapshot = load_user_mcp_config_if_changed(user_id, previous[0] if previous else None)
            caller = previous[1] if previous and previous[0] is snapshot else None
            self._personal_callers[user_id] = (snapshot, caller)
            self._personal_callers.move_to_end(user_id)
            if len(self._personal_callers) > _MAX_PERSONAL_CALLERS:
                self._personal_callers.popitem(last=False)
            server = snapshot.config.mcp_servers.get(server_name)
            if server is None or not server.enabled:
                raise LookupError("Personal MCP task connection is missing, disabled or changed")
            if caller is None:
                # A personal name can equal a deployment name. Never consult
                # the deployment OAuth state or startup snapshot for this path.
                caller = McpTaskToolCaller(snapshot.config, oauth_token_manager=OAuthTokenManager.from_extensions_config(snapshot.config))
                self._personal_callers[user_id] = (snapshot, caller)
            return caller

    async def _call_configured_tool(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str,
        thread_id: str,
        thread_incarnation: str | None,
        request_scoped_headers: bool,
        connection_scope: MCPPoolDomain,
    ) -> Any:
        is_background_call = not request_scoped_headers
        interceptors = self._interceptors if is_background_call else self._submit_interceptors
        server_config = self._extensions_config.get_enabled_mcp_servers().get(server_name)
        if server_config is None:
            raise LookupError(f"MCP task server {server_name!r} is missing or disabled in the startup configuration")
        connection = build_server_params(server_name, server_config)
        transport = connection.get("transport", "stdio")
        scope_key = mcp_session_scope_key(
            user_id=user_id,
            thread_id=thread_id,
            thread_incarnation=thread_incarnation,
        )

        if transport == "stdio":
            connection = await asyncio.to_thread(
                _prepare_stdio_connection,
                connection,
                user_id=user_id,
                thread_id=thread_id,
            )
            pool = get_session_pool()
            session_init_timeout = server_config.session_init_timeout
            session_request = pool.get_session(server_name, scope_key, connection) if connection_scope == "deployment" else pool.get_session(server_name, scope_key, connection, domain=connection_scope)
            if session_init_timeout is not None:
                try:
                    session = await asyncio.wait_for(
                        session_request,
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
                session = await session_request
            return await self._invoke(
                session=session,
                pool=pool,
                scope_key=scope_key,
                connection=connection,
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                background_user_id=None,
                timeout_seconds=server_config.tool_call_timeout,
                session_init_timeout_seconds=None,
                persistent_session=True,
                interceptors=interceptors,
                connection_scope=connection_scope,
            )

        authorization = await self._oauth_token_manager.get_authorization_header(server_name)
        if authorization:
            connection["headers"] = apply_header_overrides(
                connection.get("headers") or {},
                {"Authorization": authorization},
            )
        # Only HTTP/SSE servers with enabled user_auth need an ambient owner.
        # Leave other custom-interceptor contexts unchanged.
        user_auth = server_config.user_auth
        return await self._invoke(
            session=None,
            pool=None,
            scope_key=scope_key,
            connection=connection,
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            background_user_id=user_id if is_background_call and user_auth is not None and user_auth.enabled else None,
            timeout_seconds=server_config.tool_call_timeout,
            session_init_timeout_seconds=server_config.session_init_timeout,
            persistent_session=False,
            interceptors=interceptors,
            connection_scope=connection_scope,
        )

    async def _invoke(
        self,
        *,
        session: Any | None,
        pool: MCPSessionPool | None,
        scope_key: str,
        connection: dict[str, Any],
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        background_user_id: str | None,
        timeout_seconds: float | None,
        session_init_timeout_seconds: float | None,
        persistent_session: bool,
        interceptors: list[Any],
        connection_scope: MCPPoolDomain,
    ) -> Any:
        from langchain_mcp_adapters.interceptors import MCPToolCallRequest
        from langchain_mcp_adapters.sessions import create_session

        async def execute(request: MCPToolCallRequest) -> Any:
            call_kwargs: dict[str, Any] = {}
            if timeout_seconds:
                call_kwargs["read_timeout_seconds"] = timedelta(seconds=timeout_seconds)

            if persistent_session:
                assert session is not None and pool is not None
                if request.headers:
                    if isinstance(request.headers, Mapping):
                        call_kwargs["meta"] = {"headers": dict(request.headers)}
                    else:
                        logger.warning(
                            "Ignoring MCP interceptor headers with unsupported type: %s",
                            type(request.headers).__name__,
                        )
                domain_kwargs = {"domain": connection_scope} if connection_scope != "deployment" else {}
                return await call_pooled_session_tool(
                    session,
                    pool,
                    server_name=server_name,
                    scope_key=scope_key,
                    tool_name=request.name,
                    arguments=request.args,
                    call_kwargs=call_kwargs,
                    **domain_kwargs,
                )

            effective_connection = dict(connection)
            if request.headers:
                effective_connection["headers"] = apply_header_overrides(
                    effective_connection.get("headers") or {},
                    dict(request.headers),
                )
            captured: BaseException | None = None
            call_result: Any | None = None
            # Bound transport entry and initialization together, keeping the
            # adapter's AnyIO context managers in the same task for cleanup.
            try:
                async with (
                    asyncio.timeout(session_init_timeout_seconds) as init_timeout,
                    create_session(effective_connection) as remote_session,
                ):
                    await remote_session.initialize()
                    # Tool calls have their own independent timeout below.
                    init_timeout.reschedule(None)
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
            except TimeoutError:
                if not init_timeout.expired():
                    raise
                raise TimeoutError(f"MCP task session initialization for server {server_name!r} timed out after {session_init_timeout_seconds}s") from None
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

        # Durable status/cancel calls run after the originating Agent turn, so
        # there is no LangGraph runtime from which the user-scoped auth
        # interceptor can resolve an identity. Bind the persisted task owner for
        # the duration of this call, leaving the live submit context untouched.
        # ContextVar state keeps parallel polls for different users isolated.
        user_context_token = set_current_user(_TaskOwner(id=background_user_id)) if background_user_id is not None else None
        try:
            return await handler(
                MCPToolCallRequest(
                    name=tool_name,
                    args=arguments,
                    server_name=server_name,
                    runtime=None,
                )
            )
        finally:
            if user_context_token is not None:
                reset_current_user(user_context_token)
