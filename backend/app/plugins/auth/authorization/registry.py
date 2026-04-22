"""Registry/build helpers for default authorization evaluators."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.plugins.auth.authorization.authorization import PolicyEvaluator


PolicyChainBuilder = Callable[[], tuple["PolicyEvaluator", ...]]


def build_default_policy_evaluators() -> tuple["PolicyEvaluator", ...]:
    """Return the default policy chain for auth-plugin authorization."""

    from app.plugins.auth.authorization.authorization import evaluate_owner_policy

    return (evaluate_owner_policy,)


__all__ = ["PolicyChainBuilder", "build_default_policy_evaluators"]
