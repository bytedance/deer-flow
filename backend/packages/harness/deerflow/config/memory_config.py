"""
记忆机制配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义记忆存储和更新的配置
2. 控制记忆注入到系统提示词的行为
3. 管理记忆提取和存储的阈值

**什么是记忆机制**：
- 从对话中提取关键信息（事实）
- 持久化存储这些事实
- 在后续对话中自动注入相关记忆
- 实现个性化的长期记忆

**为什么需要记忆机制**：
- AI默认是无状态的，每次对话都是全新开始
- 用户期望AI记住之前说过的话
- 个性化体验需要历史上下文
- 长期关系建立在"记住"的基础上

**记忆工作流程**：
1. 对话过程中检测需要记住的信息
2. 提取事实并评分（置信度）
3. 高置信度事实存入存储
4. 后续对话检索相关记忆
5. 注入到系统提示词中

**为什么需要防抖（debounce）**：
- 避免频繁写入存储
- 合并短时间内多次更新
- 减少IO操作
- 提高性能

**为什么需要置信度阈值**：
- 过滤低质量信息
- 避免存储错误或无关内容
- 控制存储大小
- 提高记忆质量
"""

"""Configuration for memory mechanism."""

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """全局记忆机制配置

    **enabled字段**：
    - 是否启用记忆机制
    - 禁用时代话不会被记忆
    - 可以按需关闭（如敏感场景）

    **storage_path字段**：
    - 记忆数据存储路径
    - 空字符串使用默认位置
    - 绝对路径直接使用
    - 相对路径基于base_dir解析

    **storage_class字段**：
    - 记忆存储提供者的类路径
    - 支持自定义存储后端
    - 默认使用文件存储

    **debounce_seconds字段**：
    - 防抖延迟时间（秒）
    - 等待指定时间后处理队列更新
    - 范围：1-300秒

    **model_name字段**：
    - 用于记忆更新的模型
    - None使用默认模型
    - 可以使用更便宜的模型

    **max_facts字段**：
    - 最大存储事实数量
    - 达到上限后淘汰旧事实
    - 范围：10-500

    **fact_confidence_threshold字段**：
    - 事实存储的最低置信度
    - 低于阈值的事实被丢弃
    - 范围：0.0-1.0

    **injection_enabled字段**：
    - 是否将记忆注入系统提示词
    - 禁用后记忆只存储不使用

    **max_injection_tokens字段**：
    - 记忆注入的最大token数
    - 超出时只注入最相关的记忆
    - 范围：100-8000
    """

    enabled: bool = Field(
        default=True,
        description="Whether to enable memory mechanism",
    )
    storage_path: str = Field(
        default="",
        description=(
            "Path to store memory data. "
            "If empty, defaults to `{base_dir}/memory.json` (see Paths.memory_file). "
            "Absolute paths are used as-is. "
            "Relative paths are resolved against `Paths.base_dir` "
            "(not the backend working directory). "
            "Note: if you previously set this to `.deer-flow/memory.json`, "
            "the file will now be resolved as `{base_dir}/.deer-flow/memory.json`; "
            "migrate existing data or use an absolute path to preserve the old location."
        ),
    )
    storage_class: str = Field(
        default="deerflow.agents.memory.storage.FileMemoryStorage",
        description="The class path for memory storage provider",
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued updates (debounce)",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for memory updates (None = use default model)",
    )
    max_facts: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum number of facts to store",
    )
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for memory injection",
    )


# Global configuration instance
_memory_config: MemoryConfig = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    """获取当前记忆配置

    Returns:
        全局记忆配置实例
    """
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    """设置记忆配置

    **使用场景**：
    - 测试时注入mock配置
    - 运行时调整记忆参数
    - 动态启用/禁用记忆

    Args:
        config: 要设置的MemoryConfig实例
    """
    global _memory_config
    _memory_config = config


def load_memory_config_from_dict(config_dict: dict) -> None:
    """从字典加载记忆配置

    **调用时机**：
    - AppConfig加载过程中调用
    - 从config.yaml的memory节加载

    Args:
        config_dict: 包含记忆配置的字典
    """
    global _memory_config
    _memory_config = MemoryConfig(**config_dict)
