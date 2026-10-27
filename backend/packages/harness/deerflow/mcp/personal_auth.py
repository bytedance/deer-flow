"""Final transport-boundary authorization and private credential injection."""

import asyncio
from collections.abc import Mapping
from urllib.parse import urlsplit

from langchain_core.tools import ToolException

from deerflow.authz.user_policy import get_user_security_store
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.headers import apply_header_overrides, header_spellings, illegal_header_value_reason
from deerflow.runtime.user_context import get_current_user, resolve_runtime_user_id
from deerflow.security.defaults import DEFAULT_TOOL_TARGETS


def validate_personal_server(server):
    if server.type not in {"http", "sse"}:
        raise ValueError("User-isolated MCP requires HTTP/SSE; Gateway stdio execution is disabled")
    url = urlsplit(server.url or "")
    if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
        raise ValueError("Personal MCP endpoints must be HTTP(S) URLs without embedded credentials, query parameters or fragments")
    header = server.user_auth.header if server.user_auth else "Authorization"
    if not header or any(not (c.isascii() and (c.isalnum() or c in "!#$%&'*+-.^_`|~")) for c in header):
        raise ValueError("Invalid personal credential header name")
    if header.lower() in {"host", "content-length", "connection", "transfer-encoding", "accept", "content-type"}:
        raise ValueError("A routing or transport header cannot hold personal credentials")
    if any(name.lower() not in {header.lower(), "accept", "content-type"} for name in (server.headers or {})):
        raise ValueError("User-isolated MCP cannot retain additional shared headers")
    if server.oauth or server.headers_from_context or (server.user_auth and server.user_auth.users):
        raise ValueError("Use private personal credentials instead of shared OAuth, context or user-map credentials")
    if server.task_toolsets:
        raise ValueError("Personal credentials are not supported by background MCP task polling yet")
    return header


def build_personal_auth_interceptor(extensions_config):
    async def personal_auth(request, handler):
        def resolve():
            # Reload configuration and grants for every call, including wrappers
            # assembled before a revocation or server disable.
            current = ExtensionsConfig.from_file().mcp_servers.get(request.server_name)
            original = extensions_config.mcp_servers.get(request.server_name)
            if current is None or not current.enabled or original is None:
                raise ToolException("MCP server is unavailable")
            if current.model_dump() != original.model_dump():
                raise ToolException("MCP configuration changed; start a new request before using this tool")
            # Interceptors receive the raw MCP name. Reconstruct the bound name
            # so both opt-out names and prefix combinations remain reserved,
            # including wrappers assembled before this policy was installed.
            bound_name = f"{request.server_name}_{request.name}" if current.tool_name_prefix else request.name
            if bound_name in DEFAULT_TOOL_TARGETS:
                raise ToolException("This MCP tool name is reserved for a default capability")
            try:
                header = validate_personal_server(current)
            except ValueError as exc:
                raise ToolException(str(exc)) from None
            runtime = getattr(request, "runtime", None)
            user_id = resolve_runtime_user_id(runtime)
            user = get_current_user()
            # An admin may manage all tools but still needs their OWN credential.
            admin = user is not None and str(user.id) == user_id and getattr(user, "system_role", None) == "admin"
            context = getattr(runtime, "context", None)
            if isinstance(context, Mapping) and str(context.get("user_id", "")) == user_id:
                # Same server-stamped owner context used by the authz adapter;
                # scheduled/internal calls need not have that owner ambient.
                admin = context.get("user_role") == "admin"
            store = get_user_security_store()
            if not user_id or user_id == "default" or (not admin and ("mcp_server", request.server_name) not in store.grants(user_id)):
                raise ToolException("Your account is not authorized to use this MCP server")
            credential = store.get_credential(user_id, request.server_name)
            if not credential:
                raise ToolException("Save your personal credential for this tool in Settings before using it")
            if illegal_header_value_reason(credential):
                raise ToolException("Your personal credential is not a valid HTTP header value")
            return header, credential, current.headers

        header, credential, static_headers = await asyncio.to_thread(resolve)
        headers = apply_header_overrides(request.headers, {header: credential}, spellings=header_spellings(static_headers))
        return await handler(request.override(headers=headers))

    return personal_auth
