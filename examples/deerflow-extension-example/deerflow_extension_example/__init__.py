"""A compact, standalone DeerFlow extension exercising every contribution kind."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_extension_example.plugin import (
    ExampleMiddlewareContributor,
    ExampleService,
    ExampleSystemObserver,
    ExampleTaskLifecycle,
    build_router,
)

__all__ = ["install"]


@extension(api="0.1.2", name="example")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register one example of each supported contribution kind."""
    if config.get("enabled", True) is False:
        return

    service = ExampleService()
    registry.middlewares(ExampleMiddlewareContributor())
    registry.task_lifecycle(ExampleTaskLifecycle())
    registry.system_model_observer(ExampleSystemObserver())
    registry.service(service)
    registry.routers((build_router(service),))


_entry_point: ExtensionInstall = install
