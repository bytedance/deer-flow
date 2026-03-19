#   !/usr/bin/env python


"""
Debug script for lead_agent.
Run this 文件 directly in VS Code with breakpoints.

Requirements:
    Run with `uv 运行` from the 后端/ 目录 so that the uv 工作区
    resolves deerflow-harness and app packages correctly:

        cd 后端 && PYTHONPATH=. uv 运行 python 调试.py

Usage:
    1. Set breakpoints in 代理.py or other files
    2. Press F5 or use "Run and Debug" panel
    3. Input messages in the terminal to interact with the 代理
"""

import asyncio
import logging

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from deerflow.agents import make_lead_agent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def main():
    #    Initialize MCP tools at startup


    try:
        from deerflow.mcp import initialize_mcp_tools

        await initialize_mcp_tools()
    except Exception as e:
        print(f"Warning: Failed to initialize MCP tools: {e}")

    #    Create 代理 with 默认 配置


    config = {
        "configurable": {
            "thread_id": "debug-thread-001",
            "thinking_enabled": True,
            "is_plan_mode": True,
            #    Uncomment to use a specific 模型


            "model_name": "kimi-k2.5",
        }
    }

    agent = make_lead_agent(config)

    print("=" * 50)
    print("Lead Agent Debug Mode")
    print("Type 'quit' or 'exit' to stop")
    print("=" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            #    Invoke the 代理


            state = {"messages": [HumanMessage(content=user_input)]}
            result = await agent.ainvoke(state, config=config, context={"thread_id": "debug-thread-001"})

            #    Print the 响应


            if result.get("messages"):
                last_message = result["messages"][-1]
                print(f"\nAgent: {last_message.content}")

        except KeyboardInterrupt:
            print("\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
