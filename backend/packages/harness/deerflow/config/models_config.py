"""API-writable model configuration (``models_config.json``).

This module backs the web "Models" settings surface (spec 2026-09-10 §5). It is
the model-config counterpart of :mod:`deerflow.config.extensions_config`: a
*separate*, runtime-writable file that is merged into ``AppConfig.models`` at
load time, while ``config.yaml`` remains the operator-trusted source (it also
carries code-executing ``plugins:`` / ``extensions.middlewares`` and is
deliberately never written through Gateway APIs).

Security note (spec §5.3): the web UI never accepts a free-text ``use:`` class
path (a dynamic-import / code-execution boundary, same class as ``plugins:``).
It submits a curated *provider id*; :data:`PROVIDER_ALLOWLIST` maps that id to a
fixed ``use:`` class path and the correct endpoint key, and anything outside the
allowlist is rejected by the API layer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from deerflow.config.model_config import ModelConfig
from deerflow.config.runtime_paths import existing_project_file

#: Sentinel echoed by read endpoints in place of a real api_key, and accepted on
#: write to mean "keep the stored key unchanged" (spec §5.4). Mirrors the channel
#: credentials masking convention.
MASKED_API_KEY = "********"

#: Curated provider allowlist (spec §5.3): provider id -> (use class path,
#: endpoint key). The endpoint key differs per adapter: ``PatchedChatDeepSeek``
#: declares ``api_base`` as its canonical endpoint field (see
#: ``models/factory._declares_api_base``), while OpenAI-compatible and Anthropic
#: clients take ``base_url``.
PROVIDER_ALLOWLIST: dict[str, tuple[str, str]] = {
    "openai-compatible": ("langchain_openai:ChatOpenAI", "base_url"),
    "anthropic": ("langchain_anthropic:ChatAnthropic", "base_url"),
    "deepseek": ("deerflow.models.patched_deepseek:PatchedChatDeepSeek", "api_base"),
}

_USE_TO_PROVIDER: dict[str, str] = {use: provider for provider, (use, _endpoint) in PROVIDER_ALLOWLIST.items()}


def resolve_provider_use(provider: str) -> str | None:
    """Return the fixed ``use:`` class path for an allowlisted provider id, else ``None``."""
    entry = PROVIDER_ALLOWLIST.get(provider)
    return entry[0] if entry else None


def reverse_lookup_provider(use: str) -> str | None:
    """Map a stored ``use:`` class path back to its provider id; ``None`` when not allowlisted."""
    return _USE_TO_PROVIDER.get(use)


class ModelsConfig(BaseModel):
    """The UI-managed model set persisted in ``models_config.json``."""

    models: list[ModelConfig] = Field(default_factory=list, description="Models added/edited through the web settings UI.")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """Resolve the models config file path.

        Priority: explicit argument, then ``DEER_FLOW_MODELS_CONFIG_PATH``, then a
        project-root / legacy search. An explicit argument or set env var is an
        operator assertion, so a missing file there raises ``FileNotFoundError``;
        the fallback search returns ``None`` (the file is optional — most
        deployments configure models only in ``config.yaml``).
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Models config file specified by param `config_path` not found at {path}")
            return path
        elif env_path := os.getenv("DEER_FLOW_MODELS_CONFIG_PATH"):
            path = Path(env_path)
            if not path.exists():
                raise FileNotFoundError(f"Models config file specified by environment variable `DEER_FLOW_MODELS_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("models_config.json",))
            if project_config is not None:
                return project_config

            backend_dir = Path(__file__).resolve().parents[4]
            repo_root = backend_dir.parent
            for candidate in (backend_dir / "models_config.json", repo_root / "models_config.json"):
                if candidate.exists():
                    return candidate
            return None

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve ``$ENV_VAR`` references, mirroring ``config.yaml`` semantics.

        Unlike ``extensions_config`` (which blanks unresolved vars so MCP servers
        never see a literal ``$VAR``), an unresolved reference here raises, matching
        ``AppConfig.resolve_env_variables``: models are core config and a missing
        key should fail loudly rather than silently authenticate as empty.
        """
        if isinstance(config, str):
            if not config.startswith("$"):
                return config
            env_value = os.getenv(config[1:])
            if env_value is None:
                raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
            return env_value
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    @classmethod
    def from_file(cls, config_path: str | None = None) -> ModelsConfig:
        """Load the UI-managed models from ``models_config.json``.

        Returns an empty config when the file does not exist (optional). Raises a
        clear ``ValueError`` for malformed JSON or entries that fail ``ModelConfig``
        validation so a bad UI write surfaces at load rather than as a silent drop.
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            return cls(models=[])
        try:
            with open(resolved_path, encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Models config file at {resolved_path} is not valid JSON: {e}") from e
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"Models config file at {resolved_path} must be a JSON object with a `models` list")
        try:
            resolved_models = cls.resolve_env_variables(raw.get("models") or [])
            return cls.model_validate({"models": resolved_models})
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Models config file at {resolved_path} is invalid: {e}") from e


def merge_ui_models(yaml_models: list[dict], ui: ModelsConfig) -> list[dict]:
    """Union ``config.yaml`` models with UI-managed models, UI winning on name collision.

    The UI version replaces the ``config.yaml`` entry *in place* so the merged
    list's first occurrence of a collided name is the UI one (``AppConfig``'s
    name index keeps the first match).
    """
    merged: list[dict] = [dict(m) for m in yaml_models if isinstance(m, dict)]
    index: dict[str, int] = {}
    for position, entry in enumerate(merged):
        name = entry.get("name")
        if isinstance(name, str):
            index.setdefault(name, position)
    for ui_model in ui.models:
        dumped = ui_model.model_dump()
        name = dumped["name"]
        if name in index:
            merged[index[name]] = dumped
        else:
            index[name] = len(merged)
            merged.append(dumped)
    return merged
