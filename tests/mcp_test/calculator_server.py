"""MCP Test Server 2 - Calculator Server (SSE transport)"""

import asyncio
import signal
import uvicorn
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calculator-server")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide two numbers."""
    if b == 0:
        return "Error: Division by zero"
    return a / b


if __name__ == "__main__":
    # Handle signals gracefully
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = mcp.sse_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=18002, log_level="info")
    server = uvicorn.Server(config)

    # Don't handle SIGINT/SIGTERM to keep running
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    loop.run_until_complete(server.serve())
