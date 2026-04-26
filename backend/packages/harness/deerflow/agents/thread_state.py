"""
线程状态定义 - DeerFlow代理的状态结构

===================
设计思路说明
===================

**为什么需要状态定义**：
1. **类型安全**：提供状态字段的类型提示
2. **文档作用**：清晰定义可用的状态字段
3. **编译检查**：支持静态类型检查工具
4. **结构化**：组织相关状态字段

**核心设计原则**：
- **模块化**：按功能分组状态字段
- **可选性**：使用NotRequired表示可选字段
- **合并策略**：定义复杂字段的合并行为
- **兼容性**：继承AgentState确保兼容

**状态分组**：
- SandboxState: 沙箱相关状态
- ThreadDataState: 线程数据目录状态
- ViewedImageData: 查看的图像数据
- ThreadState: 完整的线程状态

**为什么这样组织**：
- **关注点分离**：每个类负责一组相关状态
- **可组合**：可以在需要时组合使用
- **可扩展**：便于添加新的状态字段
"""

from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState


class SandboxState(TypedDict):
    """沙箱状态

    **为什么需要这个类**：
    - **沙箱标识**：跟踪当前使用的沙箱实例
    - **资源管理**：知道哪个沙箱正在使用
    - **清理支持**：便于释放沙箱资源

    **字段说明**：
        sandbox_id: 当前沙箱实例的标识符
    """
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    """线程数据状态

    **为什么需要这个类**：
    - **路径管理**：提供工作目录的路径信息
    - **隔离性**：每个线程有独立的数据目录
    - **工具使用**：工具需要知道文件路径

    **字段说明**：
        workspace_path: 工作空间目录路径
        uploads_path: 上传文件目录路径
        outputs_path: 输出文件目录路径
    """
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    """查看的图像数据

    **为什么需要这个类**：
    - **图像存储**：保存查看过的图像信息
    - **多模态支持**：支持视觉模型分析
    - **base64编码**：直接嵌入图像数据

    **字段说明**：
        base64: 图像的base64编码数据
        mime_type: 图像的MIME类型（如image/png）
    """
    base64: str
    mime_type: str


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """产物列表的reducer - 合并并去重产物

    **为什么需要特殊的合并逻辑**：
    - **去重**：避免重复的产物路径
    - **顺序保持**：保持原有的顺序
    - **None处理**：优雅处理空值情况

    **参数说明**：
        existing: 现有的产物列表
        new: 新添加的产物列表

    **返回值**：
        合并去重后的产物列表

    **为什么使用dict.fromkeys**：
    - **去重**：自动去除重复项
    - **顺序保持**：Python 3.7+字典保持插入顺序
    - **高效**：O(n)时间复杂度
    """
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """viewed_images字典的reducer - 合并图像字典

    **为什么需要特殊的合并逻辑**：
    - **增量更新**：支持逐步添加查看的图像
    - **覆盖更新**：新值覆盖同键的旧值
    - **清空机制**：空字典{}表示清空所有图像

    **特殊处理**：
    如果new是空字典{}，清空现有的图像。
    这允许中间件在处理后清空viewed_images状态。

    **参数说明**：
        existing: 现有的图像字典
        new: 新添加的图像字典

    **返回值**：
        合并后的图像字典

    **为什么空字典表示清空**：
    - **明确语义**：{}与None不同，表示明确清空
    - **中间件使用**：中间件可以清空已处理的图像
    - **避免歧义**：None表示无操作，{}表示清空
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # Special case: empty dict means clear all viewed images
    if len(new) == 0:
        return {}
    # Merge dictionaries, new values override existing ones for same keys
    return {**existing, **new}


class ThreadState(AgentState):
    """DeerFlow代理的完整线程状态

    **为什么需要这个类**：
    - **统一状态**：聚合所有状态字段到一个类
    - **类型安全**：提供完整的类型提示
    - **合并策略**：定义复杂字段的合并行为
    - **AgentState兼容**：继承标准接口

    **状态字段**：
    - sandbox: 沙箱状态信息
    - thread_data: 线程数据目录路径
    - title: 线程标题
    - artifacts: 产物文件路径列表（带去重合并）
    - todos: 待办事项列表
    - uploaded_files: 上传的文件信息
    - viewed_images: 查看的图像字典（带合并策略）

    **为什么使用Annotated**：
    - **自定义合并**：为复杂类型指定合并函数
    - **类型提示**：保持字段类型信息
    - **reducer支持**：LangGraph需要reducer处理状态更新
    """
