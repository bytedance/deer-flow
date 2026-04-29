"""browser-use MCP server — exposes browser automation as an MCP tool.

Transport: Streamable HTTP (POST /mcp)
DeerFlow connects via extensions_config.json with type=http, url=http://browser-use-mcp:8000/mcp
"""

from __future__ import annotations

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("browser-use")

_MAX_CONCURRENT = int(os.environ.get("BROWSER_MAX_CONCURRENT", "2"))
_TIMEOUT_SECONDS = int(os.environ.get("BROWSER_TIMEOUT_SECONDS", "120"))
_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT)
    return _SEMAPHORE


def _build_llm():
    """Build LLM from env vars (OpenAI-compatible)."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "gpt-4o"),
        base_url=os.environ.get("LLM_BASE_URL") or None,
        api_key=os.environ.get("LLM_API_KEY", "placeholder"),
        temperature=0,
    )


@mcp.tool()
async def browser_use(task: str) -> str:
    """Control a real web browser to complete tasks that require interaction.

    Use this instead of web_fetch when the page requires JavaScript rendering,
    user interaction (clicks, form fills, login), or when web_fetch returns
    empty/incomplete content from a dynamic page.

    Args:
        task: Natural language description of what to do in the browser.
              Example: "Go to example.com/pricing and extract all plan names and prices"
    """
    from browser_use import Agent as BrowserAgent, Browser, BrowserConfig

    llm = _build_llm()
    sem = _get_semaphore()
    browser_cfg = BrowserConfig(headless=True, disable_security=True)

    async with sem:
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
                logger.warning("browser_use timed out after %ds", _TIMEOUT_SECONDS)
                return f"Browser task timed out after {_TIMEOUT_SECONDS}s."
            except Exception as e:
                logger.exception("browser_use failed")
                return f"Browser automation failed: {e}"


if __name__ == "__main__":
    import uvicorn
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
