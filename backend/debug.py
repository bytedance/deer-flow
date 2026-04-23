#!/usr/bin/env python
"""
Debug script for lead_agent.
Run this file directly in VS Code with breakpoints.

Requirements:
    Run with `uv run` from the backend/ directory so that the uv workspace
    resolves deerflow-harness and app packages correctly:

        cd backend && PYTHONPATH=. uv run python debug.py

Usage:
    1. Set breakpoints in agent.py or other files
    2. Press F5 or use "Run and Debug" panel
    3. Input messages in the terminal to interact with the agent
"""

import asyncio
import logging

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents import make_lead_agent

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def main():
    # Initialize MCP tools at startup
    try:
        from deerflow.mcp import initialize_mcp_tools

        await initialize_mcp_tools()
    except Exception as e:
        print(f"Warning: Failed to initialize MCP tools: {e}")

    # Create agent with default config
    config = {
        "configurable": {
            "thread_id": "debug-thread-001",
            "thinking_enabled": True,
            "is_plan_mode": True,
            # Uncomment to use a specific model
            "model_name": "kimi-k2.5",
        }
    }

    runtime = Runtime(context={"thread_id": config["configurable"]["thread_id"]})
    config["configurable"]["__pregel_runtime"] = runtime

    agent = make_lead_agent(config)

    session = PromptSession(history=InMemoryHistory()) if _HAS_PROMPT_TOOLKIT else None

    print("=" * 50)
    print("Lead Agent Debug Mode")
    print("Type 'quit' or 'exit' to stop")
    if not _HAS_PROMPT_TOOLKIT:
        print("Tip: `uv sync --group dev` to enable arrow-key & history support")
    print("=" * 50)

    while True:
        try:
            if session:
                user_input = (await session.prompt_async("\nYou: ")).strip()
            else:
                user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            # Invoke the agent
            state = {"messages": [HumanMessage(content=user_input)]}
            result = await agent.ainvoke(state, config=config)

            # Print the response
            if result.get("messages"):
                last_message = result["messages"][-1]
                print(f"\nAgent: {last_message.content}")

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
