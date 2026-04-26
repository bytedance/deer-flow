"""无状态运行端点 - 无需预先存在线程即可进行流式或等待运行

===================
设计思路说明
===================

**核心职责**：
提供无需预先创建线程的运行接口，支持两种模式：
1. /stream: 通过SSE（Server-Sent Events）实时流式返回运行事件
2. /wait: 阻塞等待运行完成，返回最终状态

**为什么需要这个模块**：
1. **简化API使用**：客户端不需要先创建线程再运行，可以一次性完成
2. **临时线程支持**：对于一次性任务，自动创建临时线程，无需管理生命周期
3. **会话保持**：提供thread_id参数时，可以复用已有线程保持对话历史
4. **兼容LangGraph SDK**：与LangGraph Cloud API保持一致的行为

**设计决策**：
- 自动线程管理：无thread_id时生成UUID，有则复用
- SSE流式响应：使用text/event-stream实现实时推送
- 状态查询优化：从checkpointer读取最终状态，而非内存传递
- 取消容错：捕获CancelledError避免任务取消时崩溃

**架构说明**：
该模块是Gateway层的HTTP入口，实际执行逻辑由：
- start_run: 启动运行任务
- sse_consumer: 消费运行事件并转换为SSE格式
- checkpointer: 持久化存储运行状态

与thread_runs模块的区别：
- thread_runs需要预先存在线程
- runs支持临时线程自动创建
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.gateway.deps import get_checkpointer, get_run_manager, get_stream_bridge
from app.gateway.routers.thread_runs import RunCreateRequest
from app.gateway.services import sse_consumer, start_run
from deerflow.runtime import serialize_channel_values

logger = logging.getLogger(__name__)
# 为什么使用prefix和tags：
# - prefix: 将所有运行相关端点放在/api/runs路径下
# - tags: 用于API文档分组，便于在Swagger UI中浏览
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _resolve_thread_id(body: RunCreateRequest) -> str:
    """解析或生成thread_id

    为什么这样设计：
    - 优先使用请求中的thread_id：支持会话保持
    - 无thread_id时生成UUID：创建临时线程，避免客户端管理
    - 转换为字符串：确保类型一致性，UUID可能是其他类型

    Args:
        body: 运行创建请求，可能包含config.configurable.thread_id

    Returns:
        str: 解析出的thread_id或新生成的UUID
    """
    # 从config.configurable.thread_id获取thread_id
    # 为什么嵌套这么深：与LangGraph SDK的配置结构保持一致
    thread_id = (body.config or {}).get("configurable", {}).get("thread_id")
    if thread_id:
        return str(thread_id)
    # 生成新UUID作为临时线程ID
    # 为什么使用UUID：确保全局唯一性，避免冲突
    return str(uuid.uuid4())


@router.post("/stream")
async def stateless_stream(body: RunCreateRequest, request: Request) -> StreamingResponse:
    """创建运行并通过SSE流式返回事件

    为什么使用SSE（Server-Sent Events）：
    - 单向推送：服务器主动推送事件给客户端
    - 自动重连：浏览器原生支持断线重连
    - 文本格式：易于调试和实现
    - HTTP兼容：无需额外协议，穿透代理友好

    设计考虑：
    - 临时线程vs复用线程：根据thread_id参数自动选择
    - 流式桥接：使用StreamBridge连接运行事件和SSE输出
    - 缓存控制：禁用缓存，确保实时性

    Args:
        body: 运行创建请求，包含输入、配置等
        request: FastAPI请求对象，用于获取依赖项

    Returns:
        StreamingResponse: SSE流式响应
    """
    thread_id = _resolve_thread_id(body)
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    # 启动运行任务，但不等待完成
    # 为什么这样设计：流式响应需要异步消费事件，不能阻塞
    record = await start_run(body, thread_id, request)

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        # 为什么设置这些响应头：
        headers={
            "Cache-Control": "no-cache",  # 禁用缓存，确保实时性
            "Connection": "keep-alive",  # 保持长连接
            "X-Accel-Buffering": "no",  # 禁用Nginx缓冲，确保实时推送
        },
    )


@router.post("/wait", response_model=dict)
async def stateless_wait(body: RunCreateRequest, request: Request) -> dict:
    """创建运行并阻塞等待完成

    为什么需要这个端点：
    - 简化客户端：不需要处理SSE流，直接获取最终结果
    - 同步语义：适合批处理或不需要中间状态的场景
    - 兼容性：与LangGraph SDK的runs.wait行为一致

    设计考虑：
    - 等待任务完成：使用await record.task，确保执行完毕
    - 取消容错：捕获CancelledError，避免任务取消时崩溃
    - 状态读取：从checkpointer读取最终状态，而非内存传递

    为什么从checkpointer读取而非直接返回结果：
    - 状态持久化：checkpointer是状态的权威来源
    - 解耦设计：运行任务可能在其他进程/机器
    - 一致性：确保返回的是最新提交的状态

    Args:
        body: 运行创建请求，包含输入、配置等
        request: FastAPI请求对象，用于获取依赖项

    Returns:
        dict: 最终状态或运行状态信息
    """
    thread_id = _resolve_thread_id(body)
    record = await start_run(body, thread_id, request)

    # 等待任务完成
    # 为什么要捕获CancelledError：
    # - 客户端断开连接时会触发取消
    # - 不应该让异常传播到FastAPI，返回错误响应即可
    if record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass

    # 从checkpointer读取最终状态
    # 为什么这样做：
    # 1. checkpointer存储了运行后的完整状态
    # 2. 支持跨进程/跨机器的运行状态查询
    # 3. 状态可能被其他进程修改，checkpointer是权威来源
    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None:
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint.get("channel_values", {})
            # 序列化通道值：将内部状态转换为客户端可读的格式
            return serialize_channel_values(channel_values)
    except Exception:
        logger.exception("Failed to fetch final state for run %s", record.run_id)

    # 如果无法获取checkpoint，返回运行记录的状态
    # 为什么这样做：提供降级方案，至少返回基本状态信息
    return {"status": record.status.value, "error": record.error}
