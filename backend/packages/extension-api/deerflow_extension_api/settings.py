"""Declarative, non-secret deployment parameters for plugin contributions.

Values are supplied by the deployment-installed plugin; no online editing.
Settings are not a code-loading API or a secret store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SettingValue = bool | int | str


@dataclass(frozen=True)
class FrontendBinding:
    """Bind settings to a trusted browser module loaded at page startup.

    Module identifiers are names, never remote script URLs. Only explicitly
    listed non-secret fields are projected to authenticated browser clients.
    """

    module: str
    public_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_fields", tuple(self.public_fields))


@dataclass(frozen=True)
class SettingsField:
    key: str
    title: str
    kind: Literal["boolean", "integer", "string"]
    default: SettingValue
    description: str = ""
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = 256


@dataclass(frozen=True)
class SettingsContribution:
    namespace: str
    title: str
    fields: tuple[SettingsField, ...]
    description: str = ""
    scope: Literal["deployment"] = "deployment"
    applies: Literal["next-run", "page-load", "next-request", "request-and-page-load"] = "next-run"
    frontend: FrontendBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
