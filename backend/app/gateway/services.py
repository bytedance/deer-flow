"""
Gateway运行生命周期服务层

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 集中管理运行（Run）创建和生命周期管理的核心业务逻辑
2. 提供SSE（Server-Sent Events）帧格式化和事件消费的统一接口
3. 解耦路由层（HTTP处理）和业务逻辑层，保持路由模块简洁

**核心设计模式**：
- 服务层模式：将业务逻辑从路由控制器中分离
- 异步生成器模式：SSE流式响应的高效实现
- 工厂模式：通过agent_factory创建代理实例

**为什么这样设计**：
- **关注点分离**：路由只处理HTTP协议，服务层处理业务逻辑
- **代码复用**：多个路由（thread_runs、runs）共享同一套服务逻辑
- **可测试性**：服务层函数独立，便于单元测试
- **流式优化**：使用异步生成器提供高效的SSE流式响应

**模块职责**：
1. SSE格式化：将事件转换为标准SSE帧格式
2. 输入规范化：将外部输入格式转换为内部LangChain格式
3. 运行启动：创建RunRecord并启动后台代理任务
4. 标题同步：将代理生成的标题同步到Store
5. SSE消费：从StreamBridge订阅事件并转换为SSE响应
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import HumanMessage

from app.gateway.deps import get_checkpointer, get_run_manager, get_store, get_stream_bridge
from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
)

logger = logging.getLogger(__name__)


# ==================== SSE格式化 ====================
# 为什么需要单独的SSE格式化函数：
# - 确保所有SSE帧格式一致
# - 便于维护和修改SSE格式
# - 符合LangGraph Platform的线缆格式规范


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """
    格式化单个SSE（Server-Sent Events）帧

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将事件数据转换为符合SSE规范的文本帧格式

    **为什么这样设计**：
    - **标准格式**：字段顺序为 event -> data -> id -> 空行
    - **兼容性**：匹配LangGraph Platform的线缆格式
    - **客户端兼容**：与useStream React hook和langgraph-sdk SSE解码器兼容

    **SSE帧格式**：
    ```
    event: <事件类型>
    data: <JSON数据>
    id: <事件ID>  # 可选

    # 空行表示帧结束
    ```

    **参数说明**：
    - event: 事件类型（如"messages"、"values"、"end"等）
    - data: 事件数据，将被JSON序列化
    - event_id: 可选的事件ID，用于客户端去重和排序

    **返回值**：
    符合SSE规范的格式化字符串

    **为什么使用ensure_ascii=False**：
    - 支持中文等多字节字符
    - 减少数据传输量
    - 提高可读性
    """
    # JSON序列化：default=str处理不可序列化对象
    # 为什么用default=str：
    # - 避免序列化失败
    # - 将对象转换为字符串表示
    # - 确保所有数据都能传输
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    # SSE规范：帧结束需要两个换行符
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# ==================== 输入/配置辅助函数 ====================
# 为什么需要这些辅助函数：
# - 统一处理输入格式转换
# - 隐藏底层实现细节
# - 提供一致的API接口


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """
    规范化stream_mode参数为列表

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将不同形式的stream_mode参数统一转换为列表格式

    **为什么这样设计**：
    - **输入灵活性**：接受字符串、列表或None
    - **默认值合理**：默认使用"values"模式，适合大多数场景
    - **类型一致性**：统一返回列表，简化后续处理

    **参数说明**：
    - raw: 原始stream_mode参数，可以是字符串、列表或None

    **返回值**：
    规范化后的stream_mode列表

    **为什么默认是"values"**：
    - values模式提供完整的代理状态
    - 适合状态同步和调试
    - 与useStream hook的默认行为一致
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def normalize_input(raw_input: dict[str, Any] | None) -> dict[str, Any]:
    """
    将LangGraph Platform输入格式转换为LangChain状态字典

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将外部API的输入格式转换为内部LangChain消息格式

    **为什么这样设计**：
    - **格式桥接**：LangGraph Platform和LangChain使用不同的消息格式
    - **类型安全**：将字典消息转换为强类型的LangChain消息对象
    - **扩展性**：预留处理其他消息类型（system、ai、tool）的能力

    **转换规则**：
    - user/human角色 -> HumanMessage
    - 其他角色 -> 暂时作为HumanMessage处理（TODO）

    **参数说明**：
    - raw_input: 原始输入字典，包含messages列表

    **返回值**：
    转换后的LangChain状态字典

    **为什么有TODO**：
    - 当前只处理用户消息
    - 需要支持system、ai、tool等消息类型
    - 需要保留原始消息的元数据和结构
    """
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted = []
        for msg in messages:
            if isinstance(msg, dict):
                # 提取角色：优先使用role，回退到type，默认user
                role = msg.get("role", msg.get("type", "user"))
                content = msg.get("content", "")
                if role in ("user", "human"):
                    converted.append(HumanMessage(content=content))
                else:
                    # TODO: 未来需要正确处理system、ai、tool等消息类型
                    # 目前暂时统一转换为HumanMessage以保持兼容性
                    converted.append(HumanMessage(content=content))
            else:
                # 已经是消息对象，直接使用
                converted.append(msg)
        # 保留原始输入的其他字段，只替换messages
        return {**raw_input, "messages": converted}
    return raw_input


