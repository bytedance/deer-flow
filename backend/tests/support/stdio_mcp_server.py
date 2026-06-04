"""Minimal stdio MCP server used by MCP regression tests.

Runs a real ``mcp`` stdio server (no mocks) so tests exercise the actual
``anyio`` task-group machinery in ``stdio_client`` / ``ClientSession``. This
is what mock-based tests cannot do — and is exactly what let issue #3379
("Attempted to exit cancel scope in a different task") slip through.

Launch with::

    python -m tests.support.stdio_mcp_server
    # or
    python <path>/tests/support/stdio_mcp_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("deerflow-test-stdio")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text back, prefixed."""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
