"""声明式功能标志和中间件定位，用于create_deerflow_agent

===================
设计思路说明
===================

**为什么需要功能标志系统**：
1. **声明式配置**：通过布尔值或实例声明启用/禁用功能
2. **类型安全**：使用类型提示确保配置正确
3. **可扩展性**：便于添加新功能而不破坏现有代码
4. **纯数据结构**：无I/O，无副作用，易于测试

**核心设计模式**：
- 数据类模式：使用@dataclass简化定义
- 装饰器模式：@Next/@Prev实现定位
- 字面量类型：使用Literal[False]限制特定选项

**为什么这样设计**：
- **纯数据**：只包含配置，不包含逻辑
- **可组合**：多个功能可以独立启用
- **灵活性**：支持默认实现或自定义实现

**公共API**：
- RuntimeFeatures: 功能标志数据类
- @Next: 装饰器，声明中间件应放在锚点之后
- @Prev: 装饰器，声明中间件应放在锚点之前

纯数据类和装饰器 — 无I/O，无副作用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain.agents.middleware import AgentMiddleware


@dataclass
class RuntimeFeatures:
    """``create_deerflow_agent``的声明式功能标志

    **为什么需要这个类**：
    - **集中配置**：所有功能标志在一个地方定义
    - **类型安全**：编译时检查配置类型
    - **文档作用**：清楚列出所有可用功能
    - **默认值**：提供合理的默认配置

    **功能值类型**：
    大多数功能接受：
    - ``True``: 使用内置默认中间件
    - ``False``: 禁用
    - 一个``AgentMiddleware``实例: 使用此自定义实现

    **特殊功能**：
    ``summarization``和``guardrail``没有内置默认 — 它们只
    接受``False``（禁用）或一个``AgentMiddleware``实例（自定义）。

    **为什么某些功能没有内置默认**：
    - **需要配置**：这些功能需要额外的配置参数（如模型）
    - **复杂初始化**：初始化逻辑较复杂，不适合默认值
    - **避免意外**：防止用户意外启用可能产生成本的功能
    """

    sandbox: bool | AgentMiddleware = True
    memory: bool | AgentMiddleware = False
    summarization: Literal[False] | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False
    vision: bool | AgentMiddleware = False
    auto_title: bool | AgentMiddleware = False
    guardrail: Literal[False] | AgentMiddleware = False


# ---------------------------------------------------------------------------
# 中间件定位装饰器
# ---------------------------------------------------------------------------


def Next(anchor: type[AgentMiddleware]):
    """声明此中间件应放在链中*anchor*之后

    **为什么需要定位装饰器**：
    - **精确控制**：允许用户精确控制中间件顺序
    - **解耦**：不需要知道完整的中间件链
    - **灵活性**：可以相对于任何中间件定位

    **使用场景**：
    - 在特定中间件之后插入自定义逻辑
    - 确保依赖关系得到满足
    - 实现自定义的处理流程
    """
    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(f"@Next expects an AgentMiddleware subclass, got {anchor!r}")

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        cls._next_anchor = anchor  # type: ignore[attr-defined]
        return cls

    return decorator


def Prev(anchor: type[AgentMiddleware]):
    """声明此中间件应放在链中*anchor*之前

    **为什么需要@Prev**：
    - **前置处理**：在某些中间件之前执行预处理
    - **依赖注入**：为后续中间件准备数据
    - **行为覆盖**：在默认行为之前拦截

    **与@Next的区别**：
    - @Prev: 在锚点之前插入
    - @Next: 在锚点之后插入

    **使用示例**：
    ```python
    @Prev(ClarificationMiddleware)
    class MyCustomMiddleware(AgentMiddleware):
        # 将在ClarificationMiddleware之前执行
        pass
    ```
    """
    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(f"@Prev expects an AgentMiddleware subclass, got {anchor!r}")

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        cls._prev_anchor = anchor  # type: ignore[attr-defined]
        return cls

    return decorator
