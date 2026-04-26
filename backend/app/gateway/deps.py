"""
Gateway依赖注入模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 集中管理FastAPI应用中所有单例对象的访问方式
2. 提供类型安全的依赖注入getter函数
3. 统一处理依赖缺失时的错误响应（503服务不可用）

**核心设计模式**：
- 依赖注入模式：通过FastAPI的依赖注入系统获取单例对象
- 上下文管理器模式：使用AsyncExitStack管理资源的生命周期
- 单例模式：所有运行时组件都是全局唯一的

**为什么这样设计**：
- **关注点分离**：将初始化逻辑（app.py）与访问逻辑（本模块）分离
- **错误处理统一**：所有getter在依赖缺失时返回503错误
- **资源管理安全**：使用AsyncExitStack确保资源正确释放
- **测试友好**：依赖注入便于在测试中替换实现

**Getters使用说明**：
- 路由中使用这些函数作为依赖注入
- 必需依赖缺失时返回503
- 可选依赖（get_store）返回None
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from deerflow.runtime import RunManager, StreamBridge


# ==================== 生命周期管理 ====================
# 为什么需要上下文管理器：
# - 确保所有资源按正确顺序初始化和清理
# - 支持异步资源的上下文管理
# - 任何初始化失败都能正确回滚已创建的资源


@asynccontextmanager
async def langgraph_runtime(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    LangGraph运行时上下文管理器

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 初始化所有LangGraph运行时单例对象
    2. 将这些对象存储到app.state中
    3. 在应用关闭时确保资源正确释放

    **为什么使用AsyncExitStack**：
    - **动态资源管理**：可以动态添加任意数量的异步上下文管理器
    - **异常安全**：如果某个资源初始化失败，已创建的资源会自动回滚
    - **清理保证**：无论正常退出还是异常退出，所有资源都会被正确清理
    - **LIFO顺序**：资源按后进先出顺序清理，符合依赖关系

    **存储到app.state的原因**：
    - FastAPI推荐的应用状态存储方式
    - 生命周期与Application绑定
    - 可通过Request对象在路由中访问

    **初始化的单例对象**：
    1. stream_bridge: 流式响应桥接器，处理SSE连接
    2. checkpointer: 检查点存储器，用于状态持久化
    3. store: 键值存储，用于跨会话数据共享
    4. run_manager: 运行管理器，管理LangGraph运行实例

    **使用方式**：
    在app.py中::
        ```python
        app = FastAPI()
        async with langgraph_runtime(app):
            # 应用运行期间
            yield
        ```

    **为什么这样设计初始化顺序**：
    - 先初始化基础设施（stream_bridge、checkpointer、store）
    - 再初始化依赖基础设施的组件（run_manager）
    - 确保依赖关系正确

    **参数说明**：
    - app: FastAPI应用实例

    **返回值**：
    异步生成器，用于lifespan上下文管理
    """
    # 延迟导入：避免循环依赖
    # 为什么这样处理：
    # - 这些模块可能依赖本模块
    # - 延迟导入打破循环依赖链
    # - 不影响运行时性能（只执行一次）
    from deerflow.agents.checkpointer.async_provider import make_checkpointer
    from deerflow.runtime import make_store, make_stream_bridge

    # 使用AsyncExitStack管理所有异步资源
    # 为什么用enter_async_context：
    # - 将每个资源注册到栈中
    # - 自动处理资源的生命周期
    # - 失败时自动回滚已创建的资源
    async with AsyncExitStack() as stack:
        # 初始化流式响应桥接器
        # 为什么先初始化：
        # - 是其他组件可能依赖的基础设施
        # - 需要最早可用以接受连接
        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge())

        # 初始化检查点存储器
        # 用于状态持久化和恢复
        app.state.checkpointer = await stack.enter_async_context(make_checkpointer())

        # 初始化键值存储
        # 用于跨会话数据共享
        app.state.store = await stack.enter_async_context(make_store())

        # 初始化运行管理器（不需要上下文管理器）
        # 为什么最后初始化：
        # - 可能依赖前面的组件
        # - 简单对象，不需要清理
        app.state.run_manager = RunManager()

        # yield后，应用开始运行
        # 退出上下文时，AsyncExitStack会自动清理所有资源
        yield


# ==================== 依赖注入Getters ====================
# 为什么需要这些getter函数：
# - FastAPI依赖注入系统需要可调用对象
# - 提供统一的错误处理（返回503）
# - 隐藏app.state的访问细节
# - 便于测试时替换实现


def get_stream_bridge(request: Request) -> StreamBridge:
    """
    获取全局StreamBridge实例

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从app.state中获取StreamBridge，如果不存在则返回503错误

    **为什么这样设计**：
    - **快速失败**：依赖缺失时立即返回明确的错误
    - **类型安全**：返回类型明确，便于IDE提示
    - **FastAPI集成**：作为依赖注入函数使用

    **参数说明**：
    - request: FastAPI请求对象，自动注入

    **返回值**：
    StreamBridge实例，用于处理流式响应

    **错误处理**：
    返回503状态码，表示服务暂时不可用
    - 通常发生在应用启动阶段
    - 或资源配置失败时
    """
    bridge = getattr(request.app.state, "stream_bridge", None)
    if bridge is None:
        # 为什么用503：
        # - 表示服务暂时不可用，而非永久错误
        # - 客户端可以稍后重试
        # - 明确指出是哪个依赖缺失
        raise HTTPException(status_code=503, detail="Stream bridge not available")
    return bridge


def get_run_manager(request: Request) -> RunManager:
    """
    获取全局RunManager实例

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从app.state中获取RunManager，如果不存在则返回503错误

    **为什么这样设计**：
    - 统一的依赖获取模式
    - 明确的错误信息
    - 类型安全的返回值

    **参数说明**：
    - request: FastAPI请求对象，自动注入

    **返回值**：
    RunManager实例，用于管理LangGraph运行

    **错误处理**：
    返回503状态码，表示运行管理器不可用
    """
    mgr = getattr(request.app.state, "run_manager", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="Run manager not available")
    return mgr


def get_checkpointer(request: Request) -> Any:
    """
    获取全局检查点实例

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从app.state中获取检查点存储器，如果不存在则返回503错误

    **为什么这样设计**：
    - 检查点类型可能变化（不同后端实现）
    - 返回类型使用Any以适应多种实现
    - 保持一致的错误处理模式

    **参数说明**：
    - request: FastAPI请求对象，自动注入

    **返回值**：
    检查点实例，具体类型取决于配置

    **错误处理**：
    返回503状态码，表示检查点服务不可用
    """
    cp = getattr(request.app.state, "checkpointer", None)
    if cp is None:
        raise HTTPException(status_code=503, detail="Checkpointer not available")
    return cp


def get_store(request: Request) -> Any | None:
    """
    获取全局键值存储实例

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从app.state中获取键值存储

    **为什么这样设计**：
    - **可选依赖**：store可能未被配置
    - **返回None**：与其他getter不同，这里返回None而非抛异常
    - **灵活性**：允许应用在没有store的情况下运行

    **参数说明**：
    - request: FastAPI请求对象，自动注入

    **返回值**：
    - Store实例（如果已配置）
    - None（如果未配置）

    **为什么不抛异常**：
    - store是可选的依赖
    - 某些部署场景可能不需要持久化存储
    - 调用方需要处理None的情况
    """
    return getattr(request.app.state, "store", None)
