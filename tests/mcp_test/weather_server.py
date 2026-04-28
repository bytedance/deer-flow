"""MCP Test Server 1 - Weather Server (SSE transport)"""

import asyncio
import signal
import uvicorn
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather-server")


@mcp.tool()
def get_weather(city: str) -> str:
    """Get weather information for a city."""
    return f"The weather in {city} is sunny, 25°C"


@mcp.tool()
def get_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city."""
    return f"{days}-day forecast for {city}: Sunny, 25°C / Rainy, 18°C / Cloudy, 22°C"


if __name__ == "__main__":
    # Handle signals gracefully
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = mcp.sse_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=18001, log_level="info")
    server = uvicorn.Server(config)

    # Don't handle SIGINT/SIGTERM to keep running
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    loop.run_until_complete(server.serve())
