"""Config-declared agent middleware loading."""

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware

from deerflow.config.extensions_config import ConfiguredMiddlewareSpec
from deerflow.reflection import resolve_class

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def _middleware_constructor_args(entry: str | ConfiguredMiddlewareSpec | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return ``(class_path, kwargs)`` for one config entry."""
    if isinstance(entry, str):
        return entry, {}
    if isinstance(entry, ConfiguredMiddlewareSpec):
        return entry.class_path, dict(entry.kwargs)
    parsed = ConfiguredMiddlewareSpec.model_validate(entry)
    return parsed.class_path, dict(parsed.kwargs)


def load_configured_extension_middlewares(app_config: "AppConfig") -> list[AgentMiddleware]:
    """Instantiate config-declared agent middlewares.

    Each entry is a ``module.path:ClassName`` string or a
    ``ConfiguredMiddlewareSpec`` (``class`` plus optional ``kwargs``).
    Import, attribute, and subclass validation intentionally go through the
    shared reflection resolver so failures carry the same actionable
    dependency hints as models, tools, sandbox providers, and guardrail
    providers. Constructor errors fail loudly at agent creation.
    """
    middlewares: list[AgentMiddleware] = []
    for entry in list(app_config.extensions.middlewares or []):
        class_path, kwargs = _middleware_constructor_args(entry)
        middleware_cls = resolve_class(class_path, AgentMiddleware)
        try:
            middleware = middleware_cls(**kwargs)
        except Exception:
            logger.exception("Failed to instantiate configured extension middleware %s", class_path)
            raise
        middlewares.append(middleware)
    return middlewares
