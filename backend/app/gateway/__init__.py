"""
Gateway模块初始化文件

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 定义Gateway模块的公共API
2. 提供简洁的导入接口
3. 隐藏内部实现细节

**核心设计模式**：
- 门面模式：对外提供简化的接口
- 模块封装：控制外部可访问的内容

**为什么这样设计**：
- **导入便捷**：使用者可以从一个位置导入所有公共组件
- **实现隐藏**：内部实现细节不对外暴露
- **版本控制**：通过__all__明确公共API契约

**公共API说明**：
- app: FastAPI应用实例
- create_app: 应用工厂函数
- GatewayConfig: 配置模型
- get_gateway_config: 配置获取函数
"""

from .app import app, create_app
from .config import GatewayConfig, get_gateway_config

# 定义公共API
# 为什么使用__all__：
# - 明确声明哪些是公共API
# - 防止from module import *时导入内部实现
# - 代码文档化：一目了然模块对外提供什么
# - IDE支持：更好的自动补全提示
__all__ = [
    "app",                  # FastAPI应用实例，可直接使用
    "create_app",           # 应用工厂函数，用于创建新应用实例
    "GatewayConfig",        # 配置模型，类型提示和配置验证
    "get_gateway_config",   # 配置获取函数，返回单例配置
]
