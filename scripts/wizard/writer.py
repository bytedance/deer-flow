"""Config file writer for the Setup Wizard.

Writes config.yaml as a minimal working configuration and updates .env
without wiping existing user customisations where possible.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ── .env helpers ──────────────────────────────────────────────────────────────

def read_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict (ignores comments and blank lines)."""
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def write_env_file(env_path: Path, pairs: dict[str, str]) -> None:
    """Merge *pairs* into an existing (or new) .env file.

    Existing keys are updated in place; new keys are appended.
    Lines with comments and other formatting are preserved.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pairs:
                new_lines.append(f"{key}={pairs[key]}")
                updated.add(key)
                continue
        new_lines.append(line)

    for key, value in pairs.items():
        if key not in updated:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── config.yaml helpers ───────────────────────────────────────────────────────

def _yaml_dump(data: Any) -> str:
    return yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _default_tools() -> list[dict[str, Any]]:
    return [
        {"name": "image_search", "use": "deerflow.community.image_search.tools:image_search_tool", "group": "web", "max_results": 5},
        {"name": "ls", "use": "deerflow.sandbox.tools:ls_tool", "group": "file:read"},
        {"name": "read_file", "use": "deerflow.sandbox.tools:read_file_tool", "group": "file:read"},
        {"name": "glob", "use": "deerflow.sandbox.tools:glob_tool", "group": "file:read"},
        {"name": "grep", "use": "deerflow.sandbox.tools:grep_tool", "group": "file:read"},
        {"name": "write_file", "use": "deerflow.sandbox.tools:write_file_tool", "group": "file:write"},
        {"name": "str_replace", "use": "deerflow.sandbox.tools:str_replace_tool", "group": "file:write"},
        {"name": "bash", "use": "deerflow.sandbox.tools:bash_tool", "group": "bash"},
    ]


def _build_tools(
    *,
    base_tools: list[dict[str, Any]] | None,
    search_use: str | None,
    search_tool_name: str,
    search_extra_config: dict | None,
    web_fetch_use: str | None,
    web_fetch_tool_name: str,
    web_fetch_extra_config: dict | None,
    include_bash_tool: bool,
    include_write_tools: bool,
) -> list[dict[str, Any]]:
    tools = deepcopy(base_tools if base_tools is not None else _default_tools())
    tools = [
        tool
        for tool in tools
        if tool.get("name") not in {search_tool_name, web_fetch_tool_name, "write_file", "str_replace", "bash"}
    ]

    web_group = "web"

    if search_use:
        search_tool: dict[str, Any] = {
            "name": search_tool_name,
            "use": search_use,
            "group": web_group,
        }
        if search_extra_config:
            search_tool.update(search_extra_config)
        tools.insert(0, search_tool)

    if web_fetch_use:
        fetch_tool: dict[str, Any] = {
            "name": web_fetch_tool_name,
            "use": web_fetch_use,
            "group": web_group,
        }
        if web_fetch_extra_config:
            fetch_tool.update(web_fetch_extra_config)
        insert_idx = 1 if search_use else 0
        tools.insert(insert_idx, fetch_tool)

    if include_write_tools:
        tools.extend(
            [
                {"name": "write_file", "use": "deerflow.sandbox.tools:write_file_tool", "group": "file:write"},
                {"name": "str_replace", "use": "deerflow.sandbox.tools:str_replace_tool", "group": "file:write"},
            ]
        )

    if include_bash_tool:
        tools.append({"name": "bash", "use": "deerflow.sandbox.tools:bash_tool", "group": "bash"})

    return tools


def _make_model_config_name(model_name: str) -> str:
    """Derive a meaningful config model name from the provider model identifier.

    Replaces path separators and dots with hyphens so the result is a clean
    YAML-friendly identifier (e.g. "google/gemini-2.5-pro" → "gemini-2-5-pro",
    "gpt-5.4" → "gpt-5-4", "deepseek-chat" → "deepseek-chat").
    """
    # Take only the last path component for namespaced models (e.g. "org/model-name")
    base = model_name.split("/")[-1]
    # Replace dots with hyphens so "gpt-5.4" → "gpt-5-4"
    return base.replace(".", "-")


def build_minimal_config(
    *,
    provider_use: str,
    model_name: str,
    display_name: str,
    api_key_field: str,
    env_var: str | None,
    extra_model_config: dict | None = None,
    base_url: str | None = None,
    search_use: str | None = None,
    search_tool_name: str = "web_search",
    search_extra_config: dict | None = None,
    web_fetch_use: str | None = None,
    web_fetch_tool_name: str = "web_fetch",
    web_fetch_extra_config: dict | None = None,
    sandbox_use: str = "deerflow.sandbox.local:LocalSandboxProvider",
    allow_host_bash: bool = False,
    include_bash_tool: bool = False,
    include_write_tools: bool = True,
    config_version: int = 5,
    base_config: dict[str, Any] | None = None,
) -> str:
    """Build the content of a minimal config.yaml."""
    from datetime import date

    today = date.today().isoformat()

    model_entry: dict[str, Any] = {
        "name": _make_model_config_name(model_name),
        "display_name": display_name,
        "use": provider_use,
        "model": model_name,
    }
    if env_var:
        model_entry[api_key_field] = f"${env_var}"
    extra_model_fields = dict(extra_model_config or {})
    if "base_url" in extra_model_fields and not base_url:
        base_url = extra_model_fields.pop("base_url")
    if base_url:
        model_entry["base_url"] = base_url
    if extra_model_fields:
        model_entry.update(extra_model_fields)

    data: dict[str, Any] = deepcopy(base_config or {})
    data["config_version"] = config_version
    data["models"] = [model_entry]
    base_tools = data.get("tools")
    if not isinstance(base_tools, list):
        base_tools = None
    tools = _build_tools(
        base_tools=base_tools,
        search_use=search_use,
        search_tool_name=search_tool_name,
        search_extra_config=search_extra_config,
        web_fetch_use=web_fetch_use,
        web_fetch_tool_name=web_fetch_tool_name,
        web_fetch_extra_config=web_fetch_extra_config,
        include_bash_tool=include_bash_tool,
        include_write_tools=include_write_tools,
    )
    data["tools"] = tools
    sandbox_config = deepcopy(data.get("sandbox") if isinstance(data.get("sandbox"), dict) else {})
    sandbox_config["use"] = sandbox_use
    if sandbox_use == "deerflow.sandbox.local:LocalSandboxProvider":
        sandbox_config["allow_host_bash"] = allow_host_bash
    else:
        sandbox_config.pop("allow_host_bash", None)
    data["sandbox"] = sandbox_config

    header = (
        f"# DeerFlow Configuration\n"
        f"# Generated by 'make setup' on {today}\n"
        f"# Run 'make setup' to reconfigure, or edit this file for advanced options.\n"
        f"# Full reference: config.example.yaml\n\n"
    )

    return header + _yaml_dump(data)


def write_config_yaml(
    config_path: Path,
    *,
    provider_use: str,
    model_name: str,
    display_name: str,
    api_key_field: str,
    env_var: str | None,
    extra_model_config: dict | None = None,
    base_url: str | None = None,
    search_use: str | None = None,
    search_tool_name: str = "web_search",
    search_extra_config: dict | None = None,
    web_fetch_use: str | None = None,
    web_fetch_tool_name: str = "web_fetch",
    web_fetch_extra_config: dict | None = None,
    sandbox_use: str = "deerflow.sandbox.local:LocalSandboxProvider",
    allow_host_bash: bool = False,
    include_bash_tool: bool = False,
    include_write_tools: bool = True,
) -> None:
    """Write (or overwrite) config.yaml with a minimal working configuration."""
    # Read config_version from config.example.yaml if present
    config_version = 5
    example_path = config_path.parent / "config.example.yaml"
    if example_path.exists():
        try:
            import yaml as _yaml
            raw = _yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}
            config_version = int(raw.get("config_version", 5))
            example_defaults = raw
        except Exception:
            example_defaults = None
    else:
        example_defaults = None

    content = build_minimal_config(
        provider_use=provider_use,
        model_name=model_name,
        display_name=display_name,
        api_key_field=api_key_field,
        env_var=env_var,
        extra_model_config=extra_model_config,
        base_url=base_url,
        search_use=search_use,
        search_tool_name=search_tool_name,
        search_extra_config=search_extra_config,
        web_fetch_use=web_fetch_use,
        web_fetch_tool_name=web_fetch_tool_name,
        web_fetch_extra_config=web_fetch_extra_config,
        sandbox_use=sandbox_use,
        allow_host_bash=allow_host_bash,
        include_bash_tool=include_bash_tool,
        include_write_tools=include_write_tools,
        config_version=config_version,
        base_config=example_defaults,
    )
    config_path.write_text(content, encoding="utf-8")
