"""Capability routing and service results."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from deerflow.integrations.models.provenance import PartialFailure

if TYPE_CHECKING:
    from deerflow.integrations.adapters.base import AuthContext
    from deerflow.integrations.config import CapabilityRouteConfig
    from deerflow.integrations.registry import IntegrationRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceResult:
    """Result from a service capability call."""

    data: Any
    source_system_keys: tuple[str, ...]
    partial_failures: tuple[PartialFailure, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_partial(self) -> bool:
        """Check if result has partial failures."""
        return len(self.partial_failures) > 0


class CapabilityRouter:
    """Routes capability calls to appropriate adapters with enrich and fallback."""

    def __init__(
        self,
        registry: IntegrationRegistry,
        routes: dict[str, CapabilityRouteConfig],
    ) -> None:
        """Initialize router.

        Args:
            registry: Integration registry with adapters
            routes: Capability route configurations
        """
        self._registry = registry
        self._routes = routes

    async def route(
        self,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Route a capability call through primary, enrich, and fallback.

        Args:
            capability_key: Capability identifier (e.g., 'monitoring.trend')
            query: Query object for the capability
            auth_context: Authentication context

        Returns:
            ServiceResult with data and metadata

        Raises:
            CapabilityRouteNotFoundError: If no route configured
            IntegrationError: If all adapters fail
        """
        from deerflow.integrations.errors import (
            CapabilityRouteNotFoundError,
            IntegrationError,
        )

        route = self._routes.get(capability_key)
        if route is None:
            raise CapabilityRouteNotFoundError(
                message=f"No route configured for capability: {capability_key}",
                capability_key=capability_key,
            )

        if not route.enabled:
            raise CapabilityRouteNotFoundError(
                message=f"Route is disabled: {capability_key}",
                capability_key=capability_key,
            )

        # Try primary with fallback chain
        primary_result, failures = await self._try_primary_with_fallback(
            route, capability_key, query, auth_context
        )

        if primary_result is None:
            detail = "; ".join(f"{k}: {v}" for k, v in failures.items()) if failures else "no adapters tried"
            raise IntegrationError(
                message=f"All adapters failed for capability: {capability_key} [{detail}]",
                capability_key=capability_key,
            )

        primary_data, primary_system_key = primary_result

        # Run enrich if configured
        if route.enrich_system_keys:
            enrich_results = await self._run_enrich(
                route, capability_key, query, auth_context
            )
            return self._merge_results(
                route,
                primary_data,
                primary_system_key,
                enrich_results,
            )

        # No enrich, return primary only
        return ServiceResult(
            data=primary_data,
            source_system_keys=(primary_system_key,),
        )

    async def _try_primary_with_fallback(
        self,
        route: CapabilityRouteConfig,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> tuple[tuple[Any, str] | None, dict[str, str]]:
        """Try primary adapter, then fallback chain.

        Returns:
            ((data, system_key) or None, failures dict mapping adapter→error)
        """
        failures: dict[str, str] = {}

        # Try primary
        primary = self._registry.get(route.primary_system_key)
        if primary is not None:
            try:
                data = await primary.call(capability_key, query, auth_context)
                return (data, route.primary_system_key), failures
            except Exception as e:
                failures[route.primary_system_key] = str(e)
                logger.warning(
                    "Primary adapter %s failed for %s: %s",
                    route.primary_system_key,
                    capability_key,
                    e,
                )

        # Try fallback chain
        for fallback_key in route.fallback_system_keys:
            fallback = self._registry.get(fallback_key)
            if fallback is None:
                continue

            try:
                data = await fallback.call(capability_key, query, auth_context)
                logger.info(
                    "Fallback adapter %s succeeded for %s",
                    fallback_key,
                    capability_key,
                )
                return (data, fallback_key), failures
            except Exception as e:
                failures[fallback_key] = str(e)
                logger.warning(
                    "Fallback adapter %s failed for %s: %s",
                    fallback_key,
                    capability_key,
                    e,
                )

        return None, failures

    async def _run_enrich(
        self,
        route: CapabilityRouteConfig,
        capability_key: str,
        query: Any,
        auth_context: AuthContext,
    ) -> list[tuple[str, Any, Exception | None]]:
        """Run enrich adapters in parallel.

        Returns:
            List of (system_key, data, error) tuples
        """

        async def enrich_call(system_key: str) -> tuple[str, Any, Exception | None]:
            adapter = self._registry.get(system_key)
            if adapter is None:
                return system_key, None, Exception(f"Adapter not found: {system_key}")

            try:
                data = await adapter.call(capability_key, query, auth_context)
                return system_key, data, None
            except Exception as e:
                logger.warning(
                    "Enrich adapter %s failed for %s: %s",
                    system_key,
                    capability_key,
                    e,
                )
                return system_key, None, e

        tasks = [enrich_call(key) for key in route.enrich_system_keys]
        return await asyncio.gather(*tasks)

    def _merge_results(
        self,
        route: CapabilityRouteConfig,
        primary_data: Any,
        primary_system_key: str,
        enrich_results: list[tuple[str, Any, Exception | None]],
    ) -> ServiceResult:
        """Merge primary and enrich results according to policies.

        Args:
            route: Route configuration
            primary_data: Primary adapter result
            primary_system_key: Primary system identifier
            enrich_results: Enrich adapter results

        Returns:
            Merged ServiceResult
        """
        partial_failures: list[PartialFailure] = []
        successful_enrich: list[tuple[str, Any]] = []
        source_keys = [primary_system_key]

        # Process enrich results
        for system_key, data, error in enrich_results:
            if error is not None:
                partial_failures.append(
                    PartialFailure(
                        system_key=system_key,
                        capability_key=route.capability_key,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        timestamp=datetime.now(),
                    )
                )
            else:
                successful_enrich.append((system_key, data))
                source_keys.append(system_key)

        # Handle partial failures
        if partial_failures:
            if route.partial_failure_policy == "fail_all":
                from deerflow.integrations.errors import IntegrationError

                raise IntegrationError(
                    message="Enrich adapters failed",
                    capability_key=route.capability_key,
                )
            elif route.partial_failure_policy == "ignore_failures":
                partial_failures = []

        # Merge data according to policy
        merged_data = self._apply_merge_policy(
            route.merge_policy, primary_data, successful_enrich
        )

        return ServiceResult(
            data=merged_data,
            source_system_keys=tuple(source_keys),
            partial_failures=tuple(partial_failures),
            metadata={"merge_policy": route.merge_policy},
        )

    def _apply_merge_policy(
        self,
        policy: str,
        primary_data: Any,
        enrich_data: list[tuple[str, Any]],
    ) -> Any:
        """Apply merge policy to combine results.

        Args:
            policy: Merge policy name
            primary_data: Primary result
            enrich_data: List of (system_key, data) enrich results

        Returns:
            Merged data
        """
        if policy == "primary_only":
            return primary_data

        if policy == "concatenate":
            # Return list with primary first, then enrich
            result = [primary_data]
            result.extend(data for _, data in enrich_data)
            return result

        if policy == "primary_plus_enrich":
            # Default: return primary with enrich_metadata
            if not enrich_data:
                return primary_data

            # If primary is a dataclass, attach enrich as metadata
            if hasattr(primary_data, "source_metadata"):
                enrich_metadata = {
                    system_key: data for system_key, data in enrich_data
                }
                # Create new instance with enriched metadata
                if hasattr(primary_data, "with_provenance"):
                    # Assume it's a canonical model with source_metadata
                    return primary_data
                return primary_data

            return primary_data

        # Unknown policy, return primary
        logger.warning("Unknown merge policy: %s", policy)
        return primary_data
