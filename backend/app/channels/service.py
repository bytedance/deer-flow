"""
频道服务（ChannelService）——管理所有IM频道的生命周期

===================
设计思路说明
===================

**核心职责**：
1. 从config.yaml读取channels配置，实例化启用的频道
2. 管理所有IM频道的启动和停止
3. 启动ChannelManager分发器处理消息
4. 提供频道重启、状态查询等管理功能

**为什么需要这个服务**：
1. **统一入口**：所有频道的创建和管理通过一个服务完成
2. **配置驱动**：通过配置文件控制哪些频道启用
3. **延迟加载**：按需导入频道类，减少启动时间
4. **生命周期管理**：确保频道正确启动和停止

**核心设计模式**：
- 服务定位器模式：提供全局访问入口（get_channel_service）
- 延迟初始化：频道类按需导入和实例化
- 配置优先级：环境变量 > 配置文件 > 默认值

**配置优先级说明**：
1. 环境变量优先级最高（便于容器化部署）
2. 配置文件次之（便于本地开发）
3. 默认值作为兜底（确保开箱即用）
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.channels.manager import DEFAULT_GATEWAY_URL, DEFAULT_LANGGRAPH_URL, ChannelManager
from app.channels.message_bus import MessageBus
from app.channels.store import ChannelStore

logger = logging.getLogger(__name__)

# ==================== 频道注册表 ====================
# 频道名称 → 导入路径的映射
# 为什么使用字符串而非直接导入：
# 1. 延迟加载：只在需要时才导入频道类
# 2. 减少依赖：避免未使用的频道依赖被加载
# 3. 可扩展性：添加新频道只需更新此映射
_CHANNEL_REGISTRY: dict[str, str] = {
    "feishu": "app.channels.feishu:FeishuChannel",
    "slack": "app.channels.slack:SlackChannel",
    "telegram": "app.channels.telegram:TelegramChannel",
}

# 环境变量名称定义
# 为什么定义为常量：
# - 避免硬编码字符串
# - 便于统一管理和修改
# - 支持IDE自动补全和重构
_CHANNELS_LANGGRAPH_URL_ENV = "DEER_FLOW_CHANNELS_LANGGRAPH_URL"
_CHANNELS_GATEWAY_URL_ENV = "DEER_FLOW_CHANNELS_GATEWAY_URL"


def _resolve_service_url(config: dict[str, Any], config_key: str, env_key: str, default: str) -> str:
    """解析服务URL，按优先级返回配置值

    ===================
    设计思路说明
    ===================

    **优先级顺序**：
    1. 配置文件中的值（config[config_key]）
    2. 环境变量（os.getenv(env_key)）
    3. 默认值（default）

    **为什么这样设计**：
    - 灵活配置：支持多种配置方式
    - 部署友好：容器化部署常用环境变量
    - 开发便利：本地开发常用配置文件
    - 健壮性：默认值确保服务总能启动

    **参数说明**：
    - config: 配置字典，会被修改（pop掉已使用的键）
    - config_key: 配置字典中的键名
    - env_key: 环境变量名称
    - default: 默认值（当前两者都未设置时使用）

    **为什么使用pop而非get**：
    - 避免配置污染：已处理的配置不应传递给下游
    - 明确配置用途：表示该配置已被消费

    **返回值**：
    解析后的URL字符串
    """
    # 步骤1：检查配置文件
    value = config.pop(config_key, None)
    if isinstance(value, str) and value.strip():
        return value
    # 步骤2：检查环境变量
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return env_value
    # 步骤3：使用默认值
    return default


class ChannelService:
    """管理所有已配置IM频道的生命周期

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 从config.yaml的channels键读取配置
    2. 实例化已启用的频道
    3. 启动ChannelManager分发器

    **为什么这样设计**：
    - **统一管理**：所有频道的生命周期通过一个服务控制
    - **配置驱动**：通过配置文件控制哪些频道启用
    - **依赖注入**：MessageBus和ChannelStore通过构造函数传入
    - **懒加载**：频道类按需导入，减少启动时间

    **架构关系**：
    ChannelService
    ├── MessageBus（消息总线）
    ├── ChannelStore（线程存储）
    ├── ChannelManager（消息分发器）
    └── Channels[]（各IM频道实例）

    **为什么存储_channels和_config**：
    - _channels：跟踪已启动的频道，用于停止和重启
    - _config：保留原始配置，用于动态重启频道
    """

    def __init__(self, channels_config: dict[str, Any] | None = None) -> None:
        # 创建消息总线：所有频道和分发器共享同一个总线
        self.bus = MessageBus()
        # 创建频道存储：持久化IM对话到DeerFlow线程的映射
        self.store = ChannelStore()
        # 复制配置字典，避免修改原始配置
        config = dict(channels_config or {})
        # 解析服务URL：按优先级使用配置文件、环境变量或默认值
        langgraph_url = _resolve_service_url(config, "langgraph_url", _CHANNELS_LANGGRAPH_URL_ENV, DEFAULT_LANGGRAPH_URL)
        gateway_url = _resolve_service_url(config, "gateway_url", _CHANNELS_GATEWAY_URL_ENV, DEFAULT_GATEWAY_URL)
        # 提取默认会话配置
        default_session = config.pop("session", None)
        # 提取各频道的会话配置
        channel_sessions = {name: channel_config.get("session") for name, channel_config in config.items() if isinstance(channel_config, dict)}
        # 创建频道管理器
        self.manager = ChannelManager(
            bus=self.bus,
            store=self.store,
            langgraph_url=langgraph_url,
            gateway_url=gateway_url,
            default_session=default_session if isinstance(default_session, dict) else None,
            channel_sessions=channel_sessions,
        )
        # 已启动的频道字典：name -> Channel实例
        self._channels: dict[str, Any] = {}
        # 保留配置用于动态重启
        self._config = config
        # 服务运行状态
        self._running = False

    @classmethod
    def from_app_config(cls) -> ChannelService:
        """从应用配置创建ChannelService实例

        **为什么使用类方法**：
        - 提供便捷的工厂方法
        - 封装配置加载逻辑
        - 支持多种配置来源

        **配置加载流程**：
        1. 从AppConfig获取全局配置
        2. 提取channels字段（通过model_extra访问）
        3. 传递给构造函数创建实例

        **为什么从model_extra获取**：
        - AppConfig使用Pydantic的extra="allow"模式
        - channels不是预定义字段，存储在model_extra中
        - 这种设计允许扩展配置而不修改模型定义

        **返回值**：
        配置好的ChannelService实例
        """
        from deerflow.config.app_config import get_app_config

        config = get_app_config()
        channels_config = {}
        # extra fields are allowed by AppConfig (extra="allow")
        extra = config.model_extra or {}
        if "channels" in extra:
            channels_config = extra["channels"]
        return cls(channels_config=channels_config)

    async def start(self) -> None:
        """启动管理器和所有已启用的频道

        **启动流程**：
        1. 检查是否已运行（幂等性）
        2. 启动ChannelManager（开始消费入站消息）
        3. 遍历配置，启动每个已启用的频道
        4. 更新运行状态

        **为什么先启动Manager**：
        - Manager需要先订阅出站消息
        - 频道启动后可能立即发送消息
        - 确保消息不会丢失

        **为什么检查enabled字段**：
        - 支持配置频道但不启用（便于测试）
        - 减少不必要的资源消耗
        - 允许动态启用/禁用频道

        **幂等性保证**：
        多次调用start()不会重复启动，直接返回
        """
        if self._running:
            return

        # 步骤1：启动管理器（开始消费入站消息）
        await self.manager.start()

        # 步骤2：启动所有已启用的频道
        for name, channel_config in self._config.items():
            if not isinstance(channel_config, dict):
                continue
            if not channel_config.get("enabled", False):
                logger.info("Channel %s is disabled, skipping", name)
                continue

            await self._start_channel(name, channel_config)

        self._running = True
        logger.info("ChannelService started with channels: %s", list(self._channels.keys()))

    async def stop(self) -> None:
        """停止所有频道和管理器

        **停止流程**：
        1. 遍历所有已启动的频道，依次停止
        2. 清空频道字典
        3. 停止管理器
        4. 更新运行状态

        **为什么使用list()包装**：
        - 遍历副本而非原字典
        - 允许在停止过程中修改字典
        - 避免字典大小改变导致的运行时错误

        **为什么捕获异常**：
        - 单个频道停止失败不影响其他频道
    - 确保尽可能多的资源被释放
        - 记录错误便于后续排查

        **为什么先停止频道**：
        - 频道停止后不再产生新消息
        - 避免消息丢失或重复处理
        - 给管理器时间处理剩余消息
        """
        for name, channel in list(self._channels.items()):
            try:
                await channel.stop()
                logger.info("Channel %s stopped", name)
            except Exception:
                logger.exception("Error stopping channel %s", name)
        self._channels.clear()

        await self.manager.stop()
        self._running = False
        logger.info("ChannelService stopped")

    async def restart_channel(self, name: str) -> bool:
        """重启指定的频道

        **重启流程**：
        1. 如果频道正在运行，先停止它
        2. 从配置中获取频道配置
        3. 使用相同配置重新启动频道

        **为什么返回bool**：
        - 表示重启是否成功
        - 允许调用者根据结果采取行动
        - 便于错误处理和日志记录

        **参数说明**：
        - name: 频道名称（如"feishu"、"slack"）

        **返回值**：
        - True: 重启成功
        - False: 重启失败（配置不存在或启动失败）

        **使用场景**：
        配置热更新、错误恢复、调试等需要重启特定频道的场景
        """
        # 步骤1：停止正在运行的频道
        if name in self._channels:
            try:
                await self._channels[name].stop()
            except Exception:
                logger.exception("Error stopping channel %s for restart", name)
            del self._channels[name]

        # 步骤2：获取频道配置
        config = self._config.get(name)
        if not config or not isinstance(config, dict):
            logger.warning("No config for channel %s", name)
            return False

        # 步骤3：重新启动频道
        return await self._start_channel(name, config)

    async def _start_channel(self, name: str, config: dict[str, Any]) -> bool:
        """实例化并启动单个频道

        **启动流程**：
        1. 从注册表获取频道类的导入路径
        2. 动态导入频道类
        3. 创建频道实例
        4. 调用start方法启动频道
        5. 将频道添加到已启动字典

        **为什么使用动态导入**：
        - 延迟加载：只在需要时才导入频道类
        - 减少依赖：未使用的频道依赖不会被加载
        - 可扩展性：添加新频道只需更新注册表

        **为什么传入bus**：
        - 频道需要通过bus发送和接收消息
        - 依赖注入便于测试
        - 确保所有频道共享同一个总线

        **参数说明**：
        - name: 频道名称
        - config: 频道配置字典

        **返回值**：
        - True: 启动成功
        - False: 启动失败（未知频道类型、导入失败、启动失败）
        """
        # 步骤1：查找频道类路径
        import_path = _CHANNEL_REGISTRY.get(name)
        if not import_path:
            logger.warning("Unknown channel type: %s", name)
            return False

        # 步骤2：动态导入频道类
        try:
            from deerflow.reflection import resolve_class

            channel_cls = resolve_class(import_path, base_class=None)
        except Exception:
            logger.exception("Failed to import channel class for %s", name)
            return False

        # 步骤3：创建并启动频道实例
        try:
            channel = channel_cls(bus=self.bus, config=config)
            await channel.start()
            self._channels[name] = channel
            logger.info("Channel %s started", name)
            return True
        except Exception:
            logger.exception("Failed to start channel %s", name)
            return False

    def get_status(self) -> dict[str, Any]:
        """返回所有频道的状态信息

        **返回结构**：
        ```json
        {
            "service_running": true/false,
            "channels": {
                "feishu": {"enabled": true, "running": true},
                "slack": {"enabled": false, "running": false},
                ...
            }
        }
        ```

        **为什么区分enabled和running**：
        - enabled: 配置中是否启用
        - running: 实际是否正在运行
        - 两者不一致表示配置与实际状态不符

        **使用场景**：
        - 健康检查端点
        - 管理界面显示
        - 调试和监控

        **返回值**：
        包含服务运行状态和各频道状态的字典
        """
        channels_status = {}
        for name in _CHANNEL_REGISTRY:
            config = self._config.get(name, {})
            enabled = isinstance(config, dict) and config.get("enabled", False)
            running = name in self._channels and self._channels[name].is_running
            channels_status[name] = {
                "enabled": enabled,
                "running": running,
            }
        return {
            "service_running": self._running,
            "channels": channels_status,
        }


# -- singleton access（单例访问）---------------------------------------

# 全局频道服务实例
# 为什么使用模块级变量：
# - 实现单例模式，确保全局只有一个服务实例
# - 便于在不同模块中访问同一服务
# - 支持延迟初始化
_channel_service: ChannelService | None = None


def get_channel_service() -> ChannelService | None:
    """获取单例ChannelService实例（如果已启动）

    **为什么返回None**：
    - 表示服务可能未启动
    - 调用者需要处理None情况
    - 避免"隐式创建"的副作用

    **使用场景**：
    需要访问服务但不负责启动服务的场景

    **返回值**：
    - ChannelService: 如果服务已启动
    - None: 如果服务未启动
    """
    return _channel_service


async def start_channel_service() -> ChannelService:
    """从应用配置创建并启动全局ChannelService

    **为什么使用异步函数**：
    - 启动服务涉及异步操作（连接、订阅等）
    - 与ChannelService.start()保持一致的异步风格

    **为什么返回服务实例**：
    - 允许调用者立即使用服务
    - 支持链式调用
    - 便于测试和验证

    **幂等性保证**：
    如果服务已启动，直接返回现有实例，不重复启动

    **使用场景**：
    应用启动时初始化频道服务

    **返回值**：
    已启动的ChannelService实例
    """
    global _channel_service
    if _channel_service is not None:
        return _channel_service
    _channel_service = ChannelService.from_app_config()
    await _channel_service.start()
    return _channel_service


async def stop_channel_service() -> None:
    """停止全局ChannelService

    **为什么设置为None**：
    - 释放内存
    - 允许重新启动服务（测试场景）
    - 避免使用已停止的服务

    **使用场景**：
    应用关闭、测试清理、重启服务等场景

    **幂等性保证**：
    如果服务未启动，直接返回，不报错
    """
    global _channel_service
    if _channel_service is not None:
        await _channel_service.stop()
        _channel_service = None
