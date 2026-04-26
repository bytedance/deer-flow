"""
DeerFlow应用配置管理模块

====================
设计思路说明
====================

**核心职责**：
1. 从config.yaml加载应用配置
2. 管理配置缓存和自动重载
3. 支持环境变量替换（$VAR语法）
4. 配置版本检查和升级提示

**为什么需要配置管理**：
- 集中管理所有系统配置，避免硬编码
- 支持多环境部署（开发/测试/生产）
- 允许运行时热重载，无需重启服务
- 版本检查帮助用户保持配置最新

**配置优先级**（从高到低）：
1. 显式指定的config_path参数
2. DEER_FLOW_CONFIG_PATH环境变量
3. 当前目录的config.yaml
4. 父目录的config.yaml

**全局单例模式**：
- _app_config: 缓存的配置实例
- 自动检测文件修改并重载
- 支持测试时注入自定义配置

**配置热重载机制**：
- 通过比较文件修改时间（mtime）检测变化
- 首次访问或文件变化时自动加载
- 提供手动重载接口用于测试
"""

import logging
import os
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.acp_config import load_acp_config_from_dict
from deerflow.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.guardrails_config import load_guardrails_config_from_dict
from deerflow.config.memory_config import load_memory_config_from_dict
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import load_subagents_config_from_dict
from deerflow.config.summarization_config import load_summarization_config_from_dict
from deerflow.config.title_config import load_title_config_from_dict
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict

