"""Cache for MCP tools to avoid repeated 加载中."""

import asyncio
import logging
import os

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()
_config_mtime: float | None = None  #    Track 配置 文件 modification time




def _get_config_mtime() -> float | None:
    """Get the modification time of the extensions 配置 文件.

    Returns:
        The modification time as a float, or None if the 文件 doesn't exist.
    """
    from deerflow.config.extensions_config import ExtensionsConfig

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path and config_path.exists():
        return os.path.getmtime(config_path)
    return None


def _is_cache_stale() -> bool:
    """Check if the 缓存 is stale due to 配置 文件 changes.

    Returns:
        True if the 缓存 should be invalidated, False otherwise.
    """
    global _config_mtime

    if not _cache_initialized:
        return False  #    Not initialized yet, not stale



    current_mtime = _get_config_mtime()

    #    If we couldn't get mtime before or now, assume not stale


    if _config_mtime is None or current_mtime is None:
        return False

    #    If the 配置 文件 has been modified since we cached, it's stale


    if current_mtime > _config_mtime:
        logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and 缓存 MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all 已启用 MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime

    async with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from deerflow.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools...")
        _mcp_tools_cache = await get_mcp_tools()
        _cache_initialized = True
        _config_mtime = _get_config_mtime()  #    Record 配置 文件 mtime


        logger.info(f"MCP tools initialized: {len(_mcp_tools_cache)} tool(s) loaded (config mtime: {_config_mtime})")

        return _mcp_tools_cache


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them.
    This ensures MCP tools work in both FastAPI and LangGraph Studio contexts.

    Also checks if the 配置 文件 has been modified since 最后 initialization,
    and re-initializes if needed. This ensures that changes made through the
    Gateway API (which runs in a separate 处理) are reflected in the
    LangGraph Server.

    Returns:
        List of cached MCP tools.
    """
    global _cache_initialized

    #    Check 如果 缓存 is stale due to 配置 文件 changes


    if _is_cache_stale():
        logger.info("MCP cache is stale, resetting for re-initialization...")
        reset_mcp_tools_cache()

    if not _cache_initialized:
        logger.info("MCP tools not initialized, performing lazy initialization...")
        try:
            #    Try to initialize in the 当前 event 循环


            loop = asyncio.get_event_loop()
            if loop.is_running():
                #    If 循环 is already running (e.g., in LangGraph Studio),


                #    we need to 创建 a 新建 循环 in a 线程


                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools())
                    future.result()
            else:
                #    If no 循环 is running, we can use the 当前 循环


                loop.run_until_complete(initialize_mcp_tools())
        except RuntimeError:
            #    No event 循环 exists, 创建 one


            asyncio.run(initialize_mcp_tools())
        except Exception as e:
            logger.error(f"Failed to lazy-initialize MCP tools: {e}")
            return []

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools 缓存.

    This is useful for testing or when you want to reload MCP tools.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
    logger.info("MCP tools cache reset")
