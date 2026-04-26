"""
网关路径解析工具 - 处理线程虚拟路径的共享模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. **统一路径解析接口**：网关的多个路由模块都需要解析线程虚拟路径
2. **安全边界保护**：集中处理路径遍历安全检查，避免重复代码
3. **错误处理标准化**：将底层异常转换为HTTP友好的错误响应

**核心设计模式**：
- 门面模式：为复杂的路径解析逻辑提供简单接口
- 防御性编程：所有路径操作都经过安全验证

**为什么这样设计**：
- **单一职责**：只负责路径解析，不涉及业务逻辑
- **可复用性**：所有需要路径解析的路由都可以使用
- **安全优先**：默认拒绝可疑路径，防止路径遍历攻击

**关键概念**：
- **虚拟路径**：沙箱内看到的路径（如 /mnt/user-data/outputs/...）
- **实际路径**：宿主机文件系统中的真实路径
- **线程隔离**：每个线程有独立的工作目录，防止跨线程访问
"""

from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import get_paths


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """
    解析线程虚拟路径为实际文件系统路径

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将沙箱内的虚拟路径（如 /mnt/user-data/outputs/file.txt）转换为
    宿主机文件系统中的实际路径，同时进行安全验证。

    **为什么这样设计**：
    1. **路径验证委托**：利用 get_paths().resolve_virtual_path() 进行核心验证
    2. **HTTP异常转换**：将底层 ValueError 转换为适当的 HTTP 响应
    3. **安全分级**：根据错误类型返回不同的状态码

    **安全机制**：
    - 路径遍历检测：拒绝包含 ".." 的路径
    - 边界验证：确保解析后的路径在允许的目录内
    - 线程隔离：确保路径属于指定的线程

    **参数说明**：
    - thread_id: 线程ID，用于定位线程的工作目录
    - virtual_path: 虚拟路径，格式如 /mnt/user-data/outputs/file.txt

    **返回值**：
    - Path对象：表示解析后的实际文件系统路径

    **异常处理**：
    - ValueError → HTTP 403：路径遍历攻击时返回禁止访问
    - ValueError → HTTP 400：其他无效路径时返回错误请求
    - 使用不同的状态码帮助客户端区分错误类型

    **为什么返回403而不是404**：
    - 403表示"理解请求但拒绝执行"，暗示安全限制
    - 404表示"资源不存在"，可能误导客户端
    - 对于路径遍历，明确表示"禁止访问"更符合安全最佳实践
    """
    try:
        # 委托给核心路径解析逻辑
        # get_paths().resolve_virtual_path 会：
        # 1. 验证路径格式
        # 2. 检测路径遍历攻击
        # 3. 解析到线程的实际目录
        return get_paths().resolve_virtual_path(thread_id, virtual_path)
    except ValueError as e:
        # 根据错误信息判断是否为路径遍历攻击
        # "traversal" 关键词表示检测到 ../ 等路径遍历模式
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
