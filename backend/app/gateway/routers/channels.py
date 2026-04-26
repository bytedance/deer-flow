"""IM频道管理路由

===================
设计思路说明
===================

**核心职责**：
提供IM频道（如飞书、Slack、Telegram）的管理API，包括：
1. 查询所有频道的运行状态
2. 重启指定的频道连接

**为什么需要这个模块**：
1. **运维需求**：管理员需要了解各个IM频道的连接状态
2. **故障恢复**：当某个频道连接异常时，可以通过API重启
3. **监控集成**：为监控系统提供标准化的状态查询接口

**设计决策**：
- 简洁的API设计：只提供两个核心端点，避免过度设计
- 异步架构：使用async/await支持高并发场景
- 错误处理：服务未运行时返回空状态而非错误，避免误报
- 延迟加载：从app.channels.service导入，避免循环依赖

**架构说明**：
该模块是Gateway层的HTTP入口，实际逻辑由app.channels.service模块实现。
这种分层设计使得HTTP层只负责请求/响应转换，业务逻辑在service层。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 为什么使用prefix和tags：
# - prefix: 将所有频道相关端点放在/api/channels路径下，符合RESTful规范
# - tags: 用于API文档分组，便于在Swagger UI中浏览
router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelStatusResponse(BaseModel):
    """频道状态响应模型

    为什么这样设计：
    - service_running: 明确指示服务是否在运行，便于监控系统集成
    - channels: 使用dict结构，频道名作为key，便于快速查找和展示

    Attributes:
        service_running: 频道服务是否正在运行
        channels: 各频道的详细状态，key为频道名称，value为频道状态字典
    """
    service_running: bool  # 服务运行状态
    channels: dict[str, dict]  # 各频道的状态信息


class ChannelRestartResponse(BaseModel):
    """频道重启响应模型

    为什么这样设计：
    - success: 明确指示操作是否成功
    - message: 提供人类可读的结果描述，便于调试和日志记录

    Attributes:
        success: 重启操作是否成功
        message: 操作结果的描述信息
    """
    success: bool  # 操作是否成功
    message: str  # 结果描述


@router.get("/", response_model=ChannelStatusResponse)
async def get_channels_status() -> ChannelStatusResponse:
    """获取所有IM频道的状态

    为什么使用GET请求：
    - 符合RESTful规范：查询操作使用GET
    - 支持浏览器直接访问和缓存
    - 幂等性：多次调用结果一致

    设计考虑：
    - 服务未运行时返回空状态而非抛出异常：避免误报，让调用者自行判断
    - 使用函数内导入：避免启动时的循环依赖问题

    Returns:
        ChannelStatusResponse: 包含服务运行状态和各频道详细状态
    """
    # 为什么在函数内部导入：
    # 1. 避免模块加载时的循环依赖
    # 2. app.channels.service可能在运行时才初始化
    # 3. 减少启动时的导入开销
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        # 服务未启动：返回空状态而非错误
        # 这样设计的好处：监控可以区分"服务未启动"和"服务异常"
        return ChannelStatusResponse(service_running=False, channels={})
    status = service.get_status()
    return ChannelStatusResponse(**status)


@router.post("/{name}/restart", response_model=ChannelRestartResponse)
async def restart_channel(name: str) -> ChannelRestartResponse:
    """重启指定的IM频道

    为什么使用POST请求：
    - 重启操作会改变系统状态，不符合GET语义
    - 虽然是幂等操作，但POST更明确表达"执行操作"的意图
    - 未来可能需要在请求体中传递重启参数

    设计考虑：
    - 服务未运行时返回503错误：明确告知客户端服务不可用
    - 重启失败时返回success=false但不抛异常：允许客户端重试
    - 使用不同日志级别：成功用info，失败用warning

    Args:
        name: 频道名称（如"feishu"、"slack"、"telegram"）

    Returns:
        ChannelRestartResponse: 包含操作结果和描述信息

    Raises:
        HTTPException: 当服务未运行时返回503状态码
    """
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        # 使用503 Service Unavailable状态码
        # 明确告知客户端这是临时性问题，可以稍后重试
        raise HTTPException(status_code=503, detail="Channel service is not running")

    success = await service.restart_channel(name)
    if success:
        logger.info("Channel %s restarted successfully", name)
        return ChannelRestartResponse(success=True, message=f"Channel {name} restarted successfully")
    else:
        logger.warning("Failed to restart channel %s", name)
        return ChannelRestartResponse(success=False, message=f"Failed to restart channel {name}")
