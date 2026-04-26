"""Assistants兼容性API端点

===================
设计思路说明
===================

**核心职责**：
提供与LangGraph Platform兼容的assistants API接口，支持前端React组件（如useStream hook）
的初始化需求。该模块作为适配层，将DeerFlow的代理配置映射为LangGraph风格的assistants API。

**为什么需要这个模块**：
1. **前端兼容性**：LangGraph SDK的前端组件（如useStream）在初始化时会调用assistants.search()
   和assistants.get()来获取可用的助手列表
2. **统一入口**：提供标准的REST API来查询系统中可用的代理，包括默认的lead_agent和用户自定义代理
3. **最小化实现**：这是一个精简的stub实现，只满足SDK验证需求，不需要完整的图内省功能

**设计决策**：
- 使用lead_agent作为统一的graph_id：所有自定义代理都使用同一个底层图，通过agent_name上下文区分
- 支持从config.yaml加载自定义代理：用户定义的代理自动出现在assistants列表中
- 返回最小化的图结构：避免复杂的图遍历，只返回基本的nodes和edges列表
- 空schemas返回：Gateway模式下不支持完整的输入/输出/状态schema内省

**架构说明**：
该模块是Gateway层的一部分，不涉及实际的代理执行逻辑，只提供元数据查询功能。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
# 为什么使用prefix和tags：
# - prefix: 将所有assistants相关端点放在/api/assistants路径下，符合RESTful规范
# - tags: 用于API文档分组，便于在Swagger UI中浏览
router = APIRouter(prefix="/api/assistants", tags=["assistants-compat"])


class AssistantResponse(BaseModel):
    """Assistant响应模型

    为什么这样设计：
    - 兼容LangGraph Platform的assistant对象结构
    - 使用ISO格式字符串存储时间，便于JSON序列化
    - config和metadata使用dict类型，支持灵活的扩展
    """
    assistant_id: str  # 助手唯一标识符
    graph_id: str  # 底层LangGraph图的ID
    name: str  # 助手显示名称
    config: dict[str, Any] = Field(default_factory=dict)  # 运行时配置
    metadata: dict[str, Any] = Field(default_factory=dict)  # 元数据（如创建者信息）
    description: str | None = None  # 助手描述
    created_at: str = ""  # 创建时间（ISO格式）
    updated_at: str = ""  # 更新时间（ISO格式）
    version: int = 1  # 版本号


class AssistantSearchRequest(BaseModel):
    """Assistant搜索请求模型

    为什么支持这些过滤条件：
    - graph_id: 允许按特定图过滤助手
    - name: 支持模糊匹配，便于用户查找
    - metadata: 预留扩展字段，支持未来的高级过滤
    - limit/offset: 实现分页，避免一次返回过多数据
    """
    graph_id: str | None = None  # 按图ID过滤
    name: str | None = None  # 按名称模糊匹配
    metadata: dict[str, Any] | None = None  # 按元数据过滤（预留）
    limit: int = 10  # 返回数量限制
    offset: int = 0  # 起始偏移量


def _get_default_assistant() -> AssistantResponse:
    """返回默认的lead_agent助手

    为什么需要默认助手：
    - 确保系统至少有一个可用的助手
    - lead_agent是DeerFlow的核心代理，处理所有通用任务
    - 使用当前时间作为创建/更新时间，因为这是系统内置的

    Returns:
        AssistantResponse: 默认lead_agent的配置信息
    """
    now = datetime.now(UTC).isoformat()
    return AssistantResponse(
        assistant_id="lead_agent",
        graph_id="lead_agent",
        name="lead_agent",
        config={},
        metadata={"created_by": "system"},
        description="DeerFlow lead agent",
        created_at=now,
        updated_at=now,
        version=1,
    )


def _list_assistants() -> list[AssistantResponse]:
    """列出所有可用的助手

    设计思路：
    1. 始终包含默认的lead_agent
    2. 动态加载用户自定义代理（从config.yaml的agents目录）
    3. 所有自定义代理共享同一个graph_id（lead_agent），通过agent_name上下文区分

    为什么这样设计：
    - 统一架构：所有代理使用同一个图简化了部署和维护
    - 灵活扩展：用户可以添加自定义代理而不需要修改代码
    - 容错处理：加载失败时只返回默认代理，不影响核心功能

    Returns:
        list[AssistantResponse]: 所有可用助手的列表
    """
    assistants = [_get_default_assistant()]

    # 同时包含config.yaml中定义的自定义代理
    # 为什么使用try-except：
    # - 配置文件可能不存在或格式错误
    # - 不应该因为配置问题导致整个API失败
    # - 使用debug级别记录，避免日志过多
    try:
        from deerflow.config.agents_config import list_custom_agents

        for agent_cfg in list_custom_agents():
            now = datetime.now(UTC).isoformat()
            assistants.append(
                AssistantResponse(
                    assistant_id=agent_cfg.name,
                    graph_id="lead_agent",  # 所有代理使用同一个图
                    name=agent_cfg.name,
                    config={},
                    metadata={"created_by": "user"},
                    description=agent_cfg.description or "",
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
    except Exception:
        logger.debug("Could not load custom agents for assistants list")

    return assistants


@router.post("/search", response_model=list[AssistantResponse])
async def search_assistants(body: AssistantSearchRequest | None = None) -> list[AssistantResponse]:
    """搜索助手

    为什么使用POST而非GET：
    - LangGraph SDK的标准API使用POST进行搜索
    - 支持复杂的过滤条件（在请求体中传递）
    - 便于扩展未来可能添加的复杂查询参数

    Args:
        body: 搜索条件，为None时返回所有助手

    Returns:
        list[AssistantResponse]: 匹配的助手列表，支持分页
    """
    assistants = _list_assistants()

    # 应用过滤条件
    if body and body.graph_id:
        assistants = [a for a in assistants if a.graph_id == body.graph_id]
    if body and body.name:
        # 使用不区分大小写的模糊匹配
        assistants = [a for a in assistants if body.name.lower() in a.name.lower()]

    # 应用分页
    offset = body.offset if body else 0
    limit = body.limit if body else 10
    return assistants[offset : offset + limit]


@router.get("/{assistant_id}", response_model=AssistantResponse)
async def get_assistant_compat(assistant_id: str) -> AssistantResponse:
    """根据ID获取助手详情

    为什么需要这个端点：
    - SDK在初始化特定助手时会调用此接口
    - 用于验证助手是否存在并获取其配置

    Args:
        assistant_id: 助手唯一标识符

    Returns:
        AssistantResponse: 助手的详细信息

    Raises:
        HTTPException: 当助手不存在时返回404
    """
    for a in _list_assistants():
        if a.assistant_id == assistant_id:
            return a
    raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")


@router.get("/{assistant_id}/graph")
async def get_assistant_graph(assistant_id: str) -> dict:
    """获取助手的图结构

    为什么返回最小化的图描述：
    - Gateway模式下不需要完整的图遍历功能
    - 只满足SDK的验证需求
    - 避免加载和解析langgraph.json的开销

    Args:
        assistant_id: 助手唯一标识符

    Returns:
        dict: 包含graph_id、nodes和edges的图结构描述

    Raises:
        HTTPException: 当助手不存在时返回404
    """
    # 验证助手是否存在
    found = any(a.assistant_id == assistant_id for a in _list_assistants())
    if not found:
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

    return {
        "graph_id": "lead_agent",
        "nodes": [],  # 空节点列表：Gateway不需要内省图结构
        "edges": [],  # 空边列表：同上
    }


@router.get("/{assistant_id}/schemas")
async def get_assistant_schemas(assistant_id: str) -> dict:
    """获取助手的输入/输出/状态JSON Schema

    为什么返回空schemas：
    - Gateway模式下不支持完整的schema内省
    - Schema定义在LangGraph Server端，Gateway不维护
    - 空schema足以通过SDK的验证检查

    Args:
        assistant_id: 助手唯一标识符

    Returns:
        dict: 包含各种schema的字典

    Raises:
        HTTPException: 当助手不存在时返回404
    """
    # 验证助手是否存在
    found = any(a.assistant_id == assistant_id for a in _list_assistants())
    if not found:
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

    return {
        "graph_id": "lead_agent",
        "input_schema": {},  # 输入schema：由LangGraph Server处理
        "output_schema": {},  # 输出schema：同上
        "state_schema": {},  # 状态schema：同上
        "config_schema": {},  # 配置schema：同上
    }
