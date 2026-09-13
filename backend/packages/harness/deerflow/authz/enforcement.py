"""Shared Phase 1B authorization enforcement helpers."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from langchain_core.tools import BaseTool

from deerflow.authz.provider import AuthorizationProvider, Principal

logger = logging.getLogger(__name__)


class _Named(Protocol):
    """Minimal protocol for resources identified by a ``name`` attribute."""

    name: str


def filter_tools_by_authorization(
    tools: Sequence[BaseTool],
    *,
    provider: AuthorizationProvider | None,
    principal: Principal,
    fail_closed: bool,
) -> list[BaseTool]:
    """Return the policy-visible subset of *tools* without changing its order.

    The caller must invoke this before deferred-tool assembly. Provider errors
    and malformed filter results deny every tool when ``fail_closed`` is true;
    an explicitly configured fail-open policy preserves the original set.
    """
    original_tools = list(tools)
    if provider is None:
        return original_tools

    candidates = [tool.name for tool in original_tools]
    try:
        allowed = provider.filter_resources(principal, "tool", candidates)
        if not isinstance(allowed, list) or any(not isinstance(name, str) for name in allowed):
            raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
    except Exception:
        logger.exception("Authorization provider failed while filtering tools")
        return [] if fail_closed else original_tools

    allowed_names = set(allowed)
    return [tool for tool in original_tools if tool.name in allowed_names]


def filter_resources_by_authorization(
    resources: Sequence[_Named],
    *,
    resource_type: str,
    provider: AuthorizationProvider | None,
    principal: Principal,
    fail_closed: bool,
) -> list[_Named]:
    """Return the policy-visible subset of *resources* without changing order.

    Generic batch filter for any resource identified by a ``name`` attribute
    (skills, models, etc.). Mirrors ``filter_tools_by_authorization`` but is
    not coupled to ``BaseTool``. Provider errors and malformed filter results
    deny every resource when ``fail_closed`` is true; an explicitly configured
    fail-open policy preserves the original set.
    """
    original = list(resources)
    if provider is None:
        return original

    candidates = [r.name for r in original]
    try:
        allowed = provider.filter_resources(principal, resource_type, candidates)
        if not isinstance(allowed, list) or any(not isinstance(name, str) for name in allowed):
            raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
    except Exception:
        logger.exception("Authorization provider failed while filtering %s", resource_type)
        return [] if fail_closed else original

    allowed_names = set(allowed)
    return [r for r in original if r.name in allowed_names]
