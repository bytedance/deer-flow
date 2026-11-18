"""Bind personal MCP authority to fresh Gateway account records."""

import asyncio
from contextlib import asynccontextmanager

from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, is_auth_disabled
from app.gateway.deps import get_local_provider
from deerflow.mcp.personal_access import set_personal_mcp_admin_checker


async def _is_current_admin(owner: str) -> bool:
    if is_auth_disabled() and owner == AUTH_DISABLED_USER_ID:
        return True
    user = await get_local_provider().get_user(owner)
    return user is not None and user.system_role == "admin"


@asynccontextmanager
async def personal_mcp_authority():
    loop = asyncio.get_running_loop()

    async def check(owner: str) -> bool:
        if asyncio.get_running_loop() is loop:
            return await _is_current_admin(owner)
        # Synchronous tool discovery runs on assembly workers with their own
        # loops. Keep the shared database pool on the Gateway's owning loop.
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_is_current_admin(owner), loop))

    previous = set_personal_mcp_admin_checker(check)
    try:
        yield
    finally:
        set_personal_mcp_admin_checker(previous)
