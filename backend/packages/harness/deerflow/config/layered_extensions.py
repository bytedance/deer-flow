"""LayeredExtensionsConfig — load and intersect extensions_config.json across identity layers.

Skills intersection strategy (most restrictive wins):
  - A skill enabled at the global level but disabled at the dept level → disabled
  - A skill not present at a layer → inherits parent's state

MCP servers: last-defined layer wins (dept/user/agent can override global URL/headers).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

from deerflow.config.extensions_config import ExtensionsConfig

logger = logging.getLogger(__name__)

# Sentinel: skill is explicitly disabled at this layer
_DISABLED = False
# Sentinel: skill is explicitly enabled at this layer
_ENABLED = True


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning {} if it doesn't exist."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Failed to load layered extensions %s: %s", path, exc)
        return {}


def load_layered_extensions(identity: "AgentIdentity") -> ExtensionsConfig:
    """Load and merge extensions configs for the given identity.

    MCP servers: later layers override earlier ones (last writer wins).
    Skills: intersection strategy — a skill must be enabled in ALL layers that
    mention it to remain enabled in the final result.
    """
    from deerflow.config.paths import get_paths

    paths = get_paths()
    dirs = paths.identity_extensions_dirs(identity)

    merged_mcp: dict[str, Any] = {}
    # skill_name → None (never seen) | True (explicitly enabled) | False (disabled)
    skill_states: dict[str, bool | None] = {}

    for d in dirs:
        layer = _load_json(d / "extensions_config.json")
        if not layer:
            continue

        ExtensionsConfig.resolve_env_variables(layer)

        # MCP: last-layer override
        mcp = layer.get("mcpServers", {})
        for name, cfg in mcp.items():
            if name in merged_mcp:
                # Shallow merge: override individual keys
                merged_mcp[name] = {**merged_mcp[name], **cfg}
            else:
                merged_mcp[name] = dict(cfg)

        # Skills: intersection (disabled at any layer → disabled overall)
        skills = layer.get("skills", {})
        for name, state in skills.items():
            enabled = state.get("enabled", True) if isinstance(state, dict) else bool(state)
            if name not in skill_states:
                skill_states[name] = enabled
            else:
                # Once disabled, stays disabled
                if not enabled:
                    skill_states[name] = False

    # Build final skills dict
    final_skills: dict[str, Any] = {}
    for name, enabled in skill_states.items():
        if enabled is not None:
            final_skills[name] = {"enabled": enabled}

    return ExtensionsConfig.model_validate({"mcpServers": merged_mcp, "skills": final_skills})
