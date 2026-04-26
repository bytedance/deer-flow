"""
线程（Threads）路由端点 — CRUD、状态和历史

===================
设计思路说明
===================

**核心职责**：
1. 管理线程的生命周期（创建、读取、更新、删除）
2. 提供线程状态查询接口
3. 获取线程的checkpoint历史

**为什么需要这个路由**：
- LangGraph Platform期望标准的threads API
- 前端需要线程列表和状态信息
- 支持人工介入（human-in-the-loop）的状态更新

**核心设计模式**：
- 双存储架构：Store（快速查询）+ Checkpointer（状态持久化）
- 懒迁移：自动将checkpointer中的线程同步到Store
- 状态派生：从checkpoint元数据派生线程状态

**为什么使用双存储架构**：
- Store提供快速的元数据查询
- Checkpointer提供完整的状态快照
- 两者结合实现最佳性能

**序列化处理**：
通过:func:`deerflow.runtime.serialization.serialize_channel_values`确保LangChain消息对象
被转换为JSON安全的字典，匹配LangGraph Platform协议格式，这是``useStream`` React hook期望的格式。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_checkpointer, get_store
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime import serialize_channel_values

# ---------------------------------------------------------------------------
# Store namespace
# ---------------------------------------------------------------------------

THREADS_NS: tuple[str, ...] = ("threads",)
"""Store用于线程元数据记录的命名空间"""

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ThreadDeleteResponse(BaseModel):
    """线程清理响应模型"""

    success: bool
    message: str


class ThreadResponse(BaseModel):
    """单个线程的响应模型"""

    thread_id: str = Field(description="唯一线程标识符")
    status: str = Field(default="idle", description="线程状态：idle, busy, interrupted, error")
    created_at: str = Field(default="", description="ISO时间戳")
    updated_at: str = Field(default="", description="ISO时间戳")
    metadata: dict[str, Any] = Field(default_factory=dict, description="线程元数据")
    values: dict[str, Any] = Field(default_factory=dict, description="当前状态channel值")
    interrupts: dict[str, Any] = Field(default_factory=dict, description="待处理的中断")


class ThreadCreateRequest(BaseModel):
    """创建线程的请求体"""

    thread_id: str | None = Field(default=None, description="可选的线程ID（省略时自动生成）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="初始元数据")


class ThreadSearchRequest(BaseModel):
    """搜索线程的请求体"""

    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据过滤器（精确匹配）")
    limit: int = Field(default=100, ge=1, le=1000, description="最大结果数")
    offset: int = Field(default=0, ge=0, description="分页偏移量")
    status: str | None = Field(default=None, description="按线程状态过滤")


class ThreadStateResponse(BaseModel):
    """线程状态响应模型"""

    values: dict[str, Any] = Field(default_factory=dict, description="当前channel值")
    next: list[str] = Field(default_factory=list, description="下一步要执行的任务")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Checkpoint元数据")
    checkpoint: dict[str, Any] = Field(default_factory=dict, description="Checkpoint信息")
    checkpoint_id: str | None = Field(default=None, description="当前checkpoint ID")
    parent_checkpoint_id: str | None = Field(default=None, description="父checkpoint ID")
    created_at: str | None = Field(default=None, description="Checkpoint时间戳")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="中断的任务详情")


class ThreadPatchRequest(BaseModel):
    """补丁线程元数据的请求体"""

    metadata: dict[str, Any] = Field(default_factory=dict, description="要合并的元数据")


class ThreadStateUpdateRequest(BaseModel):
    """更新线程状态的请求体（人工介入恢复）"""

    values: dict[str, Any] | None = Field(default=None, description="要合并的channel值")
    checkpoint_id: str | None = Field(default=None, description="分支来源的checkpoint")
    checkpoint: dict[str, Any] | None = Field(default=None, description="完整checkpoint对象")
    as_node: str | None = Field(default=None, description="更新的节点标识")


class HistoryEntry(BaseModel):
    """单个checkpoint历史条目"""

    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    next: list[str] = Field(default_factory=list)


class ThreadHistoryRequest(BaseModel):
    """checkpoint历史请求体"""

    limit: int = Field(default=10, ge=1, le=100, description="最大条目数")
    before: str | None = Field(default=None, description="分页游标")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_thread_data(thread_id: str, paths: Paths | None = None) -> ThreadDeleteResponse:
    """
    删除线程的本地持久化文件系统数据

    **为什么需要这个函数**：
    - 线程的本地文件系统数据需要被清理
    - 可能从多个地方调用（API、测试等）
    - 统一的错误处理

    **参数说明**：
        thread_id: 要删除的线程ID
        paths: 可选的路径管理器，用于测试

    **异常**：
        HTTPException 422: 无效的thread_id
        HTTPException 500: 删除失败
    """
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        # 不严重 —— 线程数据可能不在磁盘上
        logger.debug("No local thread data to delete for %s", thread_id)
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", thread_id)
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")


async def _store_get(store, thread_id: str) -> dict | None:
    """
    从Store获取线程记录；如果不存在则返回None

    **为什么需要异步**：
    - Store可能是远程服务
    - 统一的异步接口
    """
    item = await store.aget(THREADS_NS, thread_id)
    return item.value if item is not None else None


async def _store_put(store, record: dict) -> None:
    """
    将线程记录写入Store

    **为什么需要这个函数**：
    - 统一的写入逻辑
    - 便于测试和模拟
    """
    await store.aput(THREADS_NS, record["thread_id"], record)


async def _store_upsert(store, thread_id: str, *, metadata: dict | None = None, values: dict | None = None) -> None:
    """
    在Store中创建或刷新线程记录

    **为什么这样设计**：
    - 创建时记录以status="idle"写入
    - 更新时只修改updated_at（和可选的metadata/values）
    - 保留现有字段，避免覆盖

    **values的作用**：
    - 携带agent状态快照给前端
    - 当前只包含{"title": "..."}
    - 便于线程列表显示标题

    **参数说明**：
        store: Store实例
        thread_id: 线程ID
        metadata: 可选的元数据合并
        values: 可选的值合并
    """
    now = time.time()
    existing = await _store_get(store, thread_id)
    if existing is None:
        await _store_put(
            store,
            {
                "thread_id": thread_id,
                "status": "idle",
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or {},
                "values": values or {},
            },
        )
    else:
        val = dict(existing)
        val["updated_at"] = now
        if metadata:
            val.setdefault("metadata", {}).update(metadata)
        if values:
            val.setdefault("values", {}).update(values)
        await _store_put(store, val)


def _derive_thread_status(checkpoint_tuple) -> str:
    """
    从checkpoint元数据派生线程状态

    **为什么需要派生状态**：
    - Store中的状态可能过时
    - Checkpoint包含最新的执行信息
    - 准确的状态对前端很重要

    **状态规则**：
    - idle: 没有checkpoint或没有pending_writes
    - error: pending_writes中包含__error__
    - interrupted: 有pending的next tasks

    **参数说明**：
        checkpoint_tuple: Checkpoint元组对象

    **返回值**：
        线程状态字符串
    """
    if checkpoint_tuple is None:
        return "idle"
    pending_writes = getattr(checkpoint_tuple, "pending_writes", None) or []

    # 检查pending writes中的错误
    for pw in pending_writes:
        if len(pw) >= 2 and pw[1] == "__error__":
            return "error"

    # 检查pending的next tasks（表示中断）
    tasks = getattr(checkpoint_tuple, "tasks", None)
    if tasks:
        return "interrupted"

    return "idle"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    """
    删除线程的本地持久化文件系统数据

    **清理步骤**：
    1. 清理DeerFlow管理的线程目录
    2. 删除checkpoint数据
    3. 从Store中移除线程记录

    **为什么是best-effort删除**：
    - 部分数据可能不存在
    - 不应该因为部分失败而阻止整体操作
    - 记录日志但不抛异常

    **参数说明**：
        thread_id: 要删除的线程ID
    """
    # 清理本地文件系统
    response = _delete_thread_data(thread_id)

    # 从Store中移除（best-effort）
    store = get_store(request)
    if store is not None:
        try:
            await store.adelete(THREADS_NS, thread_id)
        except Exception:
            logger.debug("Could not delete store record for thread %s (not critical)", thread_id)

    # 移除checkpoints（best-effort）
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        try:
            if hasattr(checkpointer, "adelete_thread"):
                await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug("Could not delete checkpoints for thread %s (not critical)", thread_id)

    return response


@router.post("", response_model=ThreadResponse)
async def create_thread(body: ThreadCreateRequest, request: Request) -> ThreadResponse:
    """
    创建新线程

    **幂等性设计**：
    - 如果thread_id已存在，返回现有记录
    - 避免重复创建
    - 便于客户端重试

    **初始化流程**：
    1. 检查Store中是否已存在
    2. 写入Store记录
    3. 写入空的checkpoint（使状态端点立即可用）

    **为什么需要空checkpoint**：
    - 状态端点需要checkpoint才能工作
    - 提供一致的初始状态
    - 避免特殊处理

    **参数说明**：
        body: 包含可选thread_id和metadata的创建请求

    **返回值**：
        创建的或已存在的线程记录
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)
    thread_id = body.thread_id or str(uuid.uuid4())
    now = time.time()

    # 幂等性：当已存在时从Store返回现有记录
    if store is not None:
        existing_record = await _store_get(store, thread_id)
        if existing_record is not None:
            return ThreadResponse(
                thread_id=thread_id,
                status=existing_record.get("status", "idle"),
                created_at=str(existing_record.get("created_at", "")),
                updated_at=str(existing_record.get("updated_at", "")),
                metadata=existing_record.get("metadata", {}),
            )

    # 将线程记录写入Store
    if store is not None:
        try:
            await _store_put(
                store,
                {
                    "thread_id": thread_id,
                    "status": "idle",
                    "created_at": now,
                    "updated_at": now,
                    "metadata": body.metadata,
                },
            )
        except Exception:
            logger.exception("Failed to write thread %s to store", thread_id)
            raise HTTPException(status_code=500, detail="Failed to create thread")

    # 写入空checkpoint使状态端点立即可用
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        from langgraph.checkpoint.base import empty_checkpoint

        ckpt_metadata = {
            "step": -1,
            "source": "input",
            "writes": None,
            "parents": {},
            **body.metadata,
            "created_at": now,
        }
        await checkpointer.aput(config, empty_checkpoint(), ckpt_metadata, {})
    except Exception:
        logger.exception("Failed to create checkpoint for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to create thread")

    logger.info("Thread created: %s", thread_id)
    return ThreadResponse(
        thread_id=thread_id,
        status="idle",
        created_at=str(now),
        updated_at=str(now),
        metadata=body.metadata,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(body: ThreadSearchRequest, request: Request) -> list[ThreadResponse]:
    """
    搜索和列出线程

    **两阶段方法**：

    **阶段1 — Store（快速路径，O(threads)）**：
    - 返回通过此Gateway创建或运行的线程
    - Store记录是微小的元数据字典，一次性获取很便宜

    **阶段2 — Checkpointer补充（懒迁移）**：
    - 发现已由LangGraph Server直接创建（因此不在Store中）的线程
    - 通过迭代共享checkpointer发现
    - 任何新发现的线程立即写入Store，使下次搜索跳过阶段2
    - Store随时间收敛到完整索引，无需一次性迁移作业

    **为什么需要懒迁移**：
    - 避免大规模迁移作业
    - 自动填补Store和Checkpointer的差异
    - 对用户透明的数据同步

    **参数说明**：
        body: 包含metadata过滤、limit、offset、status过滤的搜索请求

    **返回值**：
        匹配条件的线程列表，按updated_at降序排列
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)

    # -----------------------------------------------------------------------
    # 阶段1: Store
    # -----------------------------------------------------------------------
    merged: dict[str, ThreadResponse] = {}

    if store is not None:
        try:
            items = await store.asearch(THREADS_NS, limit=10_000)
        except Exception:
            logger.warning("Store search failed — falling back to checkpointer only", exc_info=True)
            items = []

        for item in items:
            val = item.value
            merged[val["thread_id"]] = ThreadResponse(
                thread_id=val["thread_id"],
                status=val.get("status", "idle"),
                created_at=str(val.get("created_at", "")),
                updated_at=str(val.get("updated_at", "")),
                metadata=val.get("metadata", {}),
                values=val.get("values", {}),
            )

    # -----------------------------------------------------------------------
    # 阶段2: Checkpointer补充
    # 发现尚未在Store中的线程（例如由LangGraph Server创建）
    # 并懒迁移它们以便未来的搜索跳过此阶段
    # -----------------------------------------------------------------------
    try:
        async for checkpoint_tuple in checkpointer.alist(None):
            cfg = getattr(checkpoint_tuple, "config", {})
            thread_id = cfg.get("configurable", {}).get("thread_id")
            if not thread_id or thread_id in merged:
                continue

            # 跳过子图checkpoint（checkpoint_ns非空）
            if cfg.get("configurable", {}).get("checkpoint_ns", ""):
                continue

            ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
            # 从用户可见的元数据字典中剥离LangGraph内部键
            user_meta = {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")}

            # 从checkpoint的channel_values中提取状态值（title）
            checkpoint_data = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint_data.get("channel_values", {})
            ckpt_values = {}
            if title := channel_values.get("title"):
                ckpt_values["title"] = title

            thread_resp = ThreadResponse(
                thread_id=thread_id,
                status=_derive_thread_status(checkpoint_tuple),
                created_at=str(ckpt_meta.get("created_at", "")),
                updated_at=str(ckpt_meta.get("updated_at", ckpt_meta.get("created_at", ""))),
                metadata=user_meta,
                values=ckpt_values,
            )
            merged[thread_id] = thread_resp

            # 懒迁移 — 写入Store以便下次搜索在那里找到它
            if store is not None:
                try:
                    await _store_upsert(store, thread_id, metadata=user_meta, values=ckpt_values or None)
                except Exception:
                    logger.debug("Failed to migrate thread %s to store (non-fatal)", thread_id)
    except Exception:
        logger.exception("Checkpointer scan failed during thread search")
        # 不抛出 —— 返回从Store + 部分扫描收集的内容

    # -----------------------------------------------------------------------
    # 阶段3: 过滤 → 排序 → 分页
    # -----------------------------------------------------------------------
    results = list(merged.values())

    if body.metadata:
        results = [r for r in results if all(r.metadata.get(k) == v for k, v in body.metadata.items())]

    if body.status:
        results = [r for r in results if r.status == body.status]

    results.sort(key=lambda r: r.updated_at, reverse=True)
    return results[body.offset : body.offset + body.limit]


@router.patch("/{thread_id}", response_model=ThreadResponse)
async def patch_thread(thread_id: str, body: ThreadPatchRequest, request: Request) -> ThreadResponse:
    """
    将元数据合并到线程记录

    **为什么使用PATCH而不是PUT**：
    - 只更新提供的字段
    - 保留未提供的字段
    - 更灵活的更新方式

    **参数说明**：
        thread_id: 线程ID
        body: 包含要合并的元数据

    **异常**：
        HTTPException 503: Store不可用
        HTTPException 404: 线程不存在
        HTTPException 500: 更新失败
    """
    store = get_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")

    record = await _store_get(store, thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    now = time.time()
    updated = dict(record)
    updated.setdefault("metadata", {}).update(body.metadata)
    updated["updated_at"] = now

    try:
        await _store_put(store, updated)
    except Exception:
        logger.exception("Failed to patch thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to update thread")

    return ThreadResponse(
        thread_id=thread_id,
        status=updated.get("status", "idle"),
        created_at=str(updated.get("created_at", "")),
        updated_at=str(now),
        metadata=updated.get("metadata", {}),
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(thread_id: str, request: Request) -> ThreadResponse:
    """
    获取线程信息

    **数据源组合**：
    - 从Store读取元数据
    - 从checkpointer派生准确的执行状态
    - 对早于Store采用的线程回退到仅checkpointer（向后兼容）

    **为什么需要组合数据源**：
    - Store提供快速的元数据访问
    - Checkpointer提供最新的状态
    - 两者结合实现最佳性能和准确性

    **参数说明**：
        thread_id: 线程ID

    **异常**：
        HTTPException 404: 线程不存在
        HTTPException 500: 获取失败

    **返回值**：
        包含元数据、状态和序列化channel值的线程信息
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)

    record: dict | None = None
    if store is not None:
        record = await _store_get(store, thread_id)

    # 从checkpointer派生准确状态
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get checkpoint for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread")

    if record is None and checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # 如果线程在checkpointer中存在但不在store中（例如遗留数据），
    # 从checkpoint元数据合成最小的store记录
    if record is None and checkpoint_tuple is not None:
        ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
        record = {
            "thread_id": thread_id,
            "status": "idle",
            "created_at": ckpt_meta.get("created_at", ""),
            "updated_at": ckpt_meta.get("updated_at", ckpt_meta.get("created_at", "")),
            "metadata": {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")},
        }

    status = _derive_thread_status(checkpoint_tuple) if checkpoint_tuple is not None else record.get("status", "idle")  # type: ignore[union-attr]
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {} if checkpoint_tuple is not None else {}
    channel_values = checkpoint.get("channel_values", {})

    return ThreadResponse(
        thread_id=thread_id,
        status=status,
        created_at=str(record.get("created_at", "")),  # type: ignore[union-attr]
        updated_at=str(record.get("updated_at", "")),  # type: ignore[union-attr]
        metadata=record.get("metadata", {}),  # type: ignore[union-attr]
        values=serialize_channel_values(channel_values),
    )


@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    """
    获取线程的最新状态快照

    **为什么需要序列化**：
    - Channel values包含LangChain消息对象
    - 需要转换为JSON安全的字典
    - 匹配LangGraph Platform协议格式

    **参数说明**：
        thread_id: 线程ID

    **异常**：
        HTTPException 404: 线程不存在
        HTTPException 500: 获取失败

    **返回值**：
        包含序列化channel值、next任务、元数据等的线程状态
    """
    checkpointer = get_checkpointer(request)

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
    checkpoint_id = None
    ckpt_config = getattr(checkpoint_tuple, "config", {})
    if ckpt_config:
        checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id")

    channel_values = checkpoint.get("channel_values", {})

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    parent_checkpoint_id = None
    if parent_config:
        parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")

    tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
    next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]
    tasks = [{"id": getattr(t, "id", ""), "name": getattr(t, "name", "")} for t in tasks_raw]

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=next_tasks,
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": str(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
        tasks=tasks,
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
async def update_thread_state(thread_id: str, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
    """
    更新线程状态（例如用于人工介入恢复或标题重命名）

    **更新流程**：
    1. 读取最新的checkpoint
    2. 合并body.values到channel values
    3. 写入新的checkpoint
    4. 将title更改同步到Store

    **为什么需要同步title到Store**：
    - /threads/search需要反映更改
    - Store是线程列表的主要数据源
    - 立即可见，无需等待下次checkpointer扫描

    **为什么使用可变副本**：
    - 避免意外修改缓存对象
    - 确保原始数据不被污染
    - 安全的并发访问

    **参数说明**：
        thread_id: 线程ID
        body: 包含values、checkpoint_id、checkpoint、as_node的更新请求

    **异常**：
        HTTPException 404: 线程不存在
        HTTPException 500: 更新失败

    **返回值**：
        更新后的线程状态
    """
    checkpointer = get_checkpointer(request)
    store = get_store(request)

    # aput需要config中的checkpoint_ns — 默认为""
    # （根图命名空间）。checkpoint_id是可选的；省略它获取线程的最新checkpoint
    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if body.checkpoint_id:
        read_config["configurable"]["checkpoint_id"] = body.checkpoint_id

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.exception("Failed to get state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # 使用可变副本，避免意外修改缓存对象
    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    if body.values:
        channel_values.update(body.values)

    checkpoint["channel_values"] = channel_values
    metadata["updated_at"] = time.time()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    # aput需要config中的checkpoint_ns — 使用与读取相同的配置
    # （总是包含checkpoint_ns=""）。不要包含checkpoint_id，以便aput为新快照
    # 生成新的checkpoint ID
    write_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        new_config = await checkpointer.aput(write_config, checkpoint, metadata, {})
    except Exception:
        logger.exception("Failed to update state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    new_checkpoint_id: str | None = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    # 将title更改同步到Store，使/threads/search立即反映它们
    if store is not None and body.values and "title" in body.values:
        try:
            await _store_upsert(store, thread_id, values={"title": body.values["title"]})
        except Exception:
            logger.debug("Failed to sync title to store for thread %s (non-fatal)", thread_id)

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
    )


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
async def get_thread_history(thread_id: str, body: ThreadHistoryRequest, request: Request) -> list[HistoryEntry]:
    """
    获取线程的checkpoint历史

    **为什么需要历史功能**：
    - 查看线程的执行轨迹
    - 调试和分析
    - 支持回滚到之前的checkpoint

    **参数说明**：
        thread_id: 线程ID
        body: 包含limit和before游标的请求

    **异常**：
        HTTPException 500: 获取失败

    **返回值**：
        checkpoint历史条目列表
    """
    checkpointer = get_checkpointer(request)

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if body.before:
        config["configurable"]["checkpoint_id"] = body.before

    entries: list[HistoryEntry] = []
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=body.limit):
            ckpt_config = getattr(checkpoint_tuple, "config", {})
            parent_config = getattr(checkpoint_tuple, "parent_config", None)
            metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}

            checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = None
            if parent_config:
                parent_id = parent_config.get("configurable", {}).get("checkpoint_id")

            channel_values = checkpoint.get("channel_values", {})

            # 派生next tasks
            tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
            next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=metadata,
                    values=serialize_channel_values(channel_values),
                    created_at=str(metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
