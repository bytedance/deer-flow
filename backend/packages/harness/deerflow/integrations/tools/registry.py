"""Tool registry for integration layer.

Manages tool instances and provides them to agents for external system access.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deerflow.integrations.config import IntegrationsConfig
from deerflow.integrations.registry import IntegrationRegistry
from deerflow.integrations.routing import CapabilityRouter
from deerflow.integrations.services import (
    AssessmentService,
    AssetService,
    CrmService,
    ErpService,
    MonitoringService,
    XsyService,
)
from deerflow.integrations.tools.assessment_tools import AssessmentTools
from deerflow.integrations.tools.asset_tools import AssetTools
from deerflow.integrations.tools.crm_tools import CrmTools
from deerflow.integrations.tools.erp_tools import ErpTools
from deerflow.integrations.tools.monitoring_tools import MonitoringTools
from deerflow.integrations.tools.xsy_tools import XsyTools

if TYPE_CHECKING:
    from deerflow.integrations.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for integration tools.

    Manages tool instances and provides access to tools by capability.
    Tools are created lazily on first access.
    """

    def __init__(
        self,
        config: IntegrationsConfig,
        registry: IntegrationRegistry,
        router: CapabilityRouter,
    ) -> None:
        self._config = config
        self._registry = registry
        self._router = router
        self._tools: dict[str, Any] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the tool registry.

        Creates service instances and tool wrappers.
        """
        if self._initialized:
            return

        logger.info("Initializing tool registry...")

        # Create service instances
        asset_service = AssetService(self._router)
        monitoring_service = MonitoringService(self._router)
        assessment_service = AssessmentService(self._router)
        crm_service = CrmService(self._router)
        erp_service = ErpService(self._router)
        xsy_service = XsyService(self._router)

        # Create tool wrappers
        self._tools["asset"] = AssetTools(asset_service)
        self._tools["monitoring"] = MonitoringTools(monitoring_service)
        self._tools["assessment"] = AssessmentTools(assessment_service)
        self._tools["crm"] = CrmTools(crm_service)
        self._tools["erp"] = ErpTools(erp_service)
        self._tools["xsy"] = XsyTools(xsy_service)

        self._initialized = True
        logger.info("Tool registry initialized with %d tool groups", len(self._tools))

    def get_tool(self, tool_group: str) -> Any | None:
        """Get a tool group by name.

        Args:
            tool_group: Tool group name (asset/monitoring/assessment)

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_group)

    def list_tools(self) -> list[str]:
        """List all available tool groups.

        Returns:
            List of tool group names
        """
        return list(self._tools.keys())

    def get_all_tools(self) -> dict[str, Any]:
        """Get all tool instances.

        Returns:
            Dictionary mapping tool group names to tool instances
        """
        return self._tools.copy()

    async def shutdown(self) -> None:
        """Shutdown the tool registry.

        Cleans up resources if needed.
        """
        logger.info("Shutting down tool registry...")
        self._tools.clear()
        self._initialized = False


# Global tool registry instance
_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry | None:
    """Get the global tool registry instance.

    Returns:
        ToolRegistry instance or None if not initialized
    """
    return _tool_registry


def initialize_tool_registry(
    config: IntegrationsConfig,
    registry: IntegrationRegistry,
    router: CapabilityRouter,
) -> ToolRegistry:
    """Initialize the global tool registry.

    Args:
        config: Integration configuration
        registry: Integration adapter registry
        router: Capability router

    Returns:
        Initialized ToolRegistry instance
    """
    global _tool_registry
    _tool_registry = ToolRegistry(config, registry, router)
    return _tool_registry
