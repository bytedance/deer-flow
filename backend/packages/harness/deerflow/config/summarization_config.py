"""
对话摘要配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义自动对话摘要配置
2. 控制摘要触发条件
3. 管理历史保留策略

**为什么需要对话摘要**：
- 长对话会超出模型上下文限制
- 保留关键信息，丢弃冗余内容
- 降低token使用和成本
- 提高响应速度

**摘要工作原理**：
1. 监控对话大小（消息数/token数）
2. 达到触发阈值时生成摘要
3. 保留部分历史+摘要
4. 删除过期的详细历史

**触发类型**：
- messages: 消息数量阈值
- tokens: token数量阈值
- fraction: 模型最大输入的比例

**保留策略**：
- 即使摘要也保留一些最近消息
- 确保上下文连续性
- 平衡记忆和效率
"""

"""Configuration for conversation summarization."""

from typing import Literal

from pydantic import BaseModel, Field

ContextSizeType = Literal["fraction", "tokens", "messages"]


class ContextSize(BaseModel):
    """上下文大小规格（用于trigger或keep参数）

    **type字段**：
    - messages: 按消息数量计算
    - tokens: 按token数量计算
    - fraction: 按模型最大输入的比例计算

    **value字段**：
    - type=messages时：消息数（整数）
    - type=tokens时：token数（整数）
    - type=fraction时：比例（0-1的小数）

    **使用场景**：
    - trigger: 触发摘要的阈值
    - keep: 摘要后保留的历史量
    """

    type: ContextSizeType = Field(description="Type of context size specification")
    value: int | float = Field(description="Value for the context size specification")

    def to_tuple(self) -> tuple[ContextSizeType, int | float]:
        """转换为SummarizationMiddleware期望的元组格式

        Returns:
            (type, value)元组
        """
        return (self.type, self.value)


class SummarizationConfig(BaseModel):
    """自动对话摘要配置

    **enabled字段**：
    - 是否启用自动对话摘要
    - 默认禁用（False）
    - 长对话建议启用

    **model_name字段**：
    - 用于生成摘要的模型
    - None使用轻量级模型
    - 摘要通常不需要最强模型

    **trigger字段**：
    - 触发摘要的一个或多个阈值
    - 任一条件满足即触发
    - 示例：
      - {'type': 'messages', 'value': 50}: 50条消息
      - {'type': 'tokens', 'value': 4000}: 4000个token
      - {'type': 'fraction', 'value': 0.8}: 模型最大输入的80%

    **keep字段**：
    - 摘要后的历史保留策略
    - 指定保留多少历史
    - 默认保留20条消息
    - 示例：
      - {'type': 'messages', 'value': 20}: 保留20条
      - {'type': 'tokens', 'value': 3000}: 保留3000 token
      - {'type': 'fraction', 'value': 0.3}: 保留30%

    **trim_tokens_to_summarize字段**：
    - 准备摘要消息时保留的最大token数
    - 避免摘要本身超出限制
    - None表示不裁剪

    **summary_prompt字段**：
    - 自定义摘要生成提示模板
    - None使用默认LangChain提示
    - 允许定制摘要风格
    """

    enabled: bool = Field(
        default=False,
        description="Whether to enable automatic conversation summarization",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for summarization (None = use a lightweight model)",
    )
    trigger: ContextSize | list[ContextSize] | None = Field(
        default=None,
        description="One or more thresholds that trigger summarization. When any threshold is met, summarization runs. "
        "Examples: {'type': 'messages', 'value': 50} triggers at 50 messages, "
        "{'type': 'tokens', 'value': 4000} triggers at 4000 tokens, "
        "{'type': 'fraction', 'value': 0.8} triggers at 80% of model's max input tokens",
    )
    keep: ContextSize = Field(
        default_factory=lambda: ContextSize(type="messages", value=20),
        description="Context retention policy after summarization. Specifies how much history to preserve. "
        "Examples: {'type': 'messages', 'value': 20} keeps 20 messages, "
        "{'type': 'tokens', 'value': 3000} keeps 3000 tokens, "
        "{'type': 'fraction', 'value': 0.3} keeps 30% of model's max input tokens",
    )
    trim_tokens_to_summarize: int | None = Field(
        default=4000,
        description="Maximum tokens to keep when preparing messages for summarization. Pass null to skip trimming.",
    )
    summary_prompt: str | None = Field(
        default=None,
        description="Custom prompt template for generating summaries. If not provided, uses the default LangChain prompt.",
    )


# Global configuration instance
_summarization_config: SummarizationConfig = SummarizationConfig()


def get_summarization_config() -> SummarizationConfig:
    """获取当前摘要配置

    Returns:
        全局摘要配置实例
    """
    return _summarization_config


def set_summarization_config(config: SummarizationConfig) -> None:
    """设置摘要配置

    Args:
        config: 要设置的摘要配置
    """
    global _summarization_config
    _summarization_config = config


def load_summarization_config_from_dict(config_dict: dict) -> None:
    """从字典加载摘要配置

    Args:
        config_dict: 包含摘要配置的字典
    """
    global _summarization_config
    _summarization_config = SummarizationConfig(**config_dict)
