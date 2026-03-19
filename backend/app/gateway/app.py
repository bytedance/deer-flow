import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.gateway.config import get_gateway_config
from app.gateway.routers import (
    agents,
    mcp,
    memory,
)
from deerflow.config.app_config import get_app_config

#    Configure logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""

    #    Load 配置 and 检查 necessary 环境 variables at startup


    try:
        get_app_config()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    #    NOTE: MCP tools initialization is NOT done here because:


    #    1. Gateway doesn't use MCP tools - they are used by Agents in the LangGraph Server


    #    2. Gateway and LangGraph Server are separate processes with independent caches


    #    MCP tools are lazily initialized in LangGraph Server when 第一 needed



    yield

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""
#   # DeerFlow API Gateway



API Gateway for DeerFlow - A LangGraph-based AI 代理 后端 with sandbox execution capabilities.

#   ## Features



- **MCP Configuration**: Manage 模型 Context Protocol (MCP) 服务器 configurations
- **内存 Management**: Access and manage global 内存 数据 for personalized conversations
- **Health Monitoring**: System health 检查 endpoints

#   ## Architecture



LangGraph requests are handled by nginx reverse proxy.
This gateway provides custom endpoints for MCP configuration and 内存.
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    #    CORS is handled by nginx - no need 对于 FastAPI 中间件



    #    Include routers


    #    MCP API is mounted at /接口/mcp


    app.include_router(mcp.router)

    #    内存 API is mounted at /接口/内存


    app.include_router(memory.router)

    #    Agents API is mounted at /接口/agents


    app.include_router(agents.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """Health 检查 endpoint.

        Returns:
            Service health status information.
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    return app


#    Create app instance 对于 uvicorn


app = create_app()
