#!/usr/bin/env python3
"""
Simple debug client to test the DeerFlow server.
Set breakpoints anywhere in this file or the server code to debug.
"""

import httpx
import asyncio
import json

# Server configuration
BASE_URL = "http://localhost:8000"

# Request payload
request_data = {
    "messages": [
        {
            "role": "user",
            "content": "简单介绍下量子计算"
        }
    ],
    "auto_accepted_plan": True,  # Auto-accept the plan
    "enable_background_investigation": True,
    "enable_web_search": True,
    "max_plan_iterations": 1,
    "max_step_num": 3,
    "max_search_results": 3,
}


async def send_request():
    """Send request to the server and stream the response."""
    print(f"Sending request to {BASE_URL}/api/chat/stream")
    print(f"Request data: {json.dumps(request_data, indent=2)}\n")
    print("=" * 80)
    print("STREAMING RESPONSE:")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/api/chat/stream",
            json=request_data,
            headers={"Accept": "text/event-stream"},
        ) as response:
            if response.status_code != 200:
                print(f"Error: {response.status_code}")
                print(await response.aread())
                return

            # Stream the response
            async for line in response.aiter_lines():
                if line:
                    print(line)
                    # Add breakpoint here to inspect each response line
                    pass


if __name__ == "__main__":
    # Run the async function
    asyncio.run(send_request())
