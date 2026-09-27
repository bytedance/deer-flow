"""Public-network policy for non-operator personal HTTP MCP connections."""

import asyncio

import httpx

from deerflow.community.url_safety import validate_public_http_url


def personal_httpx_client_factory(headers=None, timeout=None, auth=None):
    async def check(request: httpx.Request):
        error = await asyncio.to_thread(validate_public_http_url, str(request.url), action="connect to")
        if error:
            raise ValueError("Personal MCP connections require a public HTTP(S) endpoint")

    kwargs = {"headers": headers, "auth": auth, "follow_redirects": False, "trust_env": False, "event_hooks": {"request": [check]}}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return httpx.AsyncClient(**kwargs)
