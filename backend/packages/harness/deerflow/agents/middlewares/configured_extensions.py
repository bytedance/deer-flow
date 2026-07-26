"""Config-declared agent middleware loading."""

import logging
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware

from deerflow.reflection import resolve_class

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def load_configured_extension_middlewares(app_config: "AppConfig") -> list[AgentMiddleware]:
    """Instantiate config-declared agent middlewares.

    Each entry is a zero-argument ``AgentMiddleware`` class path in
    ``module.path:ClassName`` format. Import, attribute, and subclass validation
    intentionally go through the shared reflection resolver so failures carry
    the same actionable dependency hints as models, tools, sandbox providers,
    and guardrail providers.
    """
    middlewares: list[AgentMiddleware] = []
    for middleware_path in list(app_config.extensions.middlewares or []):
        middleware_cls = resolve_class(middleware_path, AgentMiddleware)
        try:
            middleware = middleware_cls()
        except Exception:
            logger.exception("Failed to instantiate configured extension middleware %s", middleware_path)
            raise
        middlewares.append(middleware)
    return middlewares
