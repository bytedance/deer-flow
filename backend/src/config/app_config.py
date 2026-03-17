import logging
import os
import threading
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from src.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from src.config.extensions_config import ExtensionsConfig
from src.config.failure_mode_gate_config import load_failure_mode_gate_config_from_dict
from src.config.journal_style_config import load_journal_style_config_from_dict
from src.config.latex_config import load_latex_config_from_dict
from src.config.memory_config import load_memory_config_from_dict
from src.config.model_config import ModelConfig
from src.config.reviewer2_strategy_config import load_reviewer2_strategy_config_from_dict
from src.config.sandbox_config import SandboxConfig
from src.config.scientific_data_config import load_scientific_data_config_from_dict
from src.config.scientific_vision_config import load_scientific_vision_config_from_dict
from src.config.skills_config import SkillsConfig
from src.config.subagents_config import load_subagents_config_from_dict
from src.config.summarization_config import load_summarization_config_from_dict
from src.config.title_config import load_title_config_from_dict
from src.config.tool_config import ToolConfig, ToolGroupConfig

logger = logging.getLogger(__name__)

load_dotenv()


class AppConfig(BaseModel):
    """Config for the DeerFlow application"""

    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    model_config = ConfigDict(extra="allow", frozen=False)
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` environment variable, use it.
        3. Otherwise, first check the `config.yaml` in the current directory, then fallback to `config.yaml` in the parent directory.
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_CONFIG_PATH"))
            if not path.exists():
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
        """Load config from YAML file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
        if not isinstance(config_data, dict):
            raise ValueError("Config file root must be a mapping/object")
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

        # Load scientific vision config if present
        if "scientific_vision" in config_data:
            load_scientific_vision_config_from_dict(config_data["scientific_vision"])

        # Load scientific data config if present
        if "scientific_data" in config_data:
            load_scientific_data_config_from_dict(config_data["scientific_data"])

        # Load journal style config if present
        if "journal_style" in config_data:
            load_journal_style_config_from_dict(config_data["journal_style"])

        # Load reviewer2 strategy config if present
        if "reviewer2_strategy" in config_data:
            load_reviewer2_strategy_config_from_dict(config_data["reviewer2_strategy"])

        # Load latex config if present
        if "latex" in config_data:
            load_latex_config_from_dict(config_data["latex"])

        # Load failure mode gate config if present
        if "failure_mode_gate" in config_data:
            load_failure_mode_gate_config_from_dict(config_data["failure_mode_gate"])

        # Load checkpointer config if present
        if "checkpointer" in config_data:
            load_checkpointer_config_from_dict(config_data["checkpointer"])

        # Load extensions config separately (it's in a different file)
        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()

        result = cls.model_validate(config_data)
        return result

    @classmethod
    def resolve_env_variables(cls, config: Any, _path: str = "") -> Any:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function.
        Example: $OPENAI_API_KEY

        When an env var is not set, the value is replaced with None and a
        warning is logged instead of crashing the entire application.  This
        allows models whose API key is not configured to be gracefully
        skipped while the rest of the system remains operational.

        Args:
            config: The config to resolve environment variables in.
            _path: Internal – dot-separated config path for log messages.

        Returns:
            The config with environment variables resolved.
        """
        if isinstance(config, str):
            if config.startswith("$"):
                env_var = config[1:]
                env_value = os.getenv(env_var)
                if env_value is None:
                    logger.warning("Environment variable %s is not set (config path: %s). The feature using this value will be unavailable.", env_var, _path or "<root>")
                    return None
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v, f"{_path}.{k}" if _path else k) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item, f"{_path}[{i}]") for i, item in enumerate(config)]
        return config

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        return next((model for model in self.models if model.name == name), None)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the tool config by name.

        Args:
            name: The name of the tool to get the config for.

        Returns:
            The tool config if found, otherwise None.
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the tool group config by name.

        Args:
            name: The name of the tool group to get the config for.

        Returns:
            The tool group config if found, otherwise None.
        """
        return next((group for group in self.tool_groups if group.name == name), None)


_app_config: AppConfig | None = None
_app_config_lock = threading.Lock()


def get_app_config() -> AppConfig:
    """Get the DeerFlow config instance.

    Returns a cached singleton instance. Use `reload_app_config()` to reload
    from file, or `reset_app_config()` to clear the cache.
    Thread-safe via internal lock.
    """
    global _app_config
    if _app_config is not None:
        return _app_config
    with _app_config_lock:
        if _app_config is None:
            _app_config = AppConfig.from_file()
        return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    global _app_config
    with _app_config_lock:
        _app_config = AppConfig.from_file(config_path)
        return _app_config


def reset_app_config() -> None:
    """Reset the cached config instance.

    This clears the singleton cache, causing the next call to
    `get_app_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _app_config
    with _app_config_lock:
        _app_config = None


def set_app_config(config: AppConfig) -> None:
    """Set a custom config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The AppConfig instance to use.
    """
    global _app_config
    with _app_config_lock:
        _app_config = config