load_dotenv()

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    """DeerFlow应用配置模型

    **配置结构说明**：
    - log_level: 日志级别，控制输出详细程度
    - token_usage: Token使用统计配置（成本追踪）
    - models: 可用的LLM模型列表
    - sandbox: 沙箱执行环境配置
    - tools: 可用工具列表（内置工具）
    - tool_groups: 工具分组（用于权限控制）
    - skills: 技能系统配置
    - extensions: 扩展配置（MCP服务器和技能状态）
    - tool_search: 工具搜索和延迟加载配置
    - checkpointer: 状态持久化配置
    - stream_bridge: 流式桥接配置

    **为什么使用extra="allow"**：
    - 允许配置文件包含额外字段（向前兼容）
    - 新版本添加的配置项不会破坏旧版本
    - 便于A/B测试新功能

    **为什么使用frozen=False**：
    - 允许运行时修改配置
    - 支持热重载场景
    - 便于测试时调整配置
    """

    log_level: str = Field(default="info", description="Logging level for deerflow modules (debug/info/warning/error)")
    token_usage: TokenUsageConfig = Field(default_factory=TokenUsageConfig, description="Token usage tracking configuration")
    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig, description="Tool search / deferred loading configuration")
    model_config = ConfigDict(extra="allow", frozen=False)
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")
    stream_bridge: StreamBridgeConfig | None = Field(default=None, description="Stream bridge configuration")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """解析配置文件路径

        **解析优先级**（从高到低）：
        1. 显式传入的config_path参数
        2. DEER_FLOW_CONFIG_PATH环境变量
        3. 当前工作目录的config.yaml
        4. 父目录的config.yaml（支持monorepo结构）

        **为什么需要多层回退**：
        - 开发环境：从项目根目录运行
        - 生产环境：通过环境变量指定配置
        - 测试环境：可以显式传入测试配置路径
        - Monorepo：配置可能在父目录

        **为什么抛出FileNotFoundError**：
    - 配置文件是必需的，不应该静默失败
    - 提供清晰的错误消息帮助用户定位问题
    - 早期失败优于运行时崩溃

        Args:
            config_path: 可选的配置文件路径

        Returns:
            解析后的配置文件路径

        Raises:
            FileNotFoundError: 配置文件不存在
        """
        if config_path:
            path = Path(config_path)
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_CONFIG_PATH"))
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by environment variable `DEER_FLOW_CONFIG_PATH` not found at {path}")
            return path
        else:
            # Check if the config.yaml is in the current directory
            path = Path(os.getcwd()) / "config.yaml"
            if not path.exists():
                # Check if the config.yaml is in the parent directory of CWD
                path = Path(os.getcwd()).parent / "config.yaml"
                if not path.exists():
                    raise FileNotFoundError("`config.yaml` file not found at the current directory nor its parent directory")
            return path

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """从YAML文件加载配置

        **加载流程**：
        1. 解析配置文件路径
        2. 读取并解析YAML
        3. 检查配置版本
        4. 替换环境变量
        5. 分别加载各模块配置到全局变量
        6. 加载扩展配置（单独文件）
        7. 验证并返回配置对象

        **为什么各模块配置要分离加载**：
        - 某些配置需要全局访问（如memory_config）
        - 避免循环依赖
        - 支持独立重载子模块配置
        - 保持向后兼容性

        **为什么扩展配置在单独文件**：
        - extensions_config.json包含敏感信息（OAuth密钥）
    - 可能由外部系统管理（如K8s ConfigMap）
    - JSON格式更适合自动化工具生成
    - 频繁变化，独立存储更安全

        Args:
            config_path: 配置文件路径

        Returns:
            加载的AppConfig实例
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # Check config version before processing
        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)

        # Load title config if present
        if "title" in config_data:
            load_title_config_from_dict(config_data["title"])

        # Load summarization config if present
        if "summarization" in config_data:
            load_summarization_config_from_dict(config_data["summarization"])

        # Load memory config if present
        if "memory" in config_data:
            load_memory_config_from_dict(config_data["memory"])

        # Load subagents config if present
        if "subagents" in config_data:
            load_subagents_config_from_dict(config_data["subagents"])

        # Load tool_search config if present
        if "tool_search" in config_data:
            load_tool_search_config_from_dict(config_data["tool_search"])

        # Load guardrails config if present
        if "guardrails" in config_data:
            load_guardrails_config_from_dict(config_data["guardrails"])

        # Load checkpointer config if present
        if "checkpointer" in config_data:
            load_checkpointer_config_from_dict(config_data["checkpointer"])

        # Load stream bridge config if present
        if "stream_bridge" in config_data:
            load_stream_bridge_config_from_dict(config_data["stream_bridge"])

        # Always refresh ACP agent config so removed entries do not linger across reloads.
        load_acp_config_from_dict(config_data.get("acp_agents", {}))

        # Load extensions config separately (it's in a different file)
        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()

        result = cls.model_validate(config_data)
        return result

    @classmethod
    def _check_config_version(cls, config_data: dict, config_path: Path) -> None:
        """检查用户配置是否过时（与config.example.yaml对比）

        **版本检查机制**：
        - 用户配置文件包含config_version字段
        - 与config.example.yaml的版本对比
        - 缺失字段视为版本0（版本化前）

        **为什么需要版本检查**：
        - 新版本可能添加必需的配置字段
        - 提醒用户保持配置更新
        - 避免因配置过时导致的运行时错误
        - 提供升级命令提示

        **为什么只警告不阻止**：
        - 向后兼容很重要，旧配置可能仍然可用
        - 用户可能有意使用旧版本
        - 警告足够引起注意，强制升级太激进

        **搜索范围**（最多5层）：
        - 支持monorepo结构
        - 配置文件可能在父目录
        - 限制搜索深度避免性能问题

        Args:
            config_data: 解析后的配置数据
            config_path: 配置文件路径
        """
        try:
            user_version = int(config_data.get("config_version", 0))
        except (TypeError, ValueError):
            user_version = 0

        # Find config.example.yaml by searching config.yaml's directory and its parents
        example_path = None
        search_dir = config_path.parent
        for _ in range(5):  # search up to 5 levels
            candidate = search_dir / "config.example.yaml"
            if candidate.exists():
                example_path = candidate
                break
            parent = search_dir.parent
            if parent == search_dir:
                break
            search_dir = parent
        if example_path is None:
            return

        try:
            with open(example_path, encoding="utf-8") as f:
                example_data = yaml.safe_load(f)
            raw = example_data.get("config_version", 0) if example_data else 0
            try:
                example_version = int(raw)
            except (TypeError, ValueError):
                example_version = 0
        except Exception:
            return

        if user_version < example_version:
            logger.warning(
                "Your config.yaml (version %d) is outdated — the latest version is %d. Run `make config-upgrade` to merge new fields into your config.",
                user_version,
                example_version,
            )

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """递归解析配置中的环境变量

        **环境变量语法**：$VAR_NAME
        - 以$开头表示环境变量引用
        - 递归处理字典、列表和字符串
        - 未找到的环境变量抛出异常

        **为什么使用环境变量**：
        - 敏感信息（API密钥）不应写入配置文件
        - 不同环境使用不同值（开发/生产）
        - 容器化部署的标准做法（12-Factor App）

        **为什么抛出异常而不是返回默认值**：
        - 配置错误应该早期失败
        - 避免运行时出现难以调试的问题
        - 强制用户正确配置环境

        **使用示例**：
        ```yaml
        models:
          - name: openai
            api_key: $OPENAI_API_KEY  # 从环境变量读取
        ```

        Args:
            config: 需要解析环境变量的配置对象

        Returns:
            解析后的配置对象

        Raises:
            ValueError: 环境变量未定义
        """
        if isinstance(config, str):
            if config.startswith("$"):
                env_value = os.getenv(config[1:])
                if env_value is None:
                    raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    def get_model_config(self, name: str) -> ModelConfig | None:
        """根据名称获取模型配置

        **为什么使用线性搜索**：
        - 模型数量通常很少（<10个）
        - 简单直接，无需维护额外索引
        - 性能影响可忽略

        **使用场景**：
        - 运行时查找指定模型的配置
        - 验证模型是否已配置
        - 获取模型的API密钥等参数

        Args:
            name: 模型名称

        Returns:
            找到的模型配置，未找到返回None
        """
        return next((model for model in self.models if model.name == name), None)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """根据名称获取工具配置

        **使用场景**：
        - 验证工具是否可用
        - 获取工具的执行参数
        - 检查工具权限设置

        Args:
            name: 工具名称

        Returns:
            找到的工具配置，未找到返回None
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """根据名称获取工具分组配置

        **工具分组的作用**：
        - 将多个工具组织成逻辑组
    - 为代理分配工具权限时使用分组
    - 简化权限管理（一次授权整组工具）

        **使用场景**：
        - 检查代理是否有权访问某组工具
        - 获取组内所有工具列表
        - 权限验证

        Args:
            name: 工具分组名称

        Returns:
            找到的工具分组配置，未找到返回None
        """
        return next((group for group in self.tool_groups if group.name == name), None)


