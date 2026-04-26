"""
沙箱配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义沙箱执行环境配置
2. 支持多种沙箱提供者（本地/AIO）
3. 配置容器资源管理
4. 管理卷挂载和环境变量

**什么是沙箱（Sandbox）**：
- 隔离的代码执行环境
- 防止恶意代码破坏主机
- 提供统一的运行时环境
- 支持资源限制和清理

**为什么需要沙箱**：
- AI生成的代码可能不安全
- 需要隔离执行环境
- 统一依赖管理
- 便于资源清理

**沙箱提供者类型**：
- LocalSandboxProvider: 本地进程执行（开发测试）
- AioSandboxProvider: Docker容器隔离（生产环境）

**为什么allow_host_bash很危险**：
- 允许AI直接在主机执行命令
- 完全绕过沙箱隔离
- 可能导致数据丢失或系统损坏
- 只应在完全可信的环境中使用
"""

from pydantic import BaseModel, ConfigDict, Field


class VolumeMountConfig(BaseModel):
    """卷挂载配置

    **卷挂载的作用**：
    - 在主机和容器间共享目录
    - 持久化容器输出
    - 提供配置文件给容器

    **host_path字段**：
    - 主机上的源路径
    - 必须是绝对路径或相对于base_dir

    **container_path字段**：
    - 容器内的目标路径
    - 容器内看到的路径

    **read_only字段**：
    - True: 容器只能读取
    - False: 容器可以写入
    - 安全考虑：只读挂载更安全
    """

    host_path: str = Field(..., description="Path on the host machine")
    container_path: str = Field(..., description="Path inside the container")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    """沙箱配置

    **通用选项**：
    - use: 沙箱提供者的类路径（必填）
    - allow_host_bash: 允许本地bash执行（仅LocalSandboxProvider）
      - 危险操作，仅用于完全可信的本地工作流

    **AioSandboxProvider特定选项**：
    - image: Docker镜像（默认：all-in-one-sandbox:latest）
    - port: 沙箱容器的基础端口（默认：8080）
    - replicas: 最大并发容器数（默认：3）
      - 达到上限时驱逐最少使用的容器
    - container_prefix: 容器名称前缀（默认：deer-flow-sandbox）
    - idle_timeout: 空闲超时秒数（默认：600=10分钟）
      - 设为0禁用自动释放
    - mounts: 主机与容器间共享目录的卷挂载列表
    - environment: 注入容器的环境变量
      - 以$开头的值从主机环境变量解析

    **为什么需要replicas限制**：
    - 限制资源消耗
    - 防止容器无限增长
    - LRU策略确保公平分配

    **为什么需要idle_timeout**：
    - 自动清理空闲容器
    - 释放系统资源
    - 防止僵尸容器累积
    """

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. deerflow.sandbox.local:LocalSandboxProvider)",
    )
    allow_host_bash: bool = Field(
        default=False,
        description="Allow the bash tool to execute directly on the host when using LocalSandboxProvider. Dangerous; intended only for fully trusted local environments.",
    )
    image: str | None = Field(
        default=None,
        description="Docker image to use for the sandbox container",
    )
    port: int | None = Field(
        default=None,
        description="Base port for sandbox containers",
    )
    replicas: int | None = Field(
        default=None,
        description="Maximum number of concurrent sandbox containers (default: 3). When the limit is reached the least-recently-used sandbox is evicted to make room.",
    )
    container_prefix: str | None = Field(
        default=None,
        description="Prefix for container names",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before sandbox is released (default: 600 = 10 minutes). Set to 0 to disable.",
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of volume mounts to share directories between host and container",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject into the sandbox container. Values starting with $ will be resolved from host environment variables.",
    )

    model_config = ConfigDict(extra="allow")
