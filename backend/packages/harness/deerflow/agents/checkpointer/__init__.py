"""
检查点模块初始化文件

===================
设计思路说明
===================

**为什么需要这个模块**：
- 统一导出检查点相关的所有公共API
- 简化导入路径
- 隐藏内部实现细节

**导出内容**：
1. get_checkpointer: 同步单例检查点获取函数
2. reset_checkpointer: 重置同步检查点单例
3. checkpointer_context: 同步上下文管理器
4. make_checkpointer: 异步上下文管理器

**为什么同时提供同步和异步API**：
- 同步API：用于CLI工具和简单脚本
- 异步API：用于FastAPI等异步服务器
- 满足不同使用场景的需求

**使用方式**：
```python
# 同步使用
from deerflow.agents.checkpointer import get_checkpointer
cp = get_checkpointer()

# 异步使用
from deerflow.agents.checkpointer.async_provider import make_checkpointer
async with make_checkpointer() as cp:
    ...
```
"""

from .async_provider import make_checkpointer
from .provider import checkpointer_context, get_checkpointer, reset_checkpointer

__all__ = [
    "get_checkpointer",
    "reset_checkpointer",
    "checkpointer_context",
    "make_checkpointer",
]
