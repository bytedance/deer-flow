"""BrowserUse tool — drives a real Chromium browser to complete web tasks.

Resource management:
- Browser is opened/closed as an async context manager — guaranteed cleanup
  even when the task raises an exception or times out.
- asyncio.wait_for() enforces a hard wall-clock timeout so the LangGraph
  coroutine cannot be blocked indefinitely by a hanging page.
- A module-level semaphore caps concurrent Chromium instances to avoid OOM.
"""

from __future__ import annotations

import asyncio
import logging

from langchain.tools import tool

logger = logging.getLogger(__name__)

# Max simultaneous Chromium instances in this LangGraph process.
# Each headless Chromium uses ~200-400 MB; keep this low.
_MAX_CONCURRENT = 2
_SEMAPHORE: asyncio.Semaphore | None = None

# Hard timeout per browser task (seconds).
_TIMEOUT_SECONDS = 120


def _get_semaphore() -> asyncio.Semaphore:
    """Return (or lazily create) the module-level semaphore."""
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT)
    return _SEMAPHORE


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
        from browser_use import Browser, BrowserConfig
    except ImportError:
        return (
            "ERROR: browser-use is not installed. "
            "Run: uv pip install browser-use && playwright install chromium"
        )

    from deerflow.config import get_app_config
    from langchain_openai import ChatOpenAI

    config = get_app_config()
    model_cfg = config.models[0] if config.models else None
    if model_cfg is None:
        return "ERROR: No models configured in config.yaml"

    llm = ChatOpenAI(
        model=getattr(model_cfg, "model", "gpt-4o"),
        base_url=getattr(model_cfg, "base_url", None),
        api_key=getattr(model_cfg, "api_key", None),
        temperature=0,
    )

    sem = _get_semaphore()
    browser_cfg = BrowserConfig(headless=True, disable_security=True)

    async with sem:
        # Browser is always closed when this block exits — exception or not.
        async with Browser(config=browser_cfg) as browser:
            try:
                agent = BrowserAgent(task=task, llm=llm, browser=browser)
                result = await asyncio.wait_for(
                    agent.run(max_steps=20),
                    timeout=_TIMEOUT_SECONDS,
                )
                final = result.final_result()
                return str(final) if final else "Task completed but produced no text output."
            except asyncio.TimeoutError:
                logger.warning("browser_use_tool: task timed out after %ds", _TIMEOUT_SECONDS)
                return f"Browser task timed out after {_TIMEOUT_SECONDS}s. Try a simpler or more specific task."
            except Exception as e:
                logger.exception("browser_use_tool: task failed")
                return f"Browser automation failed: {e}"
