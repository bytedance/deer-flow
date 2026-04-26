"""
DeerFlow路径配置模块

====================
设计思路说明
====================

**核心职责**：
1. 集中管理所有应用数据路径
2. 处理主机与沙箱之间的路径映射
3. 提供安全的路径解析和验证
4. 支持Docker挂载场景

**为什么需要统一路径管理**：
- 路散落在代码中难以维护
- 主机路径和沙箱路径需要映射
- 安全验证需要集中处理
- 支持多种部署场景（本地/Docker）

**目录结构设计**：
```
{base_dir}/
├── memory.json           # 全局记忆文件
├── USER.md              # 全局用户配置文件
├── agents/              # 自定义代理目录
│   └── {agent_name}/
│       ├── config.yaml  # 代理配置
│       ├── SOUL.md      # 代理个性定义
│       └── memory.json  # 代理专属记忆
└── threads/             # 对话线程目录
    └── {thread_id}/
        ├── user-data/   # 挂载到沙箱的/mnt/user-data/
        │   ├── workspace/   # 工作空间
        │   ├── uploads/     # 用户上传文件
        │   └── outputs/     # 代理输出文件
        └── acp-workspace/  # ACP代理工作空间
```

**base_dir解析优先级**（从高到低）：
1. 构造函数参数base_dir
2. DEER_FLOW_HOME环境变量
3. 本地开发回退：cwd/.deer-flow（当cwd是backend/目录时）
4. 默认：$HOME/.deer-flow

**为什么需要VIRTUAL_PATH_PREFIX**：
- 沙箱内看到的路径与主机不同
- 统一的虚拟路径前缀简化配置
- /mnt/user-data是沙箱内的标准挂载点
- 代理只知道虚拟路径，不关心实际主机路径

**安全考虑**：
- thread_id必须通过正则验证（防止路径遍历）
- 虚拟路径解析时检查边界匹配
- resolve()规范化路径防止..攻击
- relative_to()检查确保不逃逸基目录
"""

