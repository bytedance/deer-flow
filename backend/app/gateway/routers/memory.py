"""
Memory API路由 — 管理全局记忆数据

===================
设计思路说明
===================

**为什么需要Memory API**：
1. 全局记忆是DeerFlow实现个性化对话的关键功能
2. 用户需要通过API查看、编辑、导入导出记忆数据
3. 前端需要展示记忆状态和配置信息

**核心设计模式**：
- RESTful API：GET读取、POST创建、DELETE删除、PATCH更新
- 数据模型分离：Pydantic模型定义API契约，与内部实现解耦
- 异常映射：将底层异常转换为HTTP友好的错误响应

**Memory数据结构**：
- user: 用户上下文（工作、个人、近期关注）
- history: 历史上下文（近期、较早、长期背景）
- facts: 事实性记忆（具体信息点）

**为什么需要facts机制**：
- 结构化的记忆片段更易于管理
- 可以单独编辑每条事实
- 支持置信度评分，过滤低质量信息
- 可追溯来源，便于调试

**API设计原则**：
- 返回完整数据：修改操作返回更新后的完整记忆
- 支持部分更新：PATCH允许只更新部分字段
- 导入导出：支持备份和迁移
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.agents.memory.updater import (
    clear_memory_data,
    create_memory_fact,
    delete_memory_fact,
    get_memory_data,
    import_memory_data,
    reload_memory_data,
    update_memory_fact,
)
from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["memory"])


class ContextSection(BaseModel):
    """
    上下文区块模型

    **为什么这样设计**：
    - summary: 存储摘要文本
    - updatedAt: 追踪最后更新时间
    - 简单的结构便于前端展示
    """

    summary: str = Field(default="", description="摘要内容")
    updatedAt: str = Field(default="", description="最后更新时间戳")


class UserContext(BaseModel):
    """
    用户上下文模型

    **为什么分为三个部分**：
    - workContext: 工作相关背景
    - personalContext: 个人偏好和习惯
    - topOfMind: 当前关注的事项
    - 分区存储便于有针对性地注入
    """

    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    """
    历史上下文模型

    **为什么分为三个时间维度**：
    - recentMonths: 近期活动，影响最大
    - earlierContext: 较早的上下文
    - longTermBackground: 长期背景信息
    - 时间递减的权重模型
    """

    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    """
    记忆事实模型

    **为什么需要confidence字段**：
    - 表示信息的可信度（0-1）
    - 可以过滤低质量信息
    - 某些来源的信息可能更可靠

    **为什么需要source字段**：
    - 追踪信息的来源对话
    - 便于调试和验证
    - 支持按来源过滤
    """

    id: str = Field(..., description="事实的唯一标识符")
    content: str = Field(..., description="事实内容")
    category: str = Field(default="context", description="事实类别")
    confidence: float = Field(default=0.5, description="置信度分数（0-1）")
    createdAt: str = Field(default="", description="创建时间戳")
    source: str = Field(default="unknown", description="来源线程ID")


class MemoryResponse(BaseModel):
    """
    记忆数据响应模型

    **为什么包含version字段**：
    - 支持未来数据结构升级
    - 便于迁移和兼容性检查
    - 前端可以据此调整展示逻辑
    """

    version: str = Field(default="1.0", description="记忆架构版本")
    lastUpdated: str = Field(default="", description="最后更新时间戳")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


def _map_memory_fact_value_error(exc: ValueError) -> HTTPException:
    """
    将updater验证错误转换为稳定的API响应

    **为什么需要这个映射**：
    - 底层可能抛出ValueError，但消息不友好
    - 需要统一错误格式给前端
    - 避免暴露内部实现细节

    **为什么区分confidence和content错误**：
    - confidence: 必须在0-1范围内
    - content: 不能为空
    - 不同的错误需要不同的提示
    """
    if exc.args and exc.args[0] == "confidence":
        detail = "Invalid confidence value; must be between 0 and 1."
    else:
        detail = "Memory fact content cannot be empty."
    return HTTPException(status_code=400, detail=detail)


class FactCreateRequest(BaseModel):
    """
    创建记忆事实的请求模型

    **为什么content是必需的**：
    - 空内容的事实没有意义
    - min_length=1确保至少有一个字符
    """

    content: str = Field(..., min_length=1, description="事实内容")
    category: str = Field(default="context", description="事实类别")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度分数（0-1）")


class FactPatchRequest(BaseModel):
    """
    PATCH请求模型，保留省略字段的现有值

    **为什么使用PATCH而不是PUT**：
    - PATCH允许部分更新
    - PUT需要提供所有字段
    - 用户可能只想更新content，不想改confidence
    - 更灵活的API设计

    **为什么字段都是可选的**：
    - 只更新提供的字段
    - 未提供的字段保持不变
    - 符合PATCH语义
    """

    content: str | None = Field(default=None, min_length=1, description="事实内容")
    category: str | None = Field(default=None, description="事实类别")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="置信度分数（0-1）")


class MemoryConfigResponse(BaseModel):
    """记忆配置响应模型"""

    enabled: bool = Field(..., description="是否启用记忆功能")
    storage_path: str = Field(..., description="记忆存储文件路径")
    debounce_seconds: int = Field(..., description="记忆更新的防抖时间")
    max_facts: int = Field(..., description="可存储的最大事实数量")
    fact_confidence_threshold: float = Field(..., description="事实的最低置信度阈值")
    injection_enabled: bool = Field(..., description="是否启用记忆注入")
    max_injection_tokens: int = Field(..., description="记忆注入的最大token数")


class MemoryStatusResponse(BaseModel):
    """
    记忆状态响应模型

    **为什么同时返回config和data**：
    - 一次请求获取完整状态
    - 减少前端请求次数
    - 便于展示综合信息
    """

    config: MemoryConfigResponse
    data: MemoryResponse


@router.get(
    "/memory",
    response_model=MemoryResponse,
    summary="Get Memory Data",
    description="Retrieve the current global memory data including user context, history, and facts.",
)
async def get_memory() -> MemoryResponse:
    """
    获取当前全局记忆数据

    **为什么需要这个端点**：
    - 前端展示记忆数据
    - 用户查看当前保存的信息
    - 调试时验证记忆内容

    **返回值**：
        包含用户上下文、历史和事实的当前记忆数据

    **示例响应**：
        ```json
        {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00Z",
            "user": {
                "workContext": {"summary": "Working on DeerFlow project", "updatedAt": "..."},
                "personalContext": {"summary": "Prefers concise responses", "updatedAt": "..."},
                "topOfMind": {"summary": "Building memory API", "updatedAt": "..."}
            },
            "history": {
                "recentMonths": {"summary": "Recent development activities", "updatedAt": "..."},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""}
            },
            "facts": [
                {
                    "id": "fact_abc123",
                    "content": "User prefers TypeScript over JavaScript",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2024-01-15T10:30:00Z",
                    "source": "thread_xyz"
                }
            ]
        }
        ```
    """
    memory_data = get_memory_data()
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    summary="Reload Memory Data",
    description="Reload memory data from the storage file, refreshing the in-memory cache.",
)
async def reload_memory() -> MemoryResponse:
    """
    从文件重新加载记忆数据

    **为什么需要这个端点**：
    - 文件被外部修改时强制刷新
    - 调试时验证文件内容
    - 恢复到文件保存的状态

    **返回值**：
        重新加载后的记忆数据
    """
    memory_data = reload_memory_data()
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory",
    response_model=MemoryResponse,
    summary="Clear All Memory Data",
    description="Delete all saved memory data and reset the memory structure to an empty state.",
)
async def clear_memory() -> MemoryResponse:
    """
    清除所有记忆数据

    **为什么需要这个端点**：
    - 用户想要重新开始
    - 测试时清理状态
    - 隐私要求删除所有记忆

    **异常**：
        HTTPException 500: 文件操作失败
    """
    try:
        memory_data = clear_memory_data()
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to clear memory data.") from exc

    return MemoryResponse(**memory_data)


@router.post(
    "/memory/facts",
    response_model=MemoryResponse,
    summary="Create Memory Fact",
    description="Create a single saved memory fact manually.",
)
async def create_memory_fact_endpoint(request: FactCreateRequest) -> MemoryResponse:
    """
    手动创建单个记忆事实

    **为什么需要这个端点**：
    - 用户可以手动添加重要信息
    - 不需要通过对话来积累记忆
    - 便于预填充用户偏好

    **参数说明**：
        request: 包含content、category和confidence的创建请求

    **异常**：
        HTTPException 400: 验证失败（confidence超出范围或content为空）
        HTTPException 500: 文件操作失败

    **返回值**：
        创建后的完整记忆数据
    """
    try:
        memory_data = create_memory_fact(
            content=request.content,
            category=request.category,
            confidence=request.confidence,
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to create memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.delete(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    summary="Delete Memory Fact",
    description="Delete a single saved memory fact by its fact id.",
)
async def delete_memory_fact_endpoint(fact_id: str) -> MemoryResponse:
    """
    通过fact_id删除单个记忆事实

    **为什么需要这个端点**：
    - 删除过时或错误的信息
    - 用户主动管理记忆内容
    - 保持记忆数据的准确性

    **参数说明**：
        fact_id: 要删除的事实的ID

    **异常**：
        HTTPException 404: 事实不存在
        HTTPException 500: 文件操作失败

    **返回值**：
        删除后的完整记忆数据
    """
    try:
        memory_data = delete_memory_fact(fact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.patch(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    summary="Patch Memory Fact",
    description="Partially update a single saved memory fact by its fact id while preserving omitted fields.",
)
async def update_memory_fact_endpoint(fact_id: str, request: FactPatchRequest) -> MemoryResponse:
    """
    部分更新单个记忆事实

    **为什么使用PATCH**：
    - 只更新提供的字段
    - 保留未提供的字段的现有值
    - 更灵活的更新方式

    **参数说明**：
        fact_id: 要更新的事实的ID
        request: 包含要更新字段的请求（所有字段可选）

    **异常**：
        HTTPException 400: 验证失败
        HTTPException 404: 事实不存在
        HTTPException 500: 文件操作失败

    **返回值**：
        更新后的完整记忆数据
    """
    try:
        memory_data = update_memory_fact(
            fact_id=fact_id,
            content=request.content,
            category=request.category,
            confidence=request.confidence,
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to update memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.get(
    "/memory/export",
    response_model=MemoryResponse,
    summary="Export Memory Data",
    description="Export the current global memory data as JSON for backup or transfer.",
)
async def export_memory() -> MemoryResponse:
    """
    导出当前记忆数据

    **为什么需要这个端点**：
    - 备份记忆数据
    - 在不同环境间迁移
    - 手动编辑记忆内容

    **返回值**：
        当前记忆数据的JSON表示
    """
    memory_data = get_memory_data()
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/import",
    response_model=MemoryResponse,
    summary="Import Memory Data",
    description="Import and overwrite the current global memory data from a JSON payload.",
)
async def import_memory(request: MemoryResponse) -> MemoryResponse:
    """
    导入并覆盖当前记忆数据

    **为什么需要这个端点**：
    - 从备份恢复记忆
    - 批量导入预定义的记忆
    - 在不同环境间同步

    **参数说明**：
        request: 要导入的记忆数据

    **异常**：
        HTTPException 500: 文件操作失败

    **返回值**：
        导入后的记忆数据
    """
    try:
        memory_data = import_memory_data(request.model_dump())
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to import memory data.") from exc

    return MemoryResponse(**memory_data)


@router.get(
    "/memory/config",
    response_model=MemoryConfigResponse,
    summary="Get Memory Configuration",
    description="Retrieve the current memory system configuration.",
)
async def get_memory_config_endpoint() -> MemoryConfigResponse:
    """
    获取记忆系统配置

    **为什么需要这个端点**：
    - 前端展示记忆功能状态
    - 用户了解当前配置
    - 调试时验证配置

    **返回值**：
        当前记忆系统配置

    **示例响应**：
        ```json
        {
            "enabled": true,
            "storage_path": ".deer-flow/memory.json",
            "debounce_seconds": 30,
            "max_facts": 100,
            "fact_confidence_threshold": 0.7,
            "injection_enabled": true,
            "max_injection_tokens": 2000
        }
        ```
    """
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        storage_path=config.storage_path,
        debounce_seconds=config.debounce_seconds,
        max_facts=config.max_facts,
        fact_confidence_threshold=config.fact_confidence_threshold,
        injection_enabled=config.injection_enabled,
        max_injection_tokens=config.max_injection_tokens,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status() -> MemoryStatusResponse:
    """
    获取记忆系统状态（配置和数据）

    **为什么需要这个端点**：
    - 一次请求获取完整信息
    - 减少网络往返
    - 便于综合展示

    **返回值**：
        包含配置和数据的记忆状态
    """
    config = get_memory_config()
    memory_data = get_memory_data()

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            storage_path=config.storage_path,
            debounce_seconds=config.debounce_seconds,
            max_facts=config.max_facts,
            fact_confidence_threshold=config.fact_confidence_threshold,
            injection_enabled=config.injection_enabled,
            max_injection_tokens=config.max_injection_tokens,
        ),
        data=MemoryResponse(**memory_data),
    )
