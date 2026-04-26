"""
工具调用防护栏（Guardrails）配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义工具调用前的授权检查配置
2. 管理防护栏提供者配置
3. 控制失败时的行为策略

**什么是防护栏（Guardrails）**：
- 在工具执行前进行的安全检查
- 基于策略允许或拒绝工具调用
- 保护系统免受恶意或危险操作

**为什么需要防护栏**：
- 防止AI执行危险操作（删除文件、发送邮件）
- 实现细粒度权限控制
- 符合企业安全合规要求
- 提供审计追踪

**防护栏工作流程**：
1. AI决策调用某个工具
2. 防护栏中间件拦截调用
3. 传递工具名、参数、护照给提供者
4. 提供者返回允许/拒绝决策
5. 允许则执行，拒绝则返回错误

**失败策略（fail_closed）**：
- True: 提供者出错时阻止调用（默认，更安全）
- False: 提供者出错时允许调用（更可用，但风险更高）
"""

"""Configuration for pre-tool-call authorization."""

from pydantic import BaseModel, Field


class GuardrailProviderConfig(BaseModel):
    """防护栏提供者配置

    **use字段**：
    - Python类路径（如deerflow.guardrails.builtin:AllowlistProvider）
    - 支持自定义提供者实现
    - 动态加载机制

    **config字段**：
    - 提供者特定的配置参数
    - 作为kwargs传递给提供者构造函数
    - 灵活适配不同提供者需求

    **内置提供者类型**：
    - AllowlistProvider: 白名单模式（只允许列表中的工具）
    - DenylistProvider: 黑名单模式（禁止列表中的工具）
    - OAPProvider: 基于OAP护照的授权
    """

    use: str = Field(description="Class path (e.g. 'deerflow.guardrails.builtin:AllowlistProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class GuardrailsConfig(BaseModel):
    """工具调用前授权检查配置

    **enabled字段**：
    - 是否启用防护栏中间件
    - 禁用时所有工具调用直接执行
    - 启用时每次调用都经过防护栏检查

    **fail_closed字段**：
    - True: 提供者出错时阻止调用（默认，更安全）
    - False: 提供者出错时允许调用（更可用）

    **passport字段**：
    - OAP护照路径或托管代理ID
    - 用于基于身份的授权决策
    - 可选，取决于提供者实现

    **工作原理**：
    当启用时，每个工具调用都会通过配置的提供者。
    提供者接收工具名称、参数和代理的护照引用，
    并返回允许/拒绝决策。
    """

    enabled: bool = Field(default=False, description="Enable guardrail middleware")
    fail_closed: bool = Field(default=True, description="Block tool calls if provider errors")
    passport: str | None = Field(default=None, description="OAP passport path or hosted agent ID")
    provider: GuardrailProviderConfig | None = Field(default=None, description="Guardrail provider configuration")


_guardrails_config: GuardrailsConfig | None = None


def get_guardrails_config() -> GuardrailsConfig:
    """获取防护栏配置

    **默认值策略**：
    - 未加载时返回默认配置
    - enabled=False（默认禁用）
    - fail_closed=True（出错时阻止）

    **为什么使用默认值**：
    - 防护栏是可选功能
    - 不应该因为缺少配置而失败
    - 向后兼容性

    Returns:
        当前的防护栏配置实例
    """
    global _guardrails_config
    if _guardrails_config is None:
        _guardrails_config = GuardrailsConfig()
    return _guardrails_config


def load_guardrails_config_from_dict(data: dict) -> GuardrailsConfig:
    """从字典加载防护栏配置

    **调用时机**：
    - AppConfig加载过程中调用
    - 从config.yaml的guardrails节加载

    **为什么单独加载**：
    - 防护栏配置可能需要全局访问
    - 避免循环依赖
    - 支持独立重载

    Args:
        data: 包含防护栏配置的字典

    Returns:
        加载的GuardrailsConfig实例
    """
    global _guardrails_config
    _guardrails_config = GuardrailsConfig.model_validate(data)
    return _guardrails_config


def reset_guardrails_config() -> None:
    """重置缓存的配置实例

    **使用场景**：
    - 测试后清理状态
    - 防止单例泄漏影响其他测试
    - 强制下次重新加载

    **为什么需要重置**：
    - 单例模式在测试中可能导致状态污染
    - 每个测试应该有干净的初始状态
    """
    global _guardrails_config
    _guardrails_config = None
