"""Extension-facing projection of host policy.

This module is intentionally independent of Gateway router and service
plumbing: lead and subagent builders need the projection even when the
Gateway-specific contribution points are not installed.
"""

from __future__ import annotations

from typing import Any

from deerflow_extension_api import HostPolicySnapshot

_UNSET = object()


def project_host_policy(
    app_config: Any,
    *,
    token_budget_config: Any | None = None,
    max_subagents_per_run: int | None | object = _UNSET,
) -> HostPolicySnapshot:
    """Project the host's enforced limits into the public extension contract."""
    token_budget = token_budget_config if token_budget_config is not None else getattr(app_config, "token_budget", None)
    token_budget_enabled = bool(getattr(token_budget, "enabled", False))
    if max_subagents_per_run is _UNSET:
        subagents = getattr(app_config, "subagents", None)
        effective_max_subagents = getattr(subagents, "max_total_per_run", None)
    else:
        effective_max_subagents = max_subagents_per_run
    return HostPolicySnapshot(
        token_budget_enabled=token_budget_enabled,
        max_input_tokens=getattr(token_budget, "max_input_tokens", None) if token_budget_enabled else None,
        max_output_tokens=getattr(token_budget, "max_output_tokens", None) if token_budget_enabled else None,
        max_total_tokens=getattr(token_budget, "max_tokens", None) if token_budget_enabled else None,
        budget_warn_fraction=getattr(token_budget, "warn_threshold", None) if token_budget_enabled else None,
        budget_hard_fraction=getattr(token_budget, "hard_stop_threshold", None) if token_budget_enabled else None,
        max_subagents_per_run=effective_max_subagents if isinstance(effective_max_subagents, int) else None,
    )
