"""Config-declared agent middleware loading."""

import logging
from typing import TYPE_CHECKING, Any, Literal

from langchain.agents.middleware import AgentMiddleware

from deerflow.config.extensions_config import ConfiguredMiddlewareSpec
from deerflow.reflection import resolve_class

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def _middleware_spec(entry: str | ConfiguredMiddlewareSpec | dict[str, Any]) -> ConfiguredMiddlewareSpec:
    """Normalize and validate a config entry before scope selection."""
    if isinstance(entry, str):
        return ConfiguredMiddlewareSpec(class_path=entry)
    if isinstance(entry, ConfiguredMiddlewareSpec):
        return entry
    return ConfiguredMiddlewareSpec.model_validate(entry)


def load_configured_extension_middlewares(app_config: "AppConfig", *, scope: Literal["lead", "subagent"]) -> list[AgentMiddleware]:
    """Instantiate config-declared agent middlewares.

    Each entry is a ``module.path:ClassName`` string or a
    ``ConfiguredMiddlewareSpec`` (``class`` plus optional ``kwargs`` and
    ``apply_to``). The host must explicitly supply the concrete chain scope.
    Excluded entries are not imported or constructed.
    Import, attribute, and subclass validation intentionally go through the
    shared reflection resolver so failures carry the same actionable
    dependency hints as models, tools, sandbox providers, and guardrail
    providers. Constructor errors fail loudly at agent creation.
    """
    if scope not in ("lead", "subagent"):
        raise ValueError("middleware scope must be 'lead' or 'subagent'")
    middlewares: list[AgentMiddleware] = []
    for entry in list(app_config.extensions.middlewares or []):
        spec = _middleware_spec(entry)
        if spec.apply_to not in ("both", scope):
            continue
        middleware_cls = resolve_class(spec.class_path, AgentMiddleware)
        try:
            middleware = middleware_cls(**dict(spec.kwargs))
        except Exception:
            logger.exception("Failed to instantiate configured extension middleware %s", spec.class_path)
            raise
        middlewares.append(middleware)
    return middlewares