import os
import re
import shutil
from pathlib import Path

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class Paths:
    """
    DeerFlow应用数据的集中路径配置

    **目录布局**（主机侧）：
        {base_dir}/
        ├── memory.json              # 全局记忆存储
        ├── USER.md                  # 全局用户配置（注入到所有代理）
        ├── agents/                  # 自定义代理目录
        │   └── {agent_name}/        # 单个代理目录
        │       ├── config.yaml      # 代理配置
        │       ├── SOUL.md          # 代理个性/身份（与lead prompt一起注入）
        │       └── memory.json      # 代理专属记忆
        └── threads/                 # 对话线程目录
            └── {thread_id}/         # 单个线程目录
                └── user-data/       # 挂载为沙箱内的/mnt/user-data/
                    ├── workspace/   # 沙箱内：/mnt/user-data/workspace/
                    ├── uploads/     # 沙箱内：/mnt/user-data/uploads/
                    └── outputs/     # 沙箱内：/mnt/user-data/outputs/

    **base_dir解析优先级**：
        1. 构造函数参数`base_dir`
        2. DEER_FLOW_HOME环境变量
        3. 本地开发回退：cwd/.deer-flow（当cwd是backend/目录时）
        4. 默认：$HOME/.deer-flow

    **为什么需要类而不是全局函数**：
    - 支持多个base_dir（测试场景）
    - 封装路径计算逻辑
    - 延迟计算属性（property）
    - 便于mock和测试
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """初始化Paths实例

        **参数说明**：
        - base_dir: 可选的基础目录路径
        - None: 使用默认解析策略

        **为什么使用resolve()**：
        - 规范化路径（消除..和.）
        - 转换为绝对路径
        - 避免路径比较问题

        Args:
            base_dir: 基础目录路径，None表示使用默认策略
        """
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """主机可见的基础目录（用于Docker卷挂载源）

        **为什么需要host_base_dir**：
        - Docker-in-Docker（DooD）场景下路径映射复杂
        - Docker守护进程在主机上，解析主机文件系统路径
        - 容器内路径与主机路径不同
        - 需要明确指定主机侧路径

        **DooD场景说明**：
        - Gateway容器运行在Docker中
        - 挂载了Docker socket（/var/run/docker.sock）
        - 启动沙箱容器时，Docker守护进程在主机上
        - 卷挂载路径需要主机文件系统路径

        **DEER_FLOW_HOST_BASE_DIR环境变量**：
        - 设置为容器base_dir对应的主机路径
        - 例如：容器内/app/data，主机上/opt/deer-flow/data
        - 确保沙箱容器卷挂载正确工作

        **回退到base_dir**：
        - 本地执行时不需要特殊处理
        - 环境变量未设置时使用base_dir

        Returns:
            主机侧基础目录路径
        """
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    @property
    def base_dir(self) -> Path:
        """所有应用数据的根目录

        **解析优先级**：
        1. 显式设置的_base_dir
        2. DEER_FLOW_HOME环境变量
        3. 当前目录/.deer-flow（当cwd是backend/时）
        4. 用户主目录/.deer-flow

        **为什么需要多层回退**：
        - 开发环境：从项目目录运行
        - 生产环境：通过环境变量指定
        - 默认情况：用户主目录

        **为什么检查pyproject.toml**：
        - 识别项目根目录
        - 支持从项目任何位置运行
        - 更可靠的本地开发检测

        Returns:
            解析后的基础目录路径
        """
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        cwd = Path.cwd()
        if cwd.name == "backend" or (cwd / "pyproject.toml").exists():
            return cwd / ".deer-flow"

        return Path.home() / ".deer-flow"

    @property
    def memory_file(self) -> Path:
        """持久化记忆文件路径：`{base_dir}/memory.json`

        **文件内容**：
        - 全局记忆事实
        - 用户偏好设置
        - 跨对话的持久化信息

        Returns:
            记忆文件路径
        """
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """全局用户配置文件路径：`{base_dir}/USER.md`

        **文件作用**：
        - 定义用户的偏好和风格
        - 注入到所有代理的系统提示词
        - 影响所有对话的个性

        Returns:
            用户配置文件路径
        """
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """所有自定义代理的根目录：`{base_dir}/agents/`

        **目录内容**：
        - 每个子目录是一个代理
        - 包含config.yaml和SOUL.md

        Returns:
            代理目录路径
        """
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """特定代理的目录：`{base_dir}/agents/{name}/`

        **为什么使用小写**：
        - 文件系统不敏感问题
        - 统一命名风格
        - 避免大小写混淆

        Args:
            name: 代理名称

        Returns:
            代理目录路径
        """
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """代理专属记忆文件：`{base_dir}/agents/{name}/memory.json`

        **为什么需要代理专属记忆**：
        - 不同代理关注不同信息
        - 隔离记忆避免污染
        - 个性化记忆存储

        Args:
            name: 代理名称

        Returns:
            代理记忆文件路径
        """
        return self.agent_dir(name) / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """
        线程数据的主机路径：`{base_dir}/threads/{thread_id}/`

        **目录结构**：
        - 包含user-data子目录
        - user-data挂载到沙箱内的/mnt/user-data/
        - 所有线程相关数据存储在此

        **安全验证**：
        - thread_id必须通过正则验证
        - 只允许字母、数字、连字符、下划线
        - 防止路径遍历攻击

        Args:
            thread_id: 线程ID

        Returns:
            线程目录路径

        Raises:
            ValueError: thread_id包含不安全字符
        """
        if not _SAFE_THREAD_ID_RE.match(thread_id):
            raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
        return self.base_dir / "threads" / thread_id

    def sandbox_work_dir(self, thread_id: str) -> Path:
        """
        代理工作空间的主机路径
        主机：`{base_dir}/threads/{thread_id}/user-data/workspace/`
        沙箱：`/mnt/user-data/workspace/`

        **目录用途**：
        - 代理执行代码的目录
        - 临时文件存储
        - 工作产物输出

        Args:
            thread_id: 线程ID

        Returns:
            工作空间目录路径
        """
        return self.thread_dir(thread_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """
        用户上传文件的主机路径
        主机：`{base_dir}/threads/{thread_id}/user-data/uploads/`
        沙箱：`/mnt/user-data/uploads/`

        **目录用途**：
        - 用户上传的文档
        - 图片、PDF等参考文件
        - 代理需要访问的用户资源

        Args:
            thread_id: 线程ID

        Returns:
            上传目录路径
        """
        return self.thread_dir(thread_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str) -> Path:
        """
        代理生成产物的主机路径
        主机：`{base_dir}/threads/{thread_id}/user-data/outputs/`
        沙箱：`/mnt/user-data/outputs/`

        **目录用途**：
        - 代理生成的文件
        - 代码、报告、图表等
        - 用户可下载的产物

        Args:
            thread_id: 线程ID

        Returns:
            输出目录路径
        """
        return self.thread_dir(thread_id) / "user-data" / "outputs"

    def acp_workspace_dir(self, thread_id: str) -> Path:
        """
        特定线程的ACP工作空间主机路径
        主机：`{base_dir}/threads/{thread_id}/acp-workspace/`
        沙箱：`/mnt/acp-workspace/`

        **为什么需要独立ACP工作空间**：
        - 每个线程隔离的ACP环境
        - 防止并发会话互相干扰
        - 安全性考虑

        Args:
            thread_id: 线程ID

        Returns:
            ACP工作空间目录路径
        """
        return self.thread_dir(thread_id) / "acp-workspace"

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """
        user-data根目录的主机路径
        主机：`{base_dir}/threads/{thread_id}/user-data/`
        沙箱：`/mnt/user-data/`

        **目录作用**：
        - 所有用户数据的挂载点
        - 包含workspace、uploads、outputs子目录

        Args:
            thread_id: 线程ID

        Returns:
            user-data目录路径
        """
        return self.thread_dir(thread_id) / "user-data"

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """为线程创建所有标准沙箱目录

        **权限设置为0o777的原因**：
        - 沙箱容器可能以不同UID运行
        - 避免权限拒绝错误
        - 卷挂载需要写权限

        **为什么需要显式chmod**：
        - Path.mkdir(mode=...)受umask影响
        - 可能无法获得预期权限
        - 显式调用确保正确权限

        **包含ACP工作空间**：
        - 即使未调用ACP代理也预先创建
        - 可提前挂载到沙箱容器
        - 避免首次调用时的延迟

        Args:
            thread_id: 线程ID
        """
        for d in [
            self.sandbox_work_dir(thread_id),
            self.sandbox_uploads_dir(thread_id),
            self.sandbox_outputs_dir(thread_id),
            self.acp_workspace_dir(thread_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def delete_thread_dir(self, thread_id: str) -> None:
        """删除线程的所有持久化数据

        **幂等性**：
        - 缺失的目录被忽略
        - 不会抛出异常
        - 可安全重复调用

        **使用场景**：
        - 用户删除对话
        - 清理过期数据
        - 测试后清理

        Args:
            thread_id: 线程ID
        """
        thread_dir = self.thread_dir(thread_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str) -> Path:
        """将沙箱虚拟路径解析为主机文件系统路径

        **安全检查**：
        1. 验证路径以虚拟前缀开头
        2. 检查路径遍历尝试（..）
        3. 确保结果在base目录内

        **为什么需要边界匹配**：
        - 防止前缀混淆（如mnt/user-dataX/）
        - 精确匹配避免安全漏洞
        - 更严格的验证

        **使用场景**：
        - 代理返回的文件路径需要转换
        - 下载沙箱内生成的文件
        - 访问上传的文件

        Args:
            thread_id: 线程ID
            virtual_path: 沙箱内看到的虚拟路径（如/mnt/user-data/outputs/report.pdf）

        Returns:
            解析后的主机文件系统绝对路径

        Raises:
            ValueError: 路径不以预期前缀开头或检测到路径遍历尝试
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # Require an exact segment-boundary match to avoid prefix confusion
        # (e.g. reject paths like "mnt/user-dataX/...").
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# ── Singleton ────────────────────────────────────────────────────────────

_paths: Paths | None = None


def get_paths() -> Paths:
    """返回全局Paths单例（延迟初始化）

    **为什么使用单例**：
    - 路径配置是全局资源
    - 避免重复创建
    - 确保一致性

    **延迟初始化**：
    - 首次调用时创建
    - 避免启动时开销
    - 支持配置热重载

    Returns:
        全局Paths实例
    """
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """将路径解析为绝对Path

    **相对路径处理**：
    - 相对于应用基础目录解析
    - 方便配置文件中使用相对路径

    **绝对路径处理**：
    - 直接返回（规范化后）
    - 不修改绝对路径

    **使用场景**：
    - 配置文件中的路径
    - 命令行参数中的路径
    - 用户输入的路径

    Args:
        path: 要解析的路径字符串

    Returns:
        解析后的绝对路径
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
