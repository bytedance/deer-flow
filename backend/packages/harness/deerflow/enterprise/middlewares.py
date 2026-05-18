"""Enterprise agent-middleware composition.

M0 placeholder: returns an empty list regardless of configuration. The
actual ``AuditMiddleware`` (M2-6) and any future agent-layer enterprise
middlewares will be appended here once the relevant sub-packages land.

Wired into the lead agent via
``deerflow.agents.lead_agent.agent._build_middlewares(custom_middlewares=...)``
through ``_make_lead_agent``. When ``enterprise.enabled=False`` (default),
the factory short-circuits and returns ``[]`` so callers can unconditionally
extend the middleware chain without paying any cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.enterprise.config import EnterpriseConfig

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware


def get_enterprise_middlewares(config: EnterpriseConfig) -> list[AgentMiddleware]:
    """Build the enterprise agent-middleware chain for the current config.

    Returns an empty list in M0; M2 will append :class:`AuditMiddleware`
    when ``config.audit.enabled`` is true.

    Args:
        config: The resolved :class:`EnterpriseConfig` from ``AppConfig``.

    Returns:
        Ordered list of :class:`AgentMiddleware` instances ready to be
        injected before :class:`ClarificationMiddleware`. Empty when
        ``config.enabled`` is false.
    """
    middlewares: list[AgentMiddleware] = []
    if not config.enabled:
        return middlewares

    # M2-6 placeholder: append AuditMiddleware here once landed.
    # if config.audit.enabled:
    #     from deerflow.enterprise.audit.middleware import AuditMiddleware
    #     middlewares.append(AuditMiddleware(config.audit))

    return middlewares


__all__ = ["get_enterprise_middlewares"]
