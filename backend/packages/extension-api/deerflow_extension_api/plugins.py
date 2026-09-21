"""Unified, optional browser/backend contributions from one trusted package.

Backend actions run in the Gateway process. The host supplies current settings
and an authenticated principal for each admitted call; this is not a sandbox.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.settings import FrontendBinding, SettingsContribution, SettingsField, SettingValue


@dataclass(frozen=True)
class ActionContext:
    principal: ExtensionPrincipal
    settings: Mapping[str, SettingValue]


@dataclass(frozen=True)
class BackendAction:
    name: str
    handler: Callable[[Mapping[str, Any], ActionContext], Awaitable[Any]]


@dataclass(frozen=True)
class ToolContext(ActionContext):
    """Host-bound identity for a model tool call.

    Resource ownership remains the plugin provider's responsibility,
    using principal.user_id.
    """

    thread_id: str | None


@dataclass(frozen=True)
class ModelTool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any], ToolContext], Awaitable[Any]]
    group: str = "extensions"


@dataclass(frozen=True)
class BrowserModule:
    """Experimental single-file browser transport, not the final asset package API.

    A future versioned packaged-asset transport will coexist with this inline
    form; see docs/full-stack-plugins.md for the compatibility direction.
    """

    module: str
    code: str
    public_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_fields", tuple(self.public_fields))


@dataclass(frozen=True)
class PluginContribution:
    """One identity, one enabled switch, optional settings and implementations.

    The host owns the boolean ``enabled`` field. Other fields are non-secret
    settings, private to the backend unless explicitly projected by BrowserModule.
    Supply at least one browser module, backend action, or model tool. Backend implementations
    are installed through the existing operator-controlled Python loader.
    """

    namespace: str
    title: str
    description: str = ""
    enabled: bool = False
    fields: tuple[SettingsField, ...] = ()
    frontend: BrowserModule | None = None
    backend: tuple[BackendAction, ...] = ()
    api_version: int = 1
    tools: tuple[ModelTool, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "backend", tuple(self.backend))
        object.__setattr__(self, "tools", tuple(self.tools))

    def settings_contribution(self) -> SettingsContribution:
        return SettingsContribution(
            namespace=self.namespace,
            title=self.title,
            description=self.description,
            fields=(SettingsField("enabled", "启用 / Enabled", "boolean", self.enabled), *self.fields),
            applies="request-and-page-load" if (self.backend or self.tools) and self.frontend else "next-request" if self.backend or self.tools else "page-load",
            frontend=FrontendBinding(self.frontend.module, ("enabled", *self.frontend.public_fields)) if self.frontend else None,
        )
