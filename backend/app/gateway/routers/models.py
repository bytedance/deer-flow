"""
Models API路由 — 查询可用AI模型配置

===================
设计思路说明
===================

**为什么需要Models API**：
1. 前端需要展示可用模型列表供用户选择
2. 不同的模型有不同的能力（thinking、reasoning等）
3. 配置中包含敏感信息（API密钥），不能直接暴露

**核心设计原则**：
- 只读接口：模型配置由配置文件管理，API只负责查询
- 安全过滤：自动过滤敏感字段（API密钥等）
- 能力标识：清晰标注模型支持的高级功能

**为什么需要supports_thinking字段**：
- 某些模型（如Claude）支持思考模式
- 前端可以根据此字段显示不同的UI
- 用户可以选择是否启用思考模式

**为什么需要supports_reasoning_effort字段**：
- OpenAI的o1系列模型支持推理努力度调整
- 这是模型能力的元信息
- 前端可以据此提供相应的控制选项

**API设计**：
- GET /models: 列出所有模型
- GET /models/{name}: 获取特定模型详情
- 没有POST/PUT/DELETE: 模型配置由配置文件管理
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["models"])


class ModelResponse(BaseModel):
    """
    模型信息响应模型

    **为什么需要name和model两个字段**：
    - name: 系统内部使用的唯一标识符（如"gpt-4"）
    - model: 实际传递给提供商API的模型标识符（如"gpt-4-0613"）
    - 两者可能不同，name更友好，model更精确

    **为什么display_name是可选的**：
    - 某些模型可能没有专门的显示名称
    - 可以使用name作为回退
    - 保持灵活性

    **为什么description是可选的**：
    - 不是所有模型都需要详细描述
    - 简单的模型名称可能已经足够
    """

    name: str = Field(..., description="模型的唯一标识符")
    model: str = Field(..., description="实际的提供商模型标识符")
    display_name: str | None = Field(None, description="人类可读的名称")
    description: str | None = Field(None, description="模型描述")
    supports_thinking: bool = Field(default=False, description="模型是否支持思考模式")
    supports_reasoning_effort: bool = Field(default=False, description="模型是否支持推理努力度调整")


class ModelsListResponse(BaseModel):
    """
    模型列表响应模型

    **为什么使用包装对象**：
    - 便于未来添加分页信息
    - 保持API的一致性（直接返回数组不便扩展）
    - 可以添加元数据（如总数、更新时间等）
    """

    models: list[ModelResponse]


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models() -> ModelsListResponse:
    """
    列出所有可用模型

    **为什么需要这个端点**：
    - 前端展示模型选择器
    - 用户查看可用模型
    - 验证配置是否正确加载

    **为什么过滤敏感信息**：
    - 配置中包含API密钥等敏感信息
    - 不应该通过API暴露
    - 只返回前端需要的元数据

    **返回值**：
        所有配置模型的元数据列表

    **示例响应**：
        ```json
        {
            "models": [
                {
                    "name": "gpt-4",
                    "display_name": "GPT-4",
                    "description": "OpenAI GPT-4 model",
                    "supports_thinking": false
                },
                {
                    "name": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "description": "Anthropic Claude 3 Opus model",
                    "supports_thinking": true
                }
            ]
        }
        ```
    """
    config = get_app_config()
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
        )
        for model in config.models
    ]
    return ModelsListResponse(models=models)


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(model_name: str) -> ModelResponse:
    """
    通过名称获取特定模型详情

    **为什么需要这个端点**：
    - 获取单个模型的完整信息
    - 验证模型是否存在
    - 查看模型的详细描述

    **参数说明**：
        model_name: 要获取的模型的唯一名称

    **返回值**：
        模型信息（如果找到）

    **异常**：
        HTTPException 404: 模型不存在

    **示例响应**：
        ```json
        {
            "name": "gpt-4",
            "display_name": "GPT-4",
            "description": "OpenAI GPT-4 model",
            "supports_thinking": false
        }
        ```
    """
    config = get_app_config()
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )
