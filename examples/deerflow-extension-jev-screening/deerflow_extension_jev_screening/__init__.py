"""Advisory screening of fetched content, contributed through the extension API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from deerflow_extension_api import AgentBuildContext, AgentScope, ExtensionData, ExtensionInstall, ExtensionRegistry, MiddlewarePlacement, Placement, extension

from .screener import Options, ScreeningMiddleware

__all__ = ["ScreeningMiddleware", "install"]


class _Contributor:
    def __init__(self, options: Options) -> None:
        self._options = options

    def contribute_middlewares(self, app_store: ExtensionData, ctx: AgentBuildContext) -> Sequence[MiddlewarePlacement]:
        # TOOL_VISIBLE is outer of the host's truncation, sanitization, PII
        # redaction and error wrapping: the excerpt is what the model sees.
        return (MiddlewarePlacement(ScreeningMiddleware(self._options), Placement.TOOL_VISIBLE, AgentScope.BOTH),)


@extension(api="0.2.3", name="jev-screening")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Contribute the screening middleware once the operator opts in.

    ``enabled: true`` in the private configuration is also the consent to send
    excerpts to the configured TypeSafe endpoint, so the default contributes
    nothing. Invalid settings raise, which the loader reports as a diagnostic.
    """
    options = Options.model_validate(dict(config))
    if not options.enabled:
        return
    registry.middlewares(_Contributor(options))


_entry_point: ExtensionInstall = install
