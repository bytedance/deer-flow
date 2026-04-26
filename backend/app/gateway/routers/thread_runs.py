"""
运行（Runs）路由端点——创建、流式传输、等待、取消

===================
设计思路说明
===================

**核心职责**：
1. 在RunManager和StreamBridge之上实现LangGraph Platform的runs API
2. 提供兼容LangGraph SDK的SSE流式响应格式
3. 支持多种运行模式：后台运行、流式响应、阻塞等待

**为什么需要这个路由**：
- LangGraph SDK期望特定的API格式
- 前端useStream hook依赖标准的SSE协议
- 统一的运行管理接口

**核心设计模式**：
- 适配器模式：将DeerFlow的RunManager适配为LangGraph API
- 流式响应：使用SSE（Server-Sent Events）推送运行事件
- 异步任务：后台执行，支持取消和等待

**SSE格式对齐**：
SSE格式与LangGraph Platform协议对齐，使得来自``@langchain/langgraph-sdk/react``的
``useStream`` React hook无需修改即可工作。

**为什么SSE格式很重要**：
- 前端SDK依赖特定的事件格式
- Content-Location header包含运行元数据
- useStream hook解析此header获取run_id
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.gateway.deps import get_checkpointer, get_run_manager, get_stream_bridge
from app.gateway.services import sse_consumer, start_run
from deerflow.runtime import RunRecord, serialize_channel_values

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["runs"])


# ---------------------------------------------------------------------------
# Request / response models（请求/响应模型）
# ---------------------------------------------------------------------------


class RunCreateRequest(BaseModel):
    """运行创建请求模型

    ===================
    设计思路说明
    ===================

    **为什么字段这么多**：
    - 兼容LangGraph Platform API的完整功能
    - 支持多种运行模式和策略
    - 提供灵活的配置选项

    **关键字段说明**：
    - assistant_id: 指定使用的代理/助手
    - input: 图输入（如消息列表）
    - stream_mode: 流式传输模式（events、values、messages等）
    - multitask_strategy: 并发处理策略
    - on_disconnect: SSE断开时的行为
    """

    assistant_id: str | None = Field(default=None, description="要使用的代理/助手")
    input: dict[str, Any] | None = Field(default=None, description="图输入（如 {messages: [...]}）")
    command: dict[str, Any] | None = Field(default=None, description="LangGraph命令")
    metadata: dict[str, Any] | None = Field(default=None, description="运行元数据")
    config: dict[str, Any] | None = Field(default=None, description="RunnableConfig覆盖")
    webhook: str | None = Field(default=None, description="完成回调URL")
    checkpoint_id: str | None = Field(default=None, description="从检查点恢复")
    checkpoint: dict[str, Any] | None = Field(default=None, description="完整检查点对象")
    interrupt_before: list[str] | Literal["*"] | None = Field(default=None, description="在指定节点前中断")
    interrupt_after: list[str] | Literal["*"] | None = Field(default=None, description="在指定节点后中断")
    stream_mode: list[str] | str | None = Field(default=None, description="流式传输模式")
    stream_subgraphs: bool = Field(default=False, description="包含子图事件")
    stream_resumable: bool | None = Field(default=None, description="SSE可恢复模式")
    on_disconnect: Literal["cancel", "continue"] = Field(default="cancel", description="SSE断开时的行为")
    on_completion: Literal["delete", "keep"] = Field(default="keep", description="完成后删除临时线程")
    multitask_strategy: Literal["reject", "rollback", "interrupt", "enqueue"] = Field(default="reject", description="并发策略")
    after_seconds: float | None = Field(default=None, description="延迟执行")
    if_not_exists: Literal["reject", "create"] = Field(default="create", description="线程创建策略")
    feedback_keys: list[str] | None = Field(default=None, description="LangSmith反馈键")


class RunResponse(BaseModel):
    """运行响应模型

    **返回内容**：
    - run_id: 运行的唯一标识符
    - thread_id: 所属线程ID
    - status: 运行状态
    - metadata: 运行元数据
    - 时间戳：创建和更新时间
    """

    run_id: str
    thread_id: str
    assistant_id: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    multitask_strategy: str = "reject"
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Helpers（辅助函数）
# ---------------------------------------------------------------------------


def _record_to_response(record: RunRecord) -> RunResponse:
    """将RunRecord转换为RunResponse

    **为什么需要这个转换**：
    - RunRecord是内部数据结构
    - RunResponse是API响应模型
    - 分离内部和外部表示

    **参数说明**：
    - record: 运行记录对象

    **返回值**：
    - RunResponse: API响应模型
    """
    return RunResponse(
        run_id=record.run_id,
        thread_id=record.thread_id,
        assistant_id=record.assistant_id,
        status=record.status.value,
        metadata=record.metadata,
        kwargs=record.kwargs,
        multitask_strategy=record.multitask_strategy,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints（API端点）
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/runs", response_model=RunResponse)
async def create_run(thread_id:_str, body: RunCreateRequest, request: Request) -> RunResponse:
    """创建后台运行（立即返回）

    **为什么立即返回**：
    - 避免阻塞HTTP请求
    - 允许客户端异步获取结果
    - 支持长时间运行的任务

    **使用场景**：
    - 触发不需要实时反馈的任务
    - 批量处理
    - 后台作业
    """
    record = await start_run(body, thread_id, request)
    return _record_to_response(record)


@router.post("/{thread_id}/runs/stream")
async def stream_run(thread_id: str, body: RunCreateRequest, request: Request) -> StreamingResponse:
    """创建运行并通过SSE流式传输事件

    **SSE（Server-Sent Events）设计**：
    - 单向推送：服务器主动推送事件到客户端
    - 自动重连：浏览器断线会自动重连
    - 事件格式：data: JSON\n\n

    **为什么Content-Location很重要**：
    - LangGraph Platform协议要求
    - useStream hook解析此header获取run_id
    - 包含完整的资源URL

    **Headers说明**：
    - Cache-Control: no-cache: 禁用缓存
    - Connection: keep-alive: 保持连接
    - X-Accel-Buffering: no: 禁用nginx缓冲
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = await start_run(body, thread_id, request)

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # LangGraph Platform includes run metadata in this header.
            # The SDK's _get_run_metadata_from_response() parses it.
            "Content-Location": (f"/api/threads/{thread_id}/runs/{record.run_id}/stream?thread_id={thread_id}&run_id={record.run_id}"),
        },
    )


