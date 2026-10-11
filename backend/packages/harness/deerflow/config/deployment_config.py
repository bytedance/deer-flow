"""Deployment topology declaration for the Gateway startup safety gates.

``GATEWAY_WORKERS`` / ``WEB_CONCURRENCY`` only count the uvicorn workers of one
process tree. A Kubernetes Deployment with ``replicas > 1`` runs one worker per
Pod, so every Pod reports a single worker and the multi-process safety gate in
``app/gateway/deps.py`` stays inert -- while each Pod's startup orphan
reconciliation still treats the other Pods' lease-less runs as crashed.

This module is the explicit declaration that closes that gap: an operator (or
deploy tooling such as a Helm chart, which can export the env variable from
its replica count) states that more than one Gateway instance shares the
database, and the gate then enforces the same prerequisites it enforces for
``GATEWAY_WORKERS > 1``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Environment override for ``deployment.multi_instance``, so deploy tooling can
#: set the declaration from its replica count instead of editing config.yaml.
MULTI_INSTANCE_ENV_VAR = "DEER_FLOW_MULTI_INSTANCE"

_FALSY = frozenset({"", "0", "false", "no", "off"})


class DeploymentConfig(BaseModel):
    """Operator-declared deployment topology."""

    multi_instance: bool = Field(
        default=False,
        description=(
            "Declare that more than one Gateway instance (uvicorn worker, container, or Kubernetes Pod) shares this database. "
            "GATEWAY_WORKERS counts only one process tree, so replicas > 1 with one worker per Pod are invisible to the startup "
            "safety gate without this flag. When true, startup requires database.backend='postgres', run_events.backend='db', "
            "run_ownership.heartbeat_enabled=true, and a Redis stream bridge; it refuses an explicit memory sandbox ownership store, "
            "process-local browser tools, and an enabled scheduler without scheduler.multi_instance. "
            "DEER_FLOW_MULTI_INSTANCE=1 declares the same thing from the environment."
        ),
    )


@dataclass(frozen=True)
class MultiInstanceDeclaration:
    """An explicit multi-instance declaration and the knob that made it.

    Callers branch on ``source`` and compose messages from ``knob`` and
    ``rollback``; the display text is never the thing to inspect.
    """

    source: Literal["env", "config"]
    value: str

    @property
    def knob(self) -> str:
        """The setting as the operator spelled it, for refusal and warning text."""
        if self.source == "env":
            return f"{MULTI_INSTANCE_ENV_VAR}={self.value}"
        return "deployment.multi_instance=true"

    @property
    def rollback(self) -> str:
        """The one step that withdraws this declaration, as a lower-case imperative."""
        if self.source == "env":
            return f"unset {MULTI_INSTANCE_ENV_VAR}"
        return "set deployment.multi_instance=false"

    def __str__(self) -> str:
        return self.knob


def multi_instance_declared_by_env() -> str | None:
    """Return the ``DEER_FLOW_MULTI_INSTANCE`` value when it declares a multi-instance deployment.

    Blank, ``0``, ``false``, ``no`` and ``off`` mean "not declared", so a
    templated ``DEER_FLOW_MULTI_INSTANCE=false`` stays inert. Every other value
    is a declaration: a typo in this variable must fail closed (run the gate)
    rather than silently disable it.
    """
    raw = os.environ.get(MULTI_INSTANCE_ENV_VAR)
    if raw is None:
        return None
    value = raw.strip()
    if value.lower() in _FALSY:
        return None
    return value


def multi_instance_declaration(config: Any) -> MultiInstanceDeclaration | None:
    """Return the explicit multi-instance declaration in effect, or ``None``.

    The environment is consulted first because deploy tooling that sets it
    knows the actual topology; ``deployment.multi_instance`` in config.yaml is
    the operator's manual spelling. The result carries the knob that made the
    declaration so a refusal message tells the operator what to change.
    """
    env_value = multi_instance_declared_by_env()
    if env_value is not None:
        return MultiInstanceDeclaration(source="env", value=env_value)
    deployment = getattr(config, "deployment", None)
    if bool(getattr(deployment, "multi_instance", False)):
        return MultiInstanceDeclaration(source="config", value="true")
    return None
