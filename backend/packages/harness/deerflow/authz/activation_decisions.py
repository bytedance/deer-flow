"""Typed carrier for per-step ``skill:activate`` decisions (async hooks).

The async middleware hooks precompute ``skill:activate`` decisions on the
event loop with ``aauthorize()`` and hand them to the blocking handlers that
run in worker threads. Before this type existed the carrier was a plain
``dict | None``: ``None`` meant "sync chain — the synchronous ``authorize()``
is the correct API", and a name *missing* from a non-None map silently fell
back to the same synchronous call from the thread — the wrong API for
loop-affine providers, and under ``fail_closed: false`` a provider error
there flips a denial into an allow.

Four review rounds on #4541 traced four instances of that miss (wrong keys,
failed prepass, snapshot divergence, a consumer the prepass did not cover).
This type makes the contract construction-enforced instead of
caller-disciplined:

- ``None`` (absent) — sync chain; consumers call the synchronous
  ``skill_activation_allowed`` as before.
- :class:`ActivationDecisions` (present) — an async batch. A name it covers
  returns the batched decision; a name it does NOT cover fails per the
  configured provider-error policy with a loud log and **never** calls a
  provider synchronously.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


class ActivationDecisions:
    """A per-model-step batch of ``skill:activate`` decisions.

    ``fail_closed`` carries the provider-error policy from the resolved
    authorization context so a miss resolves exactly like a provider error
    would (deny when fail-closed, allow when fail-open) — the difference
    being that a miss is always a wiring bug, so it is logged loudly at
    WARNING instead of silently shaping an allow/deny.
    """

    __slots__ = ("_decisions", "_fail_closed")

    def __init__(self, decisions: Mapping[str, bool], *, fail_closed: bool) -> None:
        self._decisions = dict(decisions)
        self._fail_closed = bool(fail_closed)

    @property
    def fail_closed(self) -> bool:
        return self._fail_closed

    def __contains__(self, name: str) -> bool:
        return name in self._decisions

    def __len__(self) -> int:
        return len(self._decisions)

    def decision_for(self, name: str) -> bool:
        """The batched decision for *name*; a miss fails per policy, loudly.

        A miss means the prepass failed to cover a name its consumer
        resolved — a construction bug, not a policy question. It resolves
        like a provider error (fail-closed denies, fail-open allows) and
        logs at WARNING so the divergence is visible in production logs
        instead of silently exercising the wrong API.
        """
        try:
            return self._decisions[name]
        except KeyError:
            logger.warning(
                "skill:activate decision for '%s' missing from the async batch; failing %s (prepass/consumer divergence — not a policy denial)",
                name,
                "closed (denied)" if self._fail_closed else "open (allowed)",
            )
            return not self._fail_closed

    def get_or_none(self, name: str) -> bool | None:
        """The batched decision, or ``None`` when *name* is not covered.

        For publishers that must distinguish "covered" from "miss" (e.g. the
        rendered-reminder publication treats an uncovered path as hide).
        """
        return self._decisions.get(name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ActivationDecisions({self._decisions!r}, fail_closed={self._fail_closed!r})"