@router.post("/{thread_id}/runs/wait", response_model=dict)
async def wait_run(thread_id: str, body: RunCreateRequest, request: Request) -> dict:
    """创建运行并阻塞等待完成，返回最终状态

    **为什么需要阻塞等待**：
    - 某些场景需要同步获取结果
    - 简化客户端逻辑
    - 适合短时间任务

    **等待流程**：
    1. 启动运行
    2. 等待任务完成
    3. 从checkpointer获取最终状态
    4. 序列化channel values并返回

    **为什么捕获CancelledError**：
    - 任务被取消是正常情况
    - 不应抛出异常
    - 返回部分状态
    """
    record = await start_run(body, thread_id, request)

    if record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass

    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None:
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint.get("channel_values", {})
            return serialize_channel_values(channel_values)
    except Exception:
        logger.exception("Failed to fetch final state for run %s", record.run_id)

    return {"status": record.status.value, "error": record.error}


@router.get("/{thread_id}/runs", response_model=list[RunResponse])
async def list_runs(thread_id: str, request: Request) -> list[RunResponse]:
    """列出线程的所有运行

    **使用场景**：
    - 查看线程历史
    - 调试和监控
    - 审计和追踪
    """
    run_mgr = get_run_manager(request)
    records = await run_mgr.list_by_thread(thread_id)
    return [_record_to_response(r) for r in records]


@router.get("/{thread_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(thread_id: str, run_id: str, request: Request) -> RunResponse:
    """获取特定运行的详细信息

    **验证逻辑**：
    - 检查run是否存在
    - 验证run属于指定thread
    - 返回404如果不匹配
    """
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _record_to_response(record)


@router.post("/{thread_id}/runs/{run_id}/cancel")
async def cancel_run(
    thread_id: str,
    run_id: str,
    request: Request,
    wait: bool = Query(default=False, description="Block until run completes after cancel"),
    action: Literal["interrupt", "rollback"] = Query(default="interrupt", description="Cancel action"),
) -> Response:
    """取消正在运行或待处理的运行

    **取消模式说明**：
    - action=interrupt: 停止执行，保留当前检查点（可恢复）
    - action=rollback: 停止执行，回滚到运行前状态
    - wait=true: 阻塞直到运行完全停止，返回204
    - wait=false: 立即返回202

    **为什么有两种取消模式**：
    - interrupt: 人工干预场景，需要保留状态供调试
    - rollback: 完全撤销，如同没有运行过

    **HTTP状态码**：
    - 202 Accepted: 取消请求已接受，运行正在停止
    - 204 No Content: 运行已完全停止
    - 409 Conflict: 运行状态不允许取消
    """
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    cancelled = await run_mgr.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is not cancellable (status: {record.status.value})",
        )

    if wait and record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass
        return Response(status_code=204)

    return Response(status_code=202)


@router.get("/{thread_id}/runs/{run_id}/join")
async def join_run(thread_id: str, run_id: str, request: Request) -> StreamingResponse:
    """加入现有运行的SSE流

    **使用场景**：
    - 网络断开后重连
    - 多客户端监听同一运行
    - 延迟获取流式结果

    **为什么单独的join端点**：
    - /runs/stream创建新运行
    - /runs/{run_id}/join加入现有运行
    - 区分创建和加入的语义
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.api_route("/{thread_id}/runs/{run_id}/stream", methods=["GET", "POST"], response_model=None)
async def stream_existing_run(
    thread_id: str,
    run_id: str,
    request: Request,
    action: Literal["interrupt", "rollback"] | None = Query(default=None, description="Cancel action"),
    wait: int = Query(default=0, description="Block until cancelled (1) or return immediately (0)"),
):
    """加入现有运行的SSE流（GET），或取消后流式传输（POST）

    **双方法设计**：
    - GET: 简单加入现有流的SSE
    - POST: 取消运行后流式传输剩余事件

    **为什么POST用于取消**：
    - LangGraph SDK的joinStream和useStream停止按钮使用POST
    - 支持优雅关闭：先取消，再流式传输剩余事件
    - 确保客户端观察到干净的关闭

    **优雅关闭流程**：
    1. 接收取消请求（action参数）
    2. 取消运行
    3. 等待运行停止（如果wait=1）
    4. 流式传输剩余缓冲事件
    5. 客户端收到完整的事件序列
    """
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Cancel if an action was requested (stop-button / interrupt flow)
    if action is not None:
        cancelled = await run_mgr.cancel(run_id, action=action)
        if cancelled and wait and record.task is not None:
            try:
                await record.task
            except (asyncio.CancelledError, Exception):
                pass
            return Response(status_code=204)

    bridge = get_stream_bridge(request)
    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
