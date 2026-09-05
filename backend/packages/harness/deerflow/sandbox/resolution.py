"""Resolve a sandbox that the executing context has declared.

Upstream resolves a tool's sandbox from checkpointed state and the execution
lease. An embedding runtime may instead *declare* the sandbox an execution
must use: a prewarmed container handed to a run, a fenced handle over a
container the runtime provisioned and will release itself, or an in-memory
double in tests. The declaration's carrier is the embedder's business (a
context variable, a registry keyed by the running task); this module only asks
it. When no resolver is installed, or the resolver answers ``None``, the
sandbox middleware and tools take their ordinary path unchanged.

A declared sandbox is resolved before state and before the provider, and the
declaring runtime owns its release: the sandbox middleware binds the declared
id into state for downstream tools and never acquires or releases on its
behalf. The ``sandbox:execute`` authorization gate still applies.
"""

from __future__ import annotations

from collections.abc import Callable

from deerflow.sandbox.sandbox import Sandbox

SandboxResolver = Callable[[], Sandbox | None]

_resolver: SandboxResolver | None = None


def set_sandbox_resolver(resolver: SandboxResolver | None) -> None:
    """Install the process-wide resolver, or remove it with ``None``."""
    global _resolver
    _resolver = resolver


def resolve_declared_sandbox() -> Sandbox | None:
    """The sandbox the executing context declared, or ``None`` when it declared none."""
    resolver = _resolver
    if resolver is None:
        return None
    return resolver()
