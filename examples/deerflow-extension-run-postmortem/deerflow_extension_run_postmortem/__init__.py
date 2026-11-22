"""Run postmortem example: one sealed run, explained from its own evidence.

Install via ``config.yaml -> plugins:`` with a ``host_access.evidence`` grant
(see README.md). Without the grant the service fails to start and the Gateway
reports a diagnostic; nothing else changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, PluginContribution, extension
from deerflow_extension_api.plugins import BrowserAssets

from deerflow_extension_run_postmortem.service import PostmortemService, build_actions, build_router

__all__ = ["install"]


@extension(api="0.2.11", name="run-postmortem")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register the report service, its HTTP surface and the workspace page."""
    # ``is False`` alone would silently keep the plugin on for ``enabled: 0`` or
    # ``enabled: "false"``; a mistyped off switch must fail the deployment.
    enabled = config.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError(f"run-postmortem: config.enabled must be a boolean, got {enabled!r}")
    if not enabled:
        return

    service = PostmortemService()
    registry.service(service)
    registry.routers((build_router(service),))
    contribution = PluginContribution(
        namespace="community.run-postmortem",
        title="运行复盘 / Run postmortem",
        description="把一次已封存运行的事件证据整理成结论、异常清单与时间线，并可下载 Markdown 报告。",
        enabled=enabled,
        frontend=BrowserAssets("run-postmortem.v1", Path(__file__).resolve().parent),
        backend=build_actions(service),
    )
    registry.plugin(contribution)


_entry_point: ExtensionInstall = install
