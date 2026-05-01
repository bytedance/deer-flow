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

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False

load_dotenv()

_LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(log_level: int = logging.INFO) -> None:
    """Route logs to ``debug.log`` using *log_level* for the initial root/file setup.

    This configures the root logger and the ``debug.log`` file handler so logs do
    not print on the interactive console. It is idempotent: any pre-existing
    handlers on the root logger (e.g. installed by ``logging.basicConfig`` in
    transitively imported modules) are removed so the debug session output only
    lands in ``debug.log``.

    Note: later config-driven logging adjustments may change named logger
    verbosity without raising the root logger or file-handler thresholds set
    here, so the eventual contents of ``debug.log`` may not be filtered solely by
    this function's ``log_level`` argument.
    """
    root = logging.root
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    root.setLevel(log_level)

    file_handler = logging.FileHandler("debug.log", mode="a", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(_LOG_FMT, datefmt=_LOG_DATEFMT))
    root.addHandler(file_handler)


async def main():
    # Install file logging first so warnings emitted while loading config do not
    # leak onto the interactive terminal via Python's lastResort handler.
    _setup_logging()

    from deerflow.config import get_app_config
    from deerflow.config.app_config import apply_logging_level

    app_config = get_app_config()
    apply_logging_level(app_config.log_level)

    # Delay the rest of the deerflow imports until *after* logging is installed
    # so that any import-time side effects (e.g. deerflow.agents starts a
    # background skill-loader thread on import) emit logs to debug.log instead
    # of leaking onto the interactive terminal via Python's lastResort handler.
    from langchain_core.messages import HumanMessage
    from langgraph.runtime import Runtime

    from deerflow.agents import make_lead_agent
    from deerflow.mcp import initialize_mcp_tools

    # Initialize MCP tools at startup
    try:
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
    print(f"Logs: debug.log (log_level={app_config.log_level})")
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
