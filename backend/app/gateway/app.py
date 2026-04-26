"""
API网关应用 — DeerFlow的FastAPI入口

===================
设计思路说明
===================

**为什么需要API网关**：
1. 统一入口：为前端提供统一的REST API接口
2. 路由分发：将不同类型的请求路由到相应的处理器
3. 生命周期管理：协调LangGraph运行时和IM频道的启动/停止

**核心设计模式**：
- 工厂模式：create_app()函数负责创建和配置应用
- 上下文管理器：lifespan管理应用生命周期
- 模块化路由：每个路由器独立管理自己的端点

**架构设计**：
```
                    ┌─────────────────────────────────────┐
                    │         FastAPI Application         │
                    │         (create_app())              │
                    └─────────────────────────────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
            │   Lifespan   │  │    Routers   │  │   Health     │
            │   Manager    │  │   (11个)     │  │   Check      │
            └──────────────┘  └──────────────┘  └──────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐
  │  Config │ │LangGraph│ │ Channels│
  │  Load   │ │ Runtime │ │ Service │
  └─────────┘ └─────────┘ └─────────┘
```

**为什么使用lifespan而不是startup/shutdown事件**：
1. 异步上下文管理器更Pythonic
2. 自动处理异常和资源清理
3. 更容易编写测试

**路由设计原则**：
- 按功能模块划分（models/mcp/memory等）
- RESTful风格设计
- 清晰的URL层级结构
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.gateway.config import get_gateway_config
from app.gateway.deps import langgraph_runtime
from app.gateway.routers import (
    agents,
    artifacts,
    assistants_compat,
    channels,
    mcp,
    memory,
    models,
    runs,
    skills,
    suggestions,
    thread_runs,
    threads,
    uploads,
)
from deerflow.config.app_config import get_app_config

# 配置日志系统
# 为什么这样配置：
# - INFO级别：生产环境合适的详细程度
# - 统一格式：便于日志聚合和分析
# - 时间戳：追踪问题时需要精确时间
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理器

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 启动时加载配置并验证
    2. 初始化LangGraph运行时组件
    3. 启动IM频道服务
    4. 停止时清理所有资源

    **为什么使用异步上下文管理器**：
    - FastAPI原生支持lifespan参数
    - 自动处理异常和资源清理
    - yield前后分别对应startup和shutdown

    **启动流程**：
    1. 加载应用配置（验证环境变量）
    2. 初始化LangGraph运行时
    3. 启动IM频道服务（可选）
    4. yield控制权交给应用

    **关闭流程**：
    1. 停止IM频道服务
    2. 关闭LangGraph运行时
    3. 记录关闭日志

    **为什么频道服务是可选的**：
    - 不是所有部署都需要IM集成
    - 频道服务失败不应阻止网关启动
    - 便于在不同环境中灵活配置
    """

    # 启动阶段：加载配置并验证必要的环境变量
    try:
        get_app_config()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    # 初始化LangGraph运行时组件（StreamBridge、RunManager、checkpointer、store）
    # 为什么需要这些组件：
    # - StreamBridge: 处理流式响应
    # - RunManager: 管理运行状态
    # - checkpointer: 状态持久化
    # - store: 线程数据存储
    async with langgraph_runtime(app):
        logger.info("LangGraph runtime initialised")

        # 如果配置了IM频道，则启动频道服务
        # 为什么用try-except包裹：
        # - 频道服务是可选功能
        # - 不应该因为频道服务失败而阻止网关启动
        try:
            from app.channels.service import start_channel_service

            channel_service = await start_channel_service()
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        yield  # 应用运行期间

        # 关闭阶段：停止频道服务
        try:
            from app.channels.service import stop_channel_service

            await stop_channel_service()
        except Exception:
            logger.exception("Failed to stop channel service")

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """
    创建并配置FastAPI应用

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 创建FastAPI应用实例
    2. 配置应用元数据和文档
    3. 注册所有路由
    4. 设置生命周期管理

    **为什么使用工厂函数**：
    - 便于测试：可以创建多个独立实例
    - 灵活配置：可以根据参数动态配置
    - 延迟初始化：避免导入时的副作用

    **路由组织原则**：
    - 按功能模块划分（models/mcp/memory等）
    - 每个路由器负责自己的URL前缀
    - 便于维护和扩展

    **为什么不需要CORS中间件**：
    - nginx反向代理已经处理CORS
    - 避免重复配置
    - 简化网关职责

    **返回值**：
        配置好的FastAPI应用实例
    """

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""
## DeerFlow API Gateway

