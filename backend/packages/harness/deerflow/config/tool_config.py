"""
工具配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义单个工具配置
2. 定义工具分组配置
3. 支持工具权限管理

**为什么需要工具配置**：
- 声明式定义可用工具
- 支持工具分组和权限控制
- 灵活扩展工具生态
- 统一工具管理接口

**工具分组的作用**：
- 按功能组织工具（如"文件操作"、"网络请求"）
- 简化权限管理（一次授权整组）
- 为不同代理分配不同工具集
- 实现最小权限原则

**为什么使用extra="allow"**：
- 不同工具可能需要不同参数
- 支持工具特定配置
- 向前兼容性
- 灵活扩展
"""

from pydantic import BaseModel, ConfigDict, Field


class ToolGroupConfig(BaseModel):
    """工具分组配置

    **name字段**：
    - 工具分组的唯一标识符
    - 用于权限控制和工具分配
    - 必填字段

    **为什么需要分组**：
    - 组织相关工具
    - 简化权限管理
    - 支持批量授权

    **extra="allow"的作用**：
    - 支持分组特定配置
    - 如描述、图标等UI属性
    """

    name: str = Field(..., description="Unique name for the tool group")
    model_config = ConfigDict(extra="allow")


class ToolConfig(BaseModel):
    """单个工具配置

    **name字段**：
    - 工具的唯一标识符
    - 用于在配置中引用该工具
    - 必填字段

    **group字段**：
    - 工具所属的分组名称
    - 用于权限控制
    - 必填字段

    **use字段**：
    - 工具提供者的变量路径
    - 格式：module:variable
    - 示例：deerflow.sandbox.tools:bash_tool
    - 动态导入机制

    **为什么使用模块路径**：
    - 支持自定义工具
    - 动态加载
    - 解耦配置和实现

    **extra="allow"的作用**：
    - 支持工具特定配置
    - 如参数、描述、图标等
    """

    name: str = Field(..., description="Unique name for the tool")
    group: str = Field(..., description="Group name for the tool")
    use: str = Field(
        ...,
        description="Variable name of the tool provider(e.g. deerflow.sandbox.tools:bash_tool)",
    )
    model_config = ConfigDict(extra="allow")
