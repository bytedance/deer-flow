"""Extension entry point: registers the knowledge service and its two API routers.

Referenced from ``config.yaml``'s ``plugins:`` list as
``deerflow_knowledge.install:install``; until that entry exists (and the package is
installed) the extension contributes nothing to the host.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_knowledge.routers.knowledge_bases import build_router as build_knowledge_bases_router
from deerflow_knowledge.routers.rag_config import build_router as build_rag_config_router
from deerflow_knowledge.service import KnowledgeExtensionService


@extension(api="0.2", name="knowledge")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register the knowledge service and both API routers."""
    if config.get("enabled", True) is False:
        return

    service = KnowledgeExtensionService()
    registry.service(service)
    registry.routers((build_knowledge_bases_router(service), build_rag_config_router(service)))


_entry_point: ExtensionInstall = install
