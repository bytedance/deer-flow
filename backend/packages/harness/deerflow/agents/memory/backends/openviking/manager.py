"""Public OpenViking backend selector with a compatibility bridge."""

from __future__ import annotations

import logging
from typing import Any, Literal

from deerflow.agents.memory.manager import MemoryManager

from .adapter import OpenVikingAdapterMemoryManager
from .openviking_manager import LegacyOpenVikingMemoryManager
from .settings import is_legacy_openviking_config

logger = logging.getLogger(__name__)


class OpenVikingMemoryManager(OpenVikingAdapterMemoryManager):
    """Select the credential-bound adapter or an explicitly legacy config."""

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
                "OpenViking custom-HTTP configuration is deprecated. Migrate to a credential-bound USER API key, add owner_user_id, and remove legacy auth, connection-pool, and injection-query fields.",
            )
            return LegacyOpenVikingMemoryManager.from_config(
                backend_config,
                mode=mode,
                **host_hooks,
            )
        if "owner_user_id" not in (backend_config or {}):
            raise ValueError("OpenViking owner_user_id is required for the official adapter. Add owner_user_id and use a USER API key, or temporarily select the deprecated legacy adapter by setting auth_mode: trusted explicitly.")
        return super().from_config(
            backend_config,
            mode=mode,
            **host_hooks,
        )


__all__ = [
    "LegacyOpenVikingMemoryManager",
    "OpenVikingAdapterMemoryManager",
    "OpenVikingMemoryManager",
]
