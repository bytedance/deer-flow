"""
DeerFlow代理模块 - 核心代理创建和状态管理

===================
设计思路说明
===================

**为什么需要这个模块**：
1. **统一入口**：作为代理系统的公共API入口
2. **模块组织**：聚合所有子模块的导出
3. **清晰边界**：通过__all__明确公共API
4. **导入便利**：简化外部导入路径

**核心组件**：
- **代理创建**：create_deerflow_agent, make_lead_agent
- **功能标志**：RuntimeFeatures, Next, Prev
- **状态管理**：ThreadState, SandboxState
- **检查点**：get_checkpointer, make_checkpointer, reset_checkpointer

**为什么这样设计导出结构**：
- **分层设计**：工厂函数、配置、状态分离
- **类型安全**：导出类型和类，支持类型检查
- **灵活性**：支持编程式和配置式两种API

**使用方式**：
```python
# 编程式API
from deerflow.agents import create_deerflow_agent, RuntimeFeatures
agent = create_deerflow_agent(model, features=RuntimeFeatures())

# 配置式API
from deerflow.agents import make_lead_agent
agent = make_lead_agent()
```
"""

from .checkpointer import get_checkpointer, make_checkpointer, reset_checkpointer
from .factory import create_deerflow_agent
from .features import Next, Prev, RuntimeFeatures
from .lead_agent import make_lead_agent
from .thread_state import SandboxState, ThreadState

__all__ = [
    "create_deerflow_agent",
    "RuntimeFeatures",
    "Next",
    "Prev",
    "make_lead_agent",
    "SandboxState",
    "ThreadState",
    "get_checkpointer",
    "reset_checkpointer",
    "make_checkpointer",
]
