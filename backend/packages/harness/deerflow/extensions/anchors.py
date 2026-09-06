"""Translating semantic placements into concrete stack indices.

This is the only module that knows the shape of DeerFlow's middleware stack.
Restructuring the stack means updating the anchor table here; extensions,
which declare only what they need to observe, stay untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_Side = Literal[
    "outer",
    "inner",
    "outer_last",
    "inner_last",
    "inner_last_after",
    "start",
    "end",
]


@dataclass(frozen=True)
class AnchorRule:
    """One attempt at locating an insertion index.

    ``side`` "outer"/"inner" position relative to the first middleware whose
    type is in ``types``; "outer_last"/"inner_last" use the last matching
    middleware; "inner_last_after" additionally requires that match to follow
    the last middleware in ``after_types``. "start"/"end" are the absolute
    ends of the stack and ignore ``types``.
    """

    side: _Side
    types: tuple[type, ...] = ()
    after_types: tuple[type, ...] = ()

    def resolve(self, middlewares: Sequence[object]) -> int | None:
        if self.side == "start":
            return 0
        if self.side == "end":
            return len(middlewares)
        if self.side in {"outer_last", "inner_last"}:
            for index in range(len(middlewares) - 1, -1, -1):
                if isinstance(middlewares[index], self.types):
                    return index if self.side == "outer_last" else index + 1
            return None
        if self.side == "inner_last_after":
            boundary = next(
                (index for index in range(len(middlewares) - 1, -1, -1) if isinstance(middlewares[index], self.after_types)),
                None,
            )
            if boundary is None:
                return None
            for index in range(len(middlewares) - 1, boundary, -1):
                if isinstance(middlewares[index], self.types):
                    return index + 1
            return None
        for index, middleware in enumerate(middlewares):
            if isinstance(middleware, self.types):
                return index if self.side == "outer" else index + 1
        return None


@dataclass(frozen=True)
class PlacementAnchor:
    """An ordered fallback chain of anchor rules."""

    chain: tuple[AnchorRule, ...]

    @classmethod
    def of(cls, *anchors: PlacementAnchor) -> PlacementAnchor:
        """Concatenate anchors into one fallback chain."""
        rules: list[AnchorRule] = []
        for anchor in anchors:
            rules.extend(anchor.chain)
        return cls(tuple(rules))

    def resolve(self, middlewares: Sequence[object]) -> tuple[int, bool]:
        """Return (index, used_primary_rule).

        ``used_primary_rule`` is False when the first rule did not match, which
        the caller reports as a diagnostic — a silently degraded placement
        changes what the extension observes with no signal.
        """
        for position, rule in enumerate(self.chain):
            index = rule.resolve(middlewares)
            if index is not None:
                return index, position == 0
        return len(middlewares), False


def outer_of(*types: type) -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("outer", types),))


def inner_of(*types: type) -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("inner", types),))


def inner_of_last(*types: type) -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("inner_last", types),))


def inner_of_last_after(*types: type, after: tuple[type, ...]) -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("inner_last_after", types, after),))


def outer_of_last(*types: type) -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("outer_last", types),))


def outermost() -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("start"),))


def innermost() -> PlacementAnchor:
    return PlacementAnchor((AnchorRule("end"),))
