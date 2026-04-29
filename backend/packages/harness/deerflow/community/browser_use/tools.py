"""BrowserUse tool — drives a real Chromium browser to complete web tasks.

Wraps the `browser-use` library as a single LangChain tool.  The tool
accepts a natural-language task description and returns the final result
after the browser automation finishes.

Requirements (in the langgraph container):
  - pip: browser-use playwright
  - system: chromium-browser (or `playwright install chromium`)
"""

from __future__ import annotations

import logging

from langchain.tools import tool

logger = logging.getLogger(__name__)


@tool("browser_use", parse_docstring=True)
async def browser_use_tool(task: str) -> str:
    """Control a real web browser to complete tasks that require interaction.

    Use this instead of web_fetch when:
    - The page requires JavaScript to render (SPA / React / Vue apps)
    - You need to fill forms, click buttons, or log in
    - You need to navigate multi-step flows (checkout, registration, etc.)
    - web_fetch returns empty or incomplete content

    Do NOT use this for simple page reads — prefer web_fetch for speed.

    Args:
        task: Natural language description of what to do in the browser.
              Example: "Go to example.com/pricing and extract all plan names and prices"
    """
    try:
        from browser_use import Agent as BrowserAgent
        from browser_use import BrowserConfig
    except ImportError:
        return (
            "ERROR: browser-use is not installed. "
            "Run: uv pip install browser-use && playwright install chromium"
        )

    from deerflow.config import get_app_config

    config = get_app_config()

    # Reuse the first configured model — browser-use needs an LLM internally.
    # We use ChatOpenAI-compatible interface since that's what config.yaml defines.
    try:
        from langchain_openai import ChatOpenAI

        model_cfg = config.models[0] if config.models else None
        if model_cfg is None:
            return "ERROR: No models configured in config.yaml"

        llm = ChatOpenAI(
            model=getattr(model_cfg, "model", "gpt-4o"),
            base_url=getattr(model_cfg, "base_url", None),
            api_key=getattr(model_cfg, "api_key", None),
            temperature=0,
        )
    except Exception as e:
        return f"ERROR: Failed to initialize LLM for browser-use: {e}"

    try:
        browser_config = BrowserConfig(headless=True, disable_security=True)
        agent = BrowserAgent(task=task, llm=llm, browser_config=browser_config)
        result = await agent.run(max_steps=20)
        # browser-use returns an AgentHistoryList; get the final output
        final = result.final_result()
        return str(final) if final else "Task completed but produced no text output."
    except Exception as e:
        logger.exception("browser_use_tool failed: %s", e)
        return f"Browser automation failed: {e}"
