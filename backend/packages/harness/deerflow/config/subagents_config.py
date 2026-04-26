"""
子代理（Subagent）系统配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义子代理超时配置
2. 支持全局和单个代理超时设置
3. 管理子代理执行时间限制

**什么是子代理（Subagent）**：
- 由主代理调用的辅助代理
- 处理特定任务（如搜索、计算）
- 独立的执行上下文和超时
- 实现任务分解和并行

**为什么需要超时配置**：
- 防止子代理无限期运行
- 控制资源使用
- 提供用户响应性
- 避免僵尸进程

**为什么需要单个代理覆盖**：
- 不同任务需要不同时间限制
- 搜索任务可能很快
    - 复杂计算可能需要更长时间
- 灵活适应各种场景

**配置优先级**：
1. 单个代理覆盖（agents[agent_name]）
2. 全局默认（timeout_seconds）
3. 硬编码默认值（900秒=15分钟）
"""

"""Configuration for the subagent system loaded from config.yaml."""

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SubagentOverrideConfig(BaseModel):
    """单个代理的配置覆盖

    **timeout_seconds字段**：
    - 该子代理的超时时间（秒）
    - None表示使用全局默认值
    - 最小值1秒

    **为什么使用None表示未设置**：
    - 区分"显式使用默认"和"未设置"
    - 支持未来扩展
    - 配置文件更清晰
    """

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Timeout in seconds for this subagent (None = use global default)",
    )


class SubagentsAppConfig(BaseModel):
    """子代理系统配置

    **timeout_seconds字段**：
    - 所有子代理的默认超时（秒）
    - 默认900秒（15分钟）
    - 最小值1秒
    - 可被单个代理覆盖

    **agents字段**：
    - 按代理名称键入的覆盖配置
    - 允许为特定代理设置不同超时
    - 字典结构便于查找

    **为什么默认15分钟**：
    - 足够完成大多数任务
    - 不会让用户等待太久
    - 可根据需要调整
    """

    timeout_seconds: int = Field(
        default=900,
        ge=1,
        description="Default timeout in seconds for all subagents (default: 900 = 15 minutes)",
    )
    agents: dict[str, SubagentOverrideConfig] = Field(
        default_factory=dict,
        description="Per-agent configuration overrides keyed by agent name",
    )

    def get_timeout_for(self, agent_name: str) -> int:
        """获取特定代理的有效超时时间

        **解析优先级**：
        1. 检查是否有该代理的覆盖配置
        2. 如果有且设置了超时，使用覆盖值
        3. 否则使用全局默认值

        **使用场景**：
        - 启动子代理前获取超时
        - 应用时间限制
        - 日志记录

        Args:
            agent_name: 子代理名称

        Returns:
            超时时间（秒），优先使用代理覆盖，否则全局默认
        """
        override = self.agents.get(agent_name)
        if override is not None and override.timeout_seconds is not None:
            return override.timeout_seconds
        return self.timeout_seconds


_subagents_config: SubagentsAppConfig = SubagentsAppConfig()


def get_subagents_app_config() -> SubagentsAppConfig:
    """获取当前子代理配置

    Returns:
        全局子代理配置实例
    """
    return _subagents_config


def load_subagents_config_from_dict(config_dict: dict) -> None:
    """从字典加载子代理配置

    **加载后处理**：
    - 生成配置摘要日志
    - 显示全局默认和覆盖
    - 帮助用户理解配置

    **为什么需要日志**：
    - 确认配置正确加载
    - 调试超时问题
    - 审计配置更改

    Args:
        config_dict: 包含子代理配置的字典
    """
    global _subagents_config
    _subagents_config = SubagentsAppConfig(**config_dict)

    overrides_summary = {name: f"{override.timeout_seconds}s" for name, override in _subagents_config.agents.items() if override.timeout_seconds is not None}
    if overrides_summary:
        logger.info(f"Subagents config loaded: default timeout={_subagents_config.timeout_seconds}s, per-agent overrides={overrides_summary}")
    else:
        logger.info(f"Subagents config loaded: default timeout={_subagents_config.timeout_seconds}s, no per-agent overrides")
