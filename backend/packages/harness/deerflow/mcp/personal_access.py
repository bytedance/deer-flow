"""Current host authority for personal connections saved with admin privileges."""

from collections.abc import Awaitable, Callable

from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig

PersonalMcpAdminChecker = Callable[[str], Awaitable[bool]]
_admin_checker: PersonalMcpAdminChecker | None = None


def set_personal_mcp_admin_checker(checker: PersonalMcpAdminChecker | None) -> PersonalMcpAdminChecker | None:
    """Install the host's fresh authority lookup, returning the previous lookup."""
    global _admin_checker
    previous, _admin_checker = _admin_checker, checker
    return previous


def requires_admin(server: McpServerConfig) -> bool:
    # Only definitions admitted under the ordinary-user policy carry True.
    # Missing markers, including legacy personal files, require authority too.
    return (server.model_extra or {}).get("personal_public_network") is not True


async def _is_current_admin(owner: str) -> bool:
    checker = _admin_checker
    if checker is None:
        return False
    try:
        return await checker(owner) is True
    except Exception:
        # Authority lookup failures must not reuse a previous admin decision.
        return False


async def require_personal_mcp_access(owner: str, server: McpServerConfig) -> None:
    if requires_admin(server) and not await _is_current_admin(owner):
        raise ToolException("Current administrator access is required for this personal MCP connection; save it again under your current permissions")


async def authorized_personal_config(owner: str, config: ExtensionsConfig) -> ExtensionsConfig:
    """Omit privileged connections before discovery can launch or contact them."""
    if not any(server.enabled and requires_admin(server) for server in config.mcp_servers.values()) or await _is_current_admin(owner):
        return config
    return config.model_copy(update={"mcp_servers": {name: server for name, server in config.mcp_servers.items() if not requires_admin(server)}})
