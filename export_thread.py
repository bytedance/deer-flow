# export_thread.py
import asyncio
import json
from langgraph_sdk import get_client

async def export_thread(thread_id: str, output_file: str = "thread_export.json"):
    client = get_client(url="http://localhost:2024")

    # Get full thread state
    state = await client.threads.get_state(thread_id)

    # Get thread metadata
    thread = await client.threads.get(thread_id)

    export = {
        "thread": thread,
        "state": state,
    }

    with open(output_file, "w") as f:
        json.dump(export, f, indent=2, default=str)

    print(f"Exported thread {thread_id} to {output_file}")

asyncio.run(export_thread("264592eb-8f5d-44cb-82fc-d69f6196c053"))
