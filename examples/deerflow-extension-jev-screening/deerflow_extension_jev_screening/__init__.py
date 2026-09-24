"""Opt-in advisory screening of remote tool results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionRegistry, extension

from .screener import Options, ScreeningContributor


@extension(api="0.2.3", name="jev-result-screening")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    options = Options.model_validate(dict(config))
    if options.enabled:
        registry.middlewares(ScreeningContributor(options))
