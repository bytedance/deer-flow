"""Behaviour-affecting parameters, declared by the component that owns them.

Two runs of "the same agent" are only the same if the middleware chain enforced
the same limits, prompts, and thresholds. Reconstructing that from outside means
reading private attributes and guessing which of them change behaviour — a
guess that silently rots as middlewares gain fields.

Each middleware declares its own instead. The declaration is the contract; the
attributes behind it are free to change.

``canonical_json`` is here rather than in the host because a hash is only
comparable if both sides compute it identically, and one of those sides is an
extension released on a different schedule.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ReleasePolicyProvider(Protocol):
    def release_policy_parameters(self) -> dict[str, object]:
        """Return this component's behaviour-affecting parameters.

        Values must be JSON-serialisable. Hash long text rather than embedding
        it: a declaration is an identity, not a copy of the prompt.
        """
        return None


def canonical_json(value: object) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace.

    Raises ``TypeError`` on an unserialisable value rather than coercing it to
    ``repr``, which would make two structurally different declarations collide
    on the same address-dependent string.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _unwrap_release_policy_source(middleware: object) -> object:
    """Return the object that owns the behaviour, not an isolation wrapper.

    Extension contributions can reach the stack inside an isolation wrapper
    whose dynamically generated subclass shares one class name across every
    contributed middleware in the process — describing the wrapper would
    collapse them all into one indistinguishable, empty declaration.

    Duck-typed on ``inner`` rather than importing the wrapper type: this
    package must stay host-independent, and any future wrapper of the same
    shape is handled for free.
    """
    described = middleware
    for _ in range(4):
        inner = getattr(described, "inner", None)
        if inner is None or inner is described:
            break
        described = inner
    return described


def collect_release_policies(middlewares: Sequence[object]) -> dict[str, dict[str, object]]:
    """Gather every declaration in an assembled stack, keyed by class name.

    A middleware whose declaration raises is recorded as ``{"error": "<Type>"}``
    rather than dropped: an assembly that failed to describe itself is a
    different fact from one that had nothing to say.

    Two instances of the same class get distinct keys (``Name``, ``Name#2``,
    ...) rather than the second silently overwriting the first: a stack that
    legitimately runs the same middleware twice must not lose one instance's
    declaration.
    """
    policies: dict[str, dict[str, object]] = {}
    seen_counts: dict[str, int] = {}
    for middleware in middlewares:
        described = _unwrap_release_policy_source(middleware)
        declare = getattr(described, "release_policy_parameters", None)
        if not callable(declare):
            continue
        name = type(described).__name__
        seen_counts[name] = seen_counts.get(name, 0) + 1
        key = name if seen_counts[name] == 1 else f"{name}#{seen_counts[name]}"
        try:
            declared = declare()
        except Exception as exc:  # noqa: BLE001 - a broken declaration must not abort assembly
            logger.warning("middleware %s failed to declare release policy: %s", name, type(exc).__name__)
            policies[key] = {"error": type(exc).__name__}
            continue
        policies[key] = declared if isinstance(declared, dict) else {"error": "NonMappingDeclaration"}
    return policies
