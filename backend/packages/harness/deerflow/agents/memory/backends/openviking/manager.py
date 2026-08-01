"""Public OpenViking backend selector with a compatibility bridge."""

from __future__ import annotations

import logging
from typing import Any, Literal

from deerflow.agents.memory.manager import MemoryManager

from .official_config import is_legacy_openviking_config
from .official_manager import OfficialOpenVikingMemoryManager
from .openviking_manager import LegacyOpenVikingMemoryManager

logger = logging.getLogger(__name__)


class OpenVikingMemoryManager(OfficialOpenVikingMemoryManager):
    """Select the official adapter path unless an old config requests legacy auth."""

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> MemoryManager:
        if is_legacy_openviking_config(backend_config):
            logger.warning(
                "OpenViking custom-HTTP trusted/dev configuration is deprecated. Migrate to a credential-bound USER API key and remove legacy auth, connection-pool, and injection-query fields.",
            )
            return LegacyOpenVikingMemoryManager.from_config(
                backend_config,
                mode=mode,
                **host_hooks,
            )
        return super().from_config(
            backend_config,
            mode=mode,
            **host_hooks,
        )


__all__ = [
    "LegacyOpenVikingMemoryManager",
    "OfficialOpenVikingMemoryManager",
    "OpenVikingMemoryManager",
]
