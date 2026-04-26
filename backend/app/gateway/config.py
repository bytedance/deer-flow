"""
API Gateway配置模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 统一管理Gateway服务器的配置参数（主机、端口、CORS等）
2. 提供类型安全的配置对象，避免配置错误
3. 支持从环境变量加载配置，便于容器化部署

**核心设计模式**：
- 单例模式：通过全局变量确保配置只加载一次
- 延迟初始化：配置在首次访问时才从环境变量加载
- 不可变对象：使用Pydantic BaseModel确保配置不可变

**为什么这样设计**：
- 使用Pydantic进行配置验证，自动处理类型转换
- 默认值提供开箱即用的体验
- 环境变量优先级高于默认值，支持灵活部署
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    """
    API Gateway配置模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    定义Gateway服务器的所有配置参数及其默认值

    **为什么使用Pydantic**：
    - 自动类型验证：确保配置值类型正确
    - 序列化支持：便于配置的导出和导入
    - 文档生成：Field的description可用于生成API文档

    **配置项说明**：
    - host: 服务器监听地址，0.0.0.0表示监听所有网卡
    - port: 服务器监听端口
    - cors_origins: 允许的跨域来源列表
    """

    host: str = Field(default="0.0.0.0", description="Gateway服务器绑定的主机地址")
    port: int = Field(default=8001, description="Gateway服务器绑定的端口")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="允许的CORS（跨域）来源列表"
    )


# 全局配置单例
# 为什么使用全局变量：
# - 确保配置只加载一次，避免重复读取环境变量
# - 提供全局访问点，便于各模块获取配置
# - 延迟初始化：首次调用时才加载
_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    """
    获取Gateway配置，首次调用时从环境变量加载

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 检查配置是否已加载
    2. 如果未加载，从环境变量读取并创建配置对象
    3. 返回配置单例

    **为什么这样设计**：
    - **延迟加载**：避免模块导入时就读取环境变量
    - **单例模式**：确保配置全局唯一且只初始化一次
    - **环境变量优先**：允许通过环境变量覆盖默认配置

    **环境变量映射**：
    - GATEWAY_HOST → host（默认: 0.0.0.0）
    - GATEWAY_PORT → port（默认: 8001）
    - CORS_ORIGINS → cors_origins（逗号分隔，默认: http://localhost:3000）

    **返回值**：
    GatewayConfig实例，包含当前Gateway的所有配置

    **使用示例**：
    ```python
    config = get_gateway_config()
    print(f"Gateway running on {config.host}:{config.port}")
    ```
    """
    global _gateway_config

    # 首次调用时从环境变量加载配置
    if _gateway_config is None:
        # 解析CORS来源：支持逗号分隔的多个来源
        # 为什么用逗号分隔：
        # - 环境变量通常是字符串形式
        # - 逗号分隔是常见的多值表示方式
        # - 便于在Docker/Kubernetes等环境中配置
        cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

        _gateway_config = GatewayConfig(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8001")),
            cors_origins=cors_origins_str.split(","),
        )

    return _gateway_config