_app_config: AppConfig | None = None
_app_config_path: Path | None = None
_app_config_mtime: float | None = None
_app_config_is_custom = False


def _get_config_mtime(config_path: Path) -> float | None:
    """获取配置文件的修改时间

    **为什么需要mtime**：
    - 检测文件是否被修改
    - 决定是否需要重新加载配置
    - 避免不必要的磁盘IO

    **为什么捕获OSError**：
    - 文件可能在检查时被删除
    - 权限问题可能导致读取失败
    - 返回None表示无法获取mtime

    Args:
        config_path: 配置文件路径

    Returns:
        文件修改时间戳，失败返回None
    """
    try:
        return config_path.stat().st_mtime
    except OSError:
        return None


def _load_and_cache_app_config(config_path: str | None = None) -> AppConfig:
    """从磁盘加载配置并刷新缓存元数据

    **加载流程**：
    1. 解析配置文件路径
    2. 加载并解析YAML
    3. 更新全局缓存变量
    4. 重置custom标志

    **为什么需要custom标志**：
    - 测试时可能注入自定义配置
    - 自定义配置不应被自动重载覆盖
    - 提供显式控制权

    Args:
        config_path: 可选的配置文件路径

    Returns:
        加载的AppConfig实例
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom

    resolved_path = AppConfig.resolve_config_path(config_path)
    _app_config = AppConfig.from_file(str(resolved_path))
    _app_config_path = resolved_path
    _app_config_mtime = _get_config_mtime(resolved_path)
    _app_config_is_custom = False
    return _app_config


def get_app_config() -> AppConfig:
    """获取DeerFlow配置实例

    **自动重载机制**：
    - 首次调用时加载配置
    - 检测文件变化自动重载
    - 自定义配置不自动重载

    **重载触发条件**：
    1. 配置文件为None（首次加载）
    2. 配置文件路径变化
    3. 文件修改时间变化

    **为什么使用单例模式**：
    - 配置是全局共享资源
    - 避免重复加载浪费资源
    - 确保所有模块使用同一配置

    Returns:
        缓存的AppConfig实例
    """
    global _app_config, _app_config_path, _app_config_mtime

    if _app_config is not None and _app_config_is_custom:
        return _app_config

    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)

    should_reload = _app_config is None or _app_config_path != resolved_path or _app_config_mtime != current_mtime
    if should_reload:
        if _app_config_path == resolved_path and _app_config_mtime is not None and current_mtime is not None and _app_config_mtime != current_mtime:
            logger.info(
                "Config file has been modified (mtime: %s -> %s), reloading AppConfig",
                _app_config_mtime,
                current_mtime,
            )
        _load_and_cache_app_config(str(resolved_path))
    return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """从文件重新加载配置并更新缓存

    **使用场景**：
    - 配置文件被修改后立即生效
    - 不重启服务的情况下更新配置
    - 切换到不同的配置文件

    **为什么需要手动重载**：
    - 某些场景需要立即应用配置更改
    - 不等待下次自动检测
    - 明确的语义更清晰

    Args:
        config_path: 可选的配置文件路径

    Returns:
        新加载的AppConfig实例
    """
    return _load_and_cache_app_config(config_path)


def reset_app_config() -> None:
    """重置缓存的配置实例

    **使用场景**：
    - 测试后清理状态
    - 切换到不同配置前重置
    - 强制下次调用重新加载

    **为什么需要重置功能**：
    - 单例模式需要显式清理机制
    - 测试隔离需要
    - 调试时可能需要
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom
    _app_config = None
    _app_config_path = None
    _app_config_mtime = None
    _app_config_is_custom = False


def set_app_config(config: AppConfig) -> None:
    """设置自定义配置实例

    **使用场景**：
    - 单元测试注入mock配置
    - A/B测试不同配置
    - 绕过文件系统加载

    **为什么custom配置不自动重载**：
    - 测试时需要稳定的配置
    - 避免外部文件变化影响测试
    - 提供显式控制

    Args:
        config: 要使用的AppConfig实例
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom
    _app_config = config
    _app_config_path = None
    _app_config_mtime = None
    _app_config_is_custom = True