def resolve_agent_factory(assistant_id: str | None):
    """
    从配置中解析代理工厂函数

    ===================
    设计思路说明
    ===================

    **核心职责**：
    根据assistant_id返回对应的代理工厂函数

    **为什么这样设计**：
    - **简化实现**：当前只支持lead_agent
    - **向后兼容**：接受任何assistant_id但统一使用lead_agent
    - **日志记录**：记录非lead_agent的请求以便调试

    **参数说明**：
    - assistant_id: 请求的代理ID

    **返回值**：
    代理工厂函数（当前固定为make_lead_agent）

    **为什么回退到lead_agent**：
    - 当前版本只实现了lead_agent
    - 提供清晰的日志提示
    - 避免请求失败
    """
    from deerflow.agents.lead_agent.agent import make_lead_agent

    if assistant_id and assistant_id != "lead_agent":
        logger.info("assistant_id=%s requested; falling back to lead_agent", assistant_id)
    return make_lead_agent


def build_run_config(thread_id: str, request_config: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """
    为代理构建RunnableConfig字典

    ===================
    设计思路说明
    ===================

    **核心职责**：
    组装LangGraph运行所需的配置对象

    **为什么这样设计**：
    - **分层配置**：基础配置 -> 请求配置 -> 元数据
    - **默认值**：recursion_limit默认为100，防止无限循环
    - **灵活性**：支持任意额外的配置参数

    **配置层次**：
    1. 基础配置：thread_id和recursion_limit
    2. 请求配置：用户提供的额外配置
    3. 元数据：运行时的元数据信息

    **参数说明**：
    - thread_id: 线程ID，必需
    - request_config: 用户请求的配置，可选
    - metadata: 运行元数据，可选

    **返回值**：
    完整的RunnableConfig字典

    **为什么recursion_limit设为100**：
    - 允许足够的递归深度处理复杂任务
    - 防止无限循环导致栈溢出
    - LangGraph推荐的默认值
    """
    # 基础可配置参数：thread_id是必需的
    configurable = {"thread_id": thread_id}
    if request_config:
        # 合并用户提供的configurable参数
        configurable.update(request_config.get("configurable", {}))

    # 基础配置：recursion_limit防止无限循环
    config: dict[str, Any] = {"configurable": configurable, "recursion_limit": 100}

    # 添加其他配置参数（除了configurable）
    if request_config:
        for k, v in request_config.items():
            if k != "configurable":
                config[k] = v

    # 添加元数据
    if metadata:
        config.setdefault("metadata", {}).update(metadata)

    return config


# ==================== 运行生命周期管理 ====================
# 为什么需要这些生命周期管理函数：
# - 确保线程状态一致性
# - 处理运行完成后的清理工作
# - 同步不同存储系统的状态


async def _upsert_thread_in_store(store, thread_id: str, metadata: dict | None) -> None:
    """
    在Store中创建或刷新线程记录

    ===================
    设计思路说明
    ===================

    **核心职责**：
    确保线程在Store中存在，便于通过/threads/search发现

    **为什么这样设计**：
    - **状态可见性**：即使是stateless的/runs/stream创建的线程也能被发现
    - **非致命操作**：失败不影响主流程，只记录警告
    - **延迟导入**：避免与threads路由模块的循环依赖

    **为什么需要这个函数**：
    - /runs/stream是stateless端点，不调用POST /threads
    - 但我们希望这些线程出现在/threads/search结果中
    - 因此需要在start_run时同步到Store

    **参数说明**：
    - store: Store实例
    - thread_id: 线程ID
    - metadata: 线程元数据

    **为什么失败是非致命的**：
    - Store是辅助功能，不影响核心运行
    - 标题等关键信息会在运行后同步
    - 避免因Store问题导致整个请求失败
    """
    # 延迟导入：避免与threads路由模块的循环依赖
    # 为什么会有循环依赖：
    # - threads路由导入本模块
    # - 本模块需要threads的Store辅助函数
    # - 延迟导入打破这个循环
    from app.gateway.routers.threads import _store_upsert

    try:
        await _store_upsert(store, thread_id, metadata=metadata)
    except Exception:
        # 非致命错误：记录警告但不抛出异常
        logger.warning("Failed to upsert thread %s in store (non-fatal)", thread_id)


async def _sync_thread_title_after_run(
    run_task: asyncio.Task,
    thread_id: str,
    checkpointer: Any,
    store: Any,
) -> None:
    """
    等待运行完成后，将生成的标题持久化到Store

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将TitleMiddleware生成的标题从checkpointer同步到Store

    **为什么需要这个函数**：
    - **双存储问题**：标题存储在checkpointer，但Store用于搜索
    - **状态一致性**：确保/threads/search返回正确的标题
    - **异步处理**：不阻塞主响应流

    **执行流程**：
    1. 等待运行任务完成
    2. 从checkpointer读取最终checkpoint
    3. 提取values.title字段
    4. 更新Store记录

    **为什么作为fire-and-forget任务**：
    - 标题同步是辅助功能，不需要等待
    - 不影响主响应的性能
    - 失败也不影响运行结果

    **参数说明**：
    - run_task: 运行任务
    - thread_id: 线程ID
    - checkpointer: 检查点实例
    - store: Store实例

    **为什么使用asyncio.wait而不是await**：
    - wait不会传播任务异常
    - 只关心任务完成，不关心结果
    - 适合fire-and-forget场景
    """
    # 等待后台运行任务完成（任何结果）
    # asyncio.wait不会传播任务异常——它只在任务完成、取消或失败时返回
    await asyncio.wait({run_task})

    # 延迟导入：避免与threads路由模块的循环依赖
    from app.gateway.routers.threads import _store_get, _store_put

    try:
        # 构建checkpoint配置
        ckpt_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        ckpt_tuple = await checkpointer.aget_tuple(ckpt_config)
        if ckpt_tuple is None:
            return

        # 从checkpoint中提取标题
        channel_values = ckpt_tuple.checkpoint.get("channel_values", {})
        title = channel_values.get("title")
        if not title:
            return

        # 获取现有Store记录
        existing = await _store_get(store, thread_id)
        if existing is None:
            return

        # 更新标题和时间戳
        updated = dict(existing)
        updated.setdefault("values", {})["title"] = title
        updated["updated_at"] = time.time()
        await _store_put(store, updated)
        logger.debug("Synced title %r for thread %s", title, thread_id)
    except Exception:
        # 非致命错误：DEBUG级别记录，不传播
        logger.debug("Failed to sync title for thread %s (non-fatal)", thread_id, exc_info=True)


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """
    创建RunRecord并启动后台代理任务

    ===================
    设计思路说明
    ===================

    **核心职责**：
    处理运行创建请求的完整生命周期

    **为什么这样设计**：
    - **集中管理**：所有运行创建逻辑集中在一处
    - **错误处理**：统一处理各种异常情况
    - **状态同步**：确保checkpointer和Store状态一致

    **执行流程**：
    1. 获取依赖（bridge、run_mgr、checkpointer、store）
    2. 解析断开模式（cancel或continue）
    3. 创建或拒绝运行记录
    4. 确保线程在Store中存在
    5. 规范化输入和配置
    6. 启动后台代理任务
    7. 安排标题同步任务

    **参数说明**：
    - body: RunCreateRequest请求体（Any类型避免循环导入）
    - thread_id: 目标线程ID
    - request: FastAPI请求对象

    **返回值**：
    RunRecord实例，包含运行信息和任务引用

    **为什么使用create_or_reject**：
    - 防止并发运行冲突
    - 支持multitask策略
    - 提供明确的错误信息
    """
    # 获取所有依赖的单例对象
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    checkpointer = get_checkpointer(request)
    store = get_store(request)

    # 解析断开连接模式
    # cancel: 客户端断开时取消运行
    # continue: 客户端断开后继续运行
    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    try:
        # 创建运行记录或拒绝（如果线程正忙）
        record = await run_mgr.create_or_reject(
            thread_id,
            body.assistant_id,
            on_disconnect=disconnect,
            metadata=body.metadata or {},
            kwargs={"input": body.input, "config": body.config},
            multitask_strategy=body.multitask_strategy,
        )
    except ConflictError as exc:
        # 409 Conflict: 线程正在处理另一个请求
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedStrategyError as exc:
        # 501 Not Implemented: 不支持的多任务策略
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    # 确保线程在/threads/search中可见
    # 即使是从未通过POST /threads显式创建的线程（如stateless运行）
    store = get_store(request)
    if store is not None:
        await _upsert_thread_in_store(store, thread_id, body.metadata)

    # 准备运行参数
    agent_factory = resolve_agent_factory(body.assistant_id)
    graph_input = normalize_input(body.input)
    config = build_run_config(thread_id, body.config, body.metadata)
    stream_modes = normalize_stream_modes(body.stream_mode)

    # 创建并启动后台代理任务
    task = asyncio.create_task(
        run_agent(
            bridge,
            run_mgr,
            record,
            checkpointer=checkpointer,
            store=store,
            agent_factory=agent_factory,
            graph_input=graph_input,
            config=config,
            stream_modes=stream_modes,
            stream_subgraphs=body.stream_subgraphs,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
        )
    )
    record.task = task

    # 运行完成后，将TitleMiddleware生成的标题从checkpointer同步到Store
    # 这样/threads/search返回正确的标题而不是空的values字典
    if store is not None:
        asyncio.create_task(_sync_thread_title_after_run(task, thread_id, checkpointer, store))

    return record


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """
    从StreamBridge消费事件并生成SSE帧的异步生成器

    ===================
    设计思路说明
    ===================

    **核心职责**：
    订阅StreamBridge事件流，转换为SSE格式响应给客户端

    **为什么使用异步生成器**：
    - **流式响应**：实时推送事件，不等待全部完成
    - **内存高效**：不需要缓存所有事件
    - **背压处理**：自动处理消费速度差异

    **断开连接处理**：
    - cancel模式：客户端断开时取消后台任务
    - continue模式：客户端断开后继续运行，事件被丢弃

    **特殊事件处理**：
    - HEARTBEAT_SENTINEL: 发送心跳注释，保持连接活跃
    - END_SENTINEL: 发送结束事件，关闭流

    **参数说明**：
    - bridge: StreamBridge实例
    - record: RunRecord实例
    - request: FastAPI请求对象
    - run_mgr: RunManager实例

    **为什么在finally块处理断开**：
    - 确保无论正常退出还是异常都会执行
    - 正确处理客户端提前断开的情况
    - 实现on_disconnect语义
    """
    try:
        # 订阅运行的事件流
        async for entry in bridge.subscribe(record.run_id):
            # 检查客户端是否断开连接
            if await request.is_disconnected():
                break

            # 处理心跳哨兵
            # 为什么需要心跳：
            # - 保持SSE连接活跃
            # - 检测客户端是否在线
            # - 防止代理超时
            if entry is HEARTBEAT_SENTINEL:
                yield ": heartbeat\n\n"
                continue

            # 处理结束哨兵
            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            # 普通事件：转换为SSE格式
            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        # 处理断开连接后的清理
        # 只有在运行仍处于pending或running状态时才需要处理
        if record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                # 取消模式：取消后台任务
                await run_mgr.cancel(record.run_id)
