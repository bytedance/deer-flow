import logging
import os
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.memory_config import load_memory_config_from_dict
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.subagents_config import load_subagents_config_from_dict
from deerflow.config.summarization_config import load_summarization_config_from_dict
from deerflow.config.title_config import load_title_config_from_dict
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict

load_dotenv()

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    """配置 for the DeerFlow application"""

    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig, description="Tool search / deferred loading configuration")
    model_config = ConfigDict(extra="allow", frozen=False)
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the 配置 文件 路径.

        Priority:
        1. If provided `config_path` 参数, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` 环境 变量, use it.
        3. Otherwise, 第一 检查 the `配置.yaml` in the 当前 目录, then 回退 to `配置.yaml` in the parent 目录.
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
            #    Check 如果 the 配置.yaml is in the 当前 目录


            path = Path(os.getcwd()) / "config.yaml"
            if not path.exists():
                #    Check 如果 the 配置.yaml is in the parent 目录 of CWD


                path = Path(os.getcwd()).parent / "config.yaml"
                if not path.exists():
                    raise FileNotFoundError("`config.yaml` file not found at the current directory nor its parent directory")
            return path

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load 配置 from YAML 文件.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the 配置 文件.

        Returns:
            AppConfig: The loaded 配置.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        #    Check 配置 version before processing


        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)

        #    Load title 配置 如果 present


        if "title" in config_data:
            load_title_config_from_dict(config_data["title"])

        #    Load summarization 配置 如果 present


        if "summarization" in config_data:
            load_summarization_config_from_dict(config_data["summarization"])

        #    Load 内存 配置 如果 present


        if "memory" in config_data:
            load_memory_config_from_dict(config_data["memory"])

        #    Load subagents 配置 如果 present


        if "subagents" in config_data:
            load_subagents_config_from_dict(config_data["subagents"])

        #    Load tool_search 配置 如果 present


        if "tool_search" in config_data:
            load_tool_search_config_from_dict(config_data["tool_search"])

        #    Load checkpointer 配置 如果 present


        if "checkpointer" in config_data:
            load_checkpointer_config_from_dict(config_data["checkpointer"])

        #    Load extensions 配置 separately (it's in a different 文件)


        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()

        result = cls.model_validate(config_data)
        return result

    @classmethod
    def _check_config_version(cls, config_data: dict, config_path: Path) -> None:
        """Check if the 用户's 配置.yaml is outdated compared to 配置.示例.yaml.

        Emits a 警告 if the 用户's config_version is lower than the 示例's.
        Missing config_version is treated as version 0 (pre-versioning).
        """
        try:
            user_version = int(config_data.get("config_version", 0))
        except (TypeError, ValueError):
            user_version = 0

        #    Find 配置.示例.yaml by searching 配置.yaml's 目录 and its parents


        example_path = None
        search_dir = config_path.parent
        for _ in range(5):  #    search 上 to 5 levels


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
                "Your config.yaml (version %d) is outdated — the latest version is %d. "
                "Run `make config-upgrade` to merge new fields into your config.",
                user_version,
                example_version,
            )

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve 环境 variables in the 配置.

        Environment variables are resolved using the `os.getenv` 函数. Example: $OPENAI_API_KEY

        Args:
            配置: The 配置 to resolve 环境 variables in.

        Returns:
            The 配置 with 环境 variables resolved.
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
        """Get the 模型 配置 by 名称.

        Args:
            名称: The 名称 of the 模型 to get the 配置 for.

        Returns:
            The 模型 配置 if found, otherwise None.
        """
        return next((model for model in self.models if model.name == name), None)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the 工具 配置 by 名称.

        Args:
            名称: The 名称 of the 工具 to get the 配置 for.

        Returns:
            The 工具 配置 if found, otherwise None.
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the 工具 组 配置 by 名称.

        Args:
            名称: The 名称 of the 工具 组 to get the 配置 for.

        Returns:
            The 工具 组 配置 if found, otherwise None.
        """
        return next((group for group in self.tool_groups if group.name == name), None)


_app_config: AppConfig | None = None


def get_app_config() -> AppConfig:
    """Get the DeerFlow 配置 instance.

    Returns a cached singleton instance. Use `reload_app_config()` to reload
    from 文件, or `reset_app_config()` to clear the 缓存.
    """
    global _app_config
    if _app_config is None:
        _app_config = AppConfig.from_file()
    return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the 配置 from 文件 and 更新 the cached instance.

    This is useful when the 配置 文件 has been modified and you want
    to pick 上 the changes without restarting the application.

    Args:
        config_path: Optional 路径 to 配置 文件. If not provided,
                     uses the 默认 resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    global _app_config
    _app_config = AppConfig.from_file(config_path)
    return _app_config


def reset_app_config() -> None:
    """Reset the cached 配置 instance.

    This clears the singleton 缓存, causing the 下一个 call to
    `get_app_config()` to reload from 文件. Useful for testing
    or when switching between different configurations.
    """
    global _app_config
    _app_config = None


def set_app_config(config: AppConfig) -> None:
    """Set a custom 配置 instance.

    This allows injecting a custom or mock 配置 for testing purposes.

    Args:
        配置: The AppConfig instance to use.
    """
    global _app_config
    _app_config = config
