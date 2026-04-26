"""
自动标题生成配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义对话标题自动生成配置
2. 控制标题长度和格式
3. 管理标题生成提示模板

**为什么需要自动标题**：
- 帮助用户识别对话内容
- 改善对话列表的可读性
- 减少手动命名的负担
- 提升用户体验

**标题生成时机**：
- 对话开始后首次回复
- 用户手动触发
- 定期更新（可选）

**为什么限制标题长度**：
- UI显示空间有限
- 过长标题影响可读性
- 保持简洁明了
"""

"""Configuration for automatic thread title generation."""

from pydantic import BaseModel, Field


class TitleConfig(BaseModel):
    """自动对话标题生成配置

    **enabled字段**：
    - 是否启用自动标题生成
    - 默认启用（True）
    - 禁用后需要手动命名

    **max_words字段**：
    - 生成标题的最大单词数
    - 默认6个单词
    - 范围：1-20
    - 确保标题简洁

    **max_chars字段**：
    - 生成标题的最大字符数
    - 默认60个字符
    - 范围：10-200
    - 配合max_words确保不超出UI限制

    **model_name字段**：
    - 用于生成标题的模型
    - None使用默认模型
    - 标题生成通常不需要最强模型

    **prompt_template字段**：
    - 标题生成的提示模板
    - 支持变量替换：
      - {max_words}: 最大单词数
      - {user_msg}: 用户消息
      - {assistant_msg}: 助手回复
    - 默认提示简洁有效
    - 可自定义以改变标题风格
    """

    enabled: bool = Field(
        default=True,
        description="Whether to enable automatic title generation",
    )
    max_words: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Maximum number of words in the generated title",
    )
    max_chars: int = Field(
        default=60,
        ge=10,
        le=200,
        description="Maximum number of characters in the generated title",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for title generation (None = use default model)",
    )
    prompt_template: str = Field(
        default=("Generate a concise title (max {max_words} words) for this conversation.\nUser: {user_msg}\nAssistant: {assistant_msg}\n\nReturn ONLY the title, no quotes, no explanation."),
        description="Prompt template for title generation",
    )


# Global configuration instance
_title_config: TitleConfig = TitleConfig()


def get_title_config() -> TitleConfig:
    """获取当前标题配置

    Returns:
        全局标题配置实例
    """
    return _title_config


def set_title_config(config: TitleConfig) -> None:
    """设置标题配置

    Args:
        config: 要设置的标题配置
    """
    global _title_config
    _title_config = config


def load_title_config_from_dict(config_dict: dict) -> None:
    """从字典加载标题配置

    Args:
        config_dict: 包含标题配置的字典
    """
    global _title_config
    _title_config = TitleConfig(**config_dict)
