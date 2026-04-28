"""
Test script to verify MCP multi-server error handling issue.

Problem: When using langchain-mcp-adapters' MultiServerMCPClient with multiple
SSE servers, if one server is unavailable, the entire get_tools() call fails
and returns no tools from ANY server.

Root cause: In langchain_mcp_adapters/client.py line 197:
    tools_list = await asyncio.gather(*load_mcp_tool_tasks)

asyncio.gather() without return_exceptions=True will raise an exception if
ANY task fails, causing all tools to be lost.

Usage:
    cd /root/code/deer-flow
    # Start both servers first:
    cd backend && uv run python ../tests/mcp_test/weather_server.py &
    cd backend && uv run python ../tests/mcp_test/calculator_server.py &
    sleep 3
    
    # Run test with both servers up:
    cd backend && uv run python ../tests/mcp_test/test_mcp_error_handling.py
    
    # Kill calculator server and test again:
    pkill -f calculator_server
    cd backend && uv run python ../tests/mcp_test/test_mcp_error_handling.py
"""

import asyncio
import sys
import time
from typing import Any

sys.path.insert(0, "/root/code/deer-flow/backend/packages/harness")


async def test_multi_server_with_one_down():
    """Test that demonstrates the issue: one server down breaks all tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    print("=" * 60)
    print("TEST: MultiServerMCPClient with one server unavailable")
    print("=" * 60)

    # Configure two servers - weather (port 8001) and calculator (port 8002)
    connections = {
        "weather": {
            "url": "http://127.0.0.1:18001/sse",
            "transport": "sse",
        },
        "calculator": {
            "url": "http://127.0.0.1:18002/sse",
            "transport": "sse",
        },
    }

    client = MultiServerMCPClient(connections, tool_name_prefix=True)

    try:
        tools = await client.get_tools()
        print(f"\nSUCCESS: Loaded {len(tools)} tools")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:50]}...")
        return True
    except Exception as e:
        print(f"\nFAILURE: {type(e).__name__}: {e}")
        print("This demonstrates the bug: one server down causes ALL tools to fail!")
        return False


async def test_single_server_at_a_time():
    """Test loading tools from each server individually."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    print("\n" + "=" * 60)
    print("TEST: Loading tools from each server individually")
    print("=" * 60)

    servers = {
        "weather": "http://127.0.0.1:18001/sse",
        "calculator": "http://127.0.0.1:18002/sse",
    }

    for name, url in servers.items():
        print(f"\nTesting {name} server ({url})...")
        client = MultiServerMCPClient(
            {name: {"url": url, "transport": "sse"}},
            tool_name_prefix=True,
        )
        try:
            tools = await client.get_tools()
            print(f"  SUCCESS: Loaded {len(tools)} tools from {name}")
            for tool in tools:
                print(f"    - {tool.name}")
        except Exception as e:
            print(f"  FAILURE: {type(e).__name__}: {e}")


async def test_fixed_multi_server():
    """
    Demonstrate the fix: use asyncio.gather with return_exceptions=True
    to handle individual server failures gracefully.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools
    from langchain_core.tools import BaseTool

    print("\n" + "=" * 60)
    print("TEST: Fixed approach - graceful degradation")
    print("=" * 60)

    connections = {
        "weather": {
            "url": "http://127.0.0.1:18001/sse",
            "transport": "sse",
        },
        "calculator": {
            "url": "http://127.0.0.1:18002/sse",
            "transport": "sse",
        },
    }

    all_tools: list[BaseTool] = []
    load_tasks = []

    for name, connection in connections.items():
        task = asyncio.create_task(
            load_mcp_tools(
                None,
                connection=connection,
                server_name=name,
                tool_name_prefix=True,
            )
        )
        load_tasks.append((name, task))

    # FIX: Use return_exceptions=True to handle individual failures
    results = await asyncio.gather(
        *[task for _, task in load_tasks],
        return_exceptions=True,
    )

    for (name, _), result in zip(load_tasks, results):
        if isinstance(result, Exception):
            print(f"  WARNING: Failed to load tools from '{name}': {type(result).__name__}: {result}")
        else:
            print(f"  SUCCESS: Loaded {len(result)} tools from '{name}'")
            all_tools.extend(result)

    print(f"\nTotal tools loaded: {len(all_tools)}")
    for tool in all_tools:
        print(f"  - {tool.name}")

    return len(all_tools) > 0


async def check_server_health():
    """Check if test servers are running."""
    import httpx

    print("Checking server health...")
    servers = {
        "weather": "http://127.0.0.1:18001",
        "calculator": "http://127.0.0.1:18002",
    }

    for name, url in servers.items():
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/sse")
                print(f"  {name} ({url}): UP (status: {resp.status_code})")
        except Exception as e:
            print(f"  {name} ({url}): DOWN ({type(e).__name__})")


async def main():
    print("MCP Multi-Server Error Handling Test")
    print("=" * 60)

    await check_server_health()

    await test_single_server_at_a_time()

    success = await test_multi_server_with_one_down()

    await test_fixed_multi_server()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if success:
        print("Both servers are up - all tests passed")
    else:
        print("One server is down - demonstrates the bug in langchain-mcp-adapters")
        print("The fix uses asyncio.gather(return_exceptions=True)")


if __name__ == "__main__":
    asyncio.run(main())