API Gateway for DeerFlow - A LangGraph-based AI agent backend with sandbox execution capabilities.

### Features

- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints

### Architecture

LangGraph requests are handled by nginx reverse proxy.
This gateway provides custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "threads",
                "description": "Manage DeerFlow thread-local filesystem data",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "assistants-compat",
                "description": "LangGraph Platform-compatible assistants API (stub)",
            },
            {
                "name": "runs",
                "description": "LangGraph Platform-compatible runs lifecycle (create, stream, cancel)",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    # CORS由nginx处理 - 这里不需要FastAPI中间件
    # 为什么这样设计：
    # - nginx作为入口更高效
    # - 统一管理跨域策略
    # - 减少应用层负担

    # 注册所有路由器
    # 为什么按这个顺序注册：
    # 1. 核心功能（models/mcp/memory）
    # 2. 扩展功能（skills/artifacts）
    # 3. 线程管理（threads/uploads）
    # 4. 代理相关（agents/suggestions）
    # 5. 频道集成（channels）
    # 6. 兼容层（assistants_compat/thread_runs/runs）

    # Models API挂载在 /api/models
    # 提供模型查询功能
    app.include_router(models.router)

    # MCP API挂载在 /api/mcp
    # 管理MCP服务器配置
    app.include_router(mcp.router)

    # Memory API挂载在 /api/memory
    # 访问和管理全局记忆数据
    app.include_router(memory.router)

    # Skills API挂载在 /api/skills
    # 管理技能及其配置
    app.include_router(skills.router)

    # Artifacts API挂载在 /api/threads/{thread_id}/artifacts
    # 访问和下载线程产物
    app.include_router(artifacts.router)

    # Uploads API挂载在 /api/threads/{thread_id}/uploads
    # 上传和管理用户文件
    app.include_router(uploads.router)

    # Thread cleanup API挂载在 /api/threads/{thread_id}
    # 管理线程本地文件系统数据
    app.include_router(threads.router)

    # Agents API挂载在 /api/agents
    # 创建和管理自定义代理
    app.include_router(agents.router)

    # Suggestions API挂载在 /api/threads/{thread_id}/suggestions
    # 生成后续问题建议
    app.include_router(suggestions.router)

    # Channels API挂载在 /api/channels
    # 管理IM频道集成
    app.include_router(channels.router)

    # Assistants兼容API（LangGraph Platform stub）
    # 提供与LangGraph Platform兼容的接口
    app.include_router(assistants_compat.router)

    # Thread Runs API（LangGraph Platform兼容的运行生命周期）
    # 管理线程的创建、流式传输和取消
    app.include_router(thread_runs.router)

    # 无状态Runs API（无需预存在thread的stream/wait）
    # 一次性运行，不关联持久化线程
    app.include_router(runs.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """
        健康检查端点

        **为什么需要健康检查**：
        - 容器编排系统（如K8s）需要探测服务状态
        - 负载均衡器需要判断实例是否可用
        - 监控系统需要收集服务健康指标

        **返回值**：
        - status: 服务状态（healthy/unhealthy）
        - service: 服务名称
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    return app


# 为uvicorn创建应用实例
# 为什么在模块级别创建：
# - uvicorn需要导入一个可调用对象
# - 简化启动命令
# - 符合FastAPI最佳实践
app = create_app()
