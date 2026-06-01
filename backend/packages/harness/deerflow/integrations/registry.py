"""Integration adapter registry.

Manages adapter lifecycle, health checks, and capability routing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from deerflow.integrations.config import IntegrationsConfig

if TYPE_CHECKING:
    from deerflow.integrations.adapters.base import IntegrationAdapter
    from deerflow.integrations.adapters.base import HealthStatus

logger = logging.getLogger(__name__)


class IntegrationRegistry:
    """Singleton registry for all integration adapters."""

    _instance: IntegrationRegistry | None = None
    _initialized: bool = False

    def __new__(cls) -> IntegrationRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._adapters: dict[str, IntegrationAdapter] = {}
        self._health_status: dict[str, HealthStatus] = {}
        self._health_check_task: asyncio.Task | None = None
        self._initialized = True

    def register(self, adapter: IntegrationAdapter) -> None:
        """Register an adapter."""
        self._adapters[adapter.system_key] = adapter
        logger.info("Registered adapter: %s (type=%s)", adapter.system_key, adapter.system_type)

    def get(self, system_key: str) -> IntegrationAdapter | None:
        """Get adapter by system key."""
        return self._adapters.get(system_key)

    def get_for_type(self, system_type: str) -> list[IntegrationAdapter]:
        """Get all adapters of a specific type."""
        return [a for a in self._adapters.values() if a.system_type == system_type]

    def list_all(self) -> list[IntegrationAdapter]:
        """List all registered adapters."""
        return list(self._adapters.values())

    async def initialize_all(self) -> None:
        """Initialize all adapters with error isolation."""
        if not self._adapters:
            logger.info("No adapters to initialize")
            return

        async def init_adapter(adapter: IntegrationAdapter) -> tuple[str, Exception | None]:
            try:
                await adapter.initialize()
                logger.info("Initialized adapter: %s", adapter.system_key)
                return adapter.system_key, None
            except Exception as e:
                logger.error(
                    "Failed to initialize adapter %s: %s",
                    adapter.system_key,
                    e,
                    exc_info=True,
                )
                return adapter.system_key, e

        results = await asyncio.gather(
            *[init_adapter(a) for a in self._adapters.values()]
        )

        failed = [key for key, err in results if err is not None]
        if failed:
            logger.warning("Failed to initialize adapters: %s", failed)

    async def shutdown_all(self) -> None:
        """Shutdown all adapters in reverse registration order."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        for adapter in reversed(list(self._adapters.values())):
            try:
                await adapter.shutdown()
                logger.info("Shutdown adapter: %s", adapter.system_key)
            except Exception as e:
                logger.error(
                    "Error shutting down adapter %s: %s",
                    adapter.system_key,
                    e,
                    exc_info=True,
                )

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """Run health checks on all adapters."""
        from deerflow.integrations.adapters.base import HealthStatus

        if not self._adapters:
            return {}

        async def check_adapter(adapter: IntegrationAdapter) -> tuple[str, HealthStatus]:
            try:
                status = await adapter.health_check()
                return adapter.system_key, status
            except Exception as e:
                logger.error(
                    "Health check failed for %s: %s",
                    adapter.system_key,
                    e,
                )
                return adapter.system_key, HealthStatus(
                    healthy=False,
                    latency_ms=None,
                    message=str(e),
                    checked_at=asyncio.get_event_loop().time(),
                )

        results = await asyncio.gather(
            *[check_adapter(a) for a in self._adapters.values()]
        )

        self._health_status = dict(results)
        return self._health_status

    def get_health_status(self, system_key: str) -> HealthStatus | None:
        """Get cached health status for a system."""
        return self._health_status.get(system_key)

    async def _health_check_loop(self, interval: float = 60.0) -> None:
        """Background health check loop."""
        while True:
            try:
                await asyncio.sleep(interval)
                await self.health_check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check loop error: %s", e, exc_info=True)

    def start_health_check_scheduler(self, interval: float = 60.0) -> None:
        """Start background health check scheduler."""
        if self._health_check_task is not None:
            return
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(interval)
        )
        logger.info("Started health check scheduler (interval=%ss)", interval)


def get_integration_registry() -> IntegrationRegistry:
    """Get the singleton integration registry."""
    return IntegrationRegistry()


def initialize_registry(config: IntegrationsConfig | None) -> IntegrationRegistry:
    """Initialize registry from config.

    Instantiates adapters for all enabled systems.
    """
    registry = get_integration_registry()

    if config is None or not config.enabled:
        logger.info("Integrations disabled")
        return registry

    from deerflow.integrations.adapters.crm import CrmAdapter
    from deerflow.integrations.adapters.erp import ErpAdapter
    from deerflow.integrations.adapters.ins import InsAdapter
    from deerflow.integrations.adapters.sms import SmsAdapter
    from deerflow.integrations.adapters.workbench import WorkbenchAdapter
    from deerflow.integrations.adapters.xsy import XsyAdapter

    adapter_factories = {
        "ins": InsAdapter,
        "sms": SmsAdapter,
        "crm": CrmAdapter,
        "erp": ErpAdapter,
        "workbench": WorkbenchAdapter,
        "xsy": XsyAdapter,
    }

    for system_key, system_config in config.systems.items():
        if not system_config.enabled:
            logger.info("Skipping disabled system: %s", system_key)
            continue

        factory = adapter_factories.get(system_config.system_type)
        if factory is None:
            logger.warning(
                "No adapter factory for system_type=%s (system=%s)",
                system_config.system_type,
                system_key,
            )
            continue

        try:
            adapter = factory(system_config)
            registry.register(adapter)
        except Exception as e:
            logger.error(
                "Failed to create adapter for %s: %s",
                system_key,
                e,
                exc_info=True,
            )

    return registry
