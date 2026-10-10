"""Superfast Decision Gate package (shadow mode, off by default).

Concept and reference implementation by Andrea Bruno, released under CC BY 4.0.
See the harness-superfast white paper for the full design. The decision models
(Von, OpenJev, Laya) are third-party open models; only the integration
architecture and the routing method here are ours.
"""

from deerflow.superfast.decision_gate import (
    SuperfastDecisionGateMiddleware,
    classify_turn,
    derive_route,
    is_enabled,
    query_system_one,
)

__all__ = [
    "SuperfastDecisionGateMiddleware",
    "classify_turn",
    "derive_route",
    "is_enabled",
    "query_system_one",
]
