"""FastMCP stdio server wrapping DeerFlow REST API."""

import asyncio
import json
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("deerflow")

DEERFLOW_URL = os.environ.get("DEERFLOW_URL", "http://localhost:2026")
DEERFLOW_EMAIL = os.environ.get("DEERFLOW_EMAIL", "")
DEERFLOW_PASSWORD = os.environ.get("DEERFLOW_PASSWORD", "")

_client: Optional[httpx.AsyncClient] = None
_csrf_token: str = ""


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=DEERFLOW_URL,
        timeout=310.0,
        follow_redirects=True,
    )


async def _login(client: httpx.AsyncClient) -> None:
    global _csrf_token
    resp = await client.post(
        "/api/v1/auth/login/local",
        data={"username": DEERFLOW_EMAIL, "password": DEERFLOW_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    _csrf_token = client.cookies.get("csrf_token", "")


async def _get_client() -> tuple[httpx.AsyncClient, str]:
    """Return (client, csrf_token), creating and logging in on first call."""
    global _client, _csrf_token
    if _client is None:
        _client = _make_client()
        await _login(_client)
    return _client, _csrf_token


async def _authed_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Make an authenticated request, re-authing once on 401/403."""
    global _client, _csrf_token
    client, csrf = await _get_client()
    headers = kwargs.pop("headers", {})
    headers["X-CSRF-Token"] = csrf
    resp = await client.request(method, path, headers=headers, **kwargs)
    if resp.status_code in (401, 403):
        # Re-auth once and retry
        await _login(client)
        headers["X-CSRF-Token"] = _csrf_token
        resp = await client.request(method, path, headers=headers, **kwargs)
    return resp


def _creds_missing() -> Optional[str]:
    if not DEERFLOW_EMAIL or not DEERFLOW_PASSWORD:
        return (
            "Error: DEERFLOW_EMAIL and DEERFLOW_PASSWORD env vars must be set. "
            "Export them before starting the server."
        )
    return None


def _extract_last_assistant_message(data: dict) -> str:
    """Pull the final assistant text from a /runs/wait response."""
    # The response may be a list of messages or a dict with a 'messages' key
    messages = []
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", [])

    for msg in reversed(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "assistant":
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                return "\n".join(p for p in parts if p)
    return json.dumps(data)


@mcp.tool()
async def deerflow_run(prompt: str, thread_id: str = "") -> str:
    """Submit a prompt to DeerFlow and wait for the response (up to 300 s).

    Args:
        prompt: The user message to send.
        thread_id: Optional existing thread ID for multi-turn conversation.
                   Leave empty for a fresh stateless run.

    Returns:
        The last assistant message text, or an error string.
    """
    err = _creds_missing()
    if err:
        return err

    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": prompt}]},
    }

    if thread_id:
        path = f"/api/threads/{thread_id}/runs/wait"
    else:
        path = "/api/runs/wait"

    try:
        resp = await _authed_request("POST", path, json=body)
        resp.raise_for_status()
        data = resp.json()
        return _extract_last_assistant_message(data)
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def deerflow_create_thread() -> str:
    """Create a new DeerFlow thread for multi-turn conversations.

    Returns:
        The thread_id string, or an error string.
    """
    err = _creds_missing()
    if err:
        return err

    try:
        resp = await _authed_request("POST", "/api/threads", json={})
        resp.raise_for_status()
        data = resp.json()
        return data.get("thread_id", json.dumps(data))
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def deerflow_health() -> str:
    """Check DeerFlow service health (no auth required).

    Returns:
        JSON string with health status.
    """
    try:
        async with httpx.AsyncClient(base_url=DEERFLOW_URL, timeout=10.0) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
