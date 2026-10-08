"""Validated manifests, independent from HTTP, account policy and UI components."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$", max_length=128)
    version: str = Field(min_length=1, max_length=80)
    name: dict[str, str]
    description: dict[str, str]
    setup: dict[str, str]
    category: Literal["office", "knowledge", "research", "business", "development", "custom"]
    kind: Literal["mcp", "cli", "native"]
    adapter: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    source: str
    icon: str | None = None
    aliases: list[str] = Field(default_factory=list)
    auth_methods: list[Literal["none", "api_key", "oauth"]] = Field(default_factory=list)
    contributions: list[Literal["tools", "skills"]] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})

    @field_validator("source")
    @classmethod
    def safe_source(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Plugin source must use HTTPS")
        return value

    @field_validator("icon")
    @classmethod
    def local_icon(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/images/plugins/") or ".." in value or "?" in value or "#" in value):
            raise ValueError("Catalog icons must be bundled plugin assets")
        return value


def load_catalog(path: Path | None = None) -> list[PluginManifest]:
    """An operator may supply another manifest file; never load executable code."""
    source = path or Path(__file__).with_name("builtin.json")
    items = [PluginManifest.model_validate(item) for item in json.loads(source.read_text(encoding="utf-8"))]
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate plugin identifiers in catalog")
    return items
