"""
LLM模型配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义单个LLM模型的配置
2. 支持多种模型提供者（OpenAI、Claude等）
3. 配置模型特性（思考、视觉等）

**为什么需要统一模型配置**：
- 支持多个LLM提供者
- 灵活切换不同模型
- A/B测试新模型
- 成本优化（不同场景用不同模型）

**模型提供者（use字段）**：
- langchain_openai.ChatOpenAI: OpenAI GPT系列
- langchain_anthropic.ChatAnthropic: Anthropic Claude系列
- 自定义提供者路径

**extra="allow"的作用**：
- 不同提供者需要不同参数
- 避免配置被未知字段阻止
- 支持新功能而无需修改schema
"""

from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    """单个模型配置

    **name字段**：
    - 模型的唯一标识符
    - 用于在配置中引用该模型
    - 必填字段

    **display_name字段**：
    - UI显示的模型名称
    - 用户友好的名称
    - 可选，默认使用name

    **description字段**：
    - 模型功能描述
    - 帮助用户选择合适的模型
    - 可选

    **use字段**：
    - 模型提供者的类路径
    - 支持任何LangChain兼容的提供者
    - 动态导入机制

    **model字段**：
    - 特定模型的标识符
    - 如"gpt-4"、"claude-3-sonnet"
    - 传递给提供者的model参数

    **use_responses_api字段**：
    - 是否通过/v1/responses API路由OpenAI调用
    - 某些功能需要特殊API
    - 可选

    **output_version字段**：
    - 结构化输出版本
    - 如"responses/v1"
    - 控制响应格式

    **supports_thinking字段**：
    - 模型是否支持思考模式
    - 如Claude的扩展思考
    - 启用后会调用推理中间件

    **supports_reasoning_effort字段**：
    - 模型是否支持推理强度设置
    - 控制推理深度
    - 影响成本和质量

    **when_thinking_enabled字段**：
    - 思考模式启用时的额外设置
    - 如max_tokens、temperature等
    - 与thinking字段合并

    **supports_vision字段**：
    - 模型是否支持视觉输入
    - 处理图片和多模态内容
    - 影响工具选择

    **thinking字段**：
    - 思考设置的快捷方式
    - 与when_thinking_enabled合并
    - 简化配置
    """

    name: str = Field(..., description="Unique name for the model")
    display_name: str | None = Field(..., default_factory=lambda: None, description="Display name for the model")
    description: str | None = Field(..., default_factory=lambda: None, description="Description for the model")
    use: str = Field(
        ...,
        description="Class path of the model provider(e.g. langchain_openai.ChatOpenAI)",
    )
    model: str = Field(..., description="Model name")
    model_config = ConfigDict(extra="allow")
    use_responses_api: bool | None = Field(
        default=None,
        description="Whether to route OpenAI ChatOpenAI calls through the /v1/responses API",
    )
    output_version: str | None = Field(
        default=None,
        description="Structured output version for OpenAI responses content, e.g. responses/v1",
    )
    supports_thinking: bool = Field(default_factory=lambda: False, description="Whether the model supports thinking")
    supports_reasoning_effort: bool = Field(default_factory=lambda: False, description="Whether the model supports reasoning effort")
    when_thinking_enabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is enabled",
    )
    supports_vision: bool = Field(default_factory=lambda: False, description="Whether the model supports vision/image inputs")
    thinking: dict | None = Field(
        default_factory=lambda: None,
        description=(
            "Thinking settings for the model. If provided, these settings will be passed to the model when thinking is enabled. "
            "This is a shortcut for `when_thinking_enabled` and will be merged with `when_thinking_enabled` if both are provided."
        ),
    )
