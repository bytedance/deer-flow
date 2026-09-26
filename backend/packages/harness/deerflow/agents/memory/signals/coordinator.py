"""The memory layer's judge: pre-screening and signal classification over one batch.

This is the single object the DeerMem updater calls. It exists because the two
sides must not each assemble their own request (design §2.2, sole authority):

* **Phase A — per-side eligibility.** Each side independently decides whether it
  can judge this round. The pre-screen can be ineligible for reasons the
  classifier does not share (deterministic signals, staleness/consolidation),
  while both are ineligible on the emergency-flush and shutdown-drain paths.
* **Phase B — cache and assembly.** Look the cache up under the group's sharing
  identity and this round's full logical question set, subtract what the cache
  already holds, then group: ``combine: always`` is one request,
  ``combine: never`` is one request per side, ``combine: auto`` shares only when
  every effective client setting matches. The lookup precedes phase A's narrowing
  (§2.2.3): a round in which only one side is still eligible reuses the answers the
  bucket already holds for that digest instead of asking for them again. A full
  hit sends nothing.
* **Phase C — consumption.** ``mode`` decides only what a result *means*:
  pre-screen ``shadow`` records, ``enforce`` skips; classifier ``shadow``
  records, ``hints`` merges. The one exception is the veto (design §2.2.7):
  pre-screen ``enforce`` × classifier ``hints`` × a model hint at or above
  ``hint_threshold`` extracts instead of skipping.

Failure is always additive: a side with no result contributes nothing, the other
side's validated answers in the same response are still consumed, and the caller
falls back to its deterministic behaviour (pre-screening extracts as usual; signal
classification falls back to the regex union).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from deerflow.agents.memory.judging import AnswerCache, CachedVerdict, batch_chars, batch_digest
from deerflow.agents.memory.prescreen.contract import (
    MODE_ENFORCE,
    VERDICT_SKIP,
    MemoryPrescreenDecision,
    MemoryPrescreenProvider,
)
from deerflow.agents.memory.prescreen.contract import (
    MODE_OFF as PRESCREEN_OFF,
)
from deerflow.agents.memory.signals.contract import (
    COMBINE_ALWAYS,
    COMBINE_AUTO,
    COMBINE_NEVER,
    COMBINES,
    MODE_HINTS,
    MemorySignalDecision,
    MemorySignalProvider,
)
from deerflow.agents.memory.signals.contract import (
    MODE_OFF as CLASSIFIER_OFF,
)
from deerflow.typesafe.client import Answer, AnswerSet, Question
from deerflow.typesafe.errors import TypeSafeError

REASON_DISABLED = "disabled"
REASON_DRAIN = "shutdown_drain"
REASON_EMERGENCY = "emergency_flush"
REASON_SIGNALS = "deterministic_signals"
REASON_MAINTENANCE = "staleness_or_consolidation"
REASON_OVER_LIMIT = "over_limit"
REASON_REQUEST_FAILED = "request_failed"
REASON_NO_VERDICT = "no_verdict"


@dataclass(frozen=True)
class MemoryBatchContext:
    """What the updater knows about one batch when it calls the judge."""

    batch_text: str
    digest: str
    signals: frozenset[str] = frozenset()
    staleness_review_enabled: bool = False
    consolidation_enabled: bool = False
    bypass_watermark: bool = False
    judged: bool = True
    thread_id: str | None = None
    user_id: str | None = None
    agent_name: str | None = None
    trace_id: str | None = None
    message_count: int = 0


@dataclass(frozen=True)
class MemoryBatchVerdict:
    """What the updater should do with this batch, plus the audit payload.

    ``skip`` is already the **effective** decision: a vetoed skip arrives as
    ``skip=False`` with ``vetoed_by_model_signal=True``. ``hints`` are the model's
    hint labels for the hint union (empty when the classifier is not in ``hints``
    mode or produced no usable answer).
    """

    skip: bool = False
    vetoed_by_model_signal: bool = False
    hints: frozenset[str] = field(default_factory=frozenset)
    payload: dict[str, object] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        """Whether any side actually produced a record this round."""
        return bool(self.payload)


@runtime_checkable
class CombinablePrescreen(MemoryPrescreenProvider, Protocol):
    """A pre-screen that can share a request: it exposes its questions and interpretation."""

    max_state_chars: int
    cache_size: int
    cache_ttl_seconds: float

    def questions(self) -> Mapping[str, Question]: ...

    def ask(self, batch_text: str, questions: Mapping[str, Question]) -> AnswerSet: ...

    def interpret(self, answers: Mapping[str, Answer], *, model: str, cached: bool) -> MemoryPrescreenDecision | None: ...

    def sharing_key(self, **dimensions: object) -> str: ...


@runtime_checkable
class CombinableClassifier(MemorySignalProvider, Protocol):
    """A classifier that can share a request: it exposes its questions and interpretation."""

    max_state_chars: int
    cache_size: int
    cache_ttl_seconds: float

    def questions(self) -> Mapping[str, Question]: ...

    def ask(self, batch_text: str, questions: Mapping[str, Question]) -> AnswerSet: ...

    def interpret(self, answers: Mapping[str, Answer], *, model: str, cached: bool) -> MemorySignalDecision | None: ...

    def sharing_key(self, **dimensions: object) -> str: ...


@dataclass(frozen=True)
class _Eligibility:
    eligible: bool
    reason: str | None = None


class MemorySignalCoordinator:
    """Judge one batch with the enabled sides, combining their requests when allowed."""

    def __init__(
        self,
        *,
        prescreen: MemoryPrescreenProvider | None = None,
        prescreen_mode: str = PRESCREEN_OFF,
        classifier: MemorySignalProvider | None = None,
        classifier_mode: str = CLASSIFIER_OFF,
        combine: str = COMBINE_AUTO,
    ) -> None:
        if combine not in COMBINES:
            raise ValueError(f"memory.signal_classification.combine must be one of {list(COMBINES)}, got {combine!r}")
        self._prescreen = prescreen
        self._prescreen_mode = prescreen_mode
        self._classifier = classifier
        self._classifier_mode = classifier_mode
        self._combine = combine
        self._combined = combine != COMBINE_NEVER and self._both_combinable() and self._configuration_matches()
        if combine == COMBINE_ALWAYS and self._prescreen is not None and self._classifier is not None and not self._combined:
            raise ValueError(
                "memory.signal_classification.combine='always' requires both sides to share every effective client setting "
                "(model, base_url, credential fingerprint, timeouts, retries, transport factory, max_state_chars, cache settings); "
                "use combine='auto' or align the two configs"
            )
        self._cache = AnswerCache(size=self._cache_size(), ttl_seconds=self._cache_ttl()) if self._combined else None

    # --- construction helpers --------------------------------------------

    def _both_combinable(self) -> bool:
        return isinstance(self._prescreen, CombinablePrescreen) and isinstance(self._classifier, CombinableClassifier) and self._combine != COMBINE_NEVER

    def _cache_size(self) -> int:
        return max(0, int(getattr(self._prescreen, "cache_size", 0)), int(getattr(self._classifier, "cache_size", 0)))

    def _cache_ttl(self) -> float:
        return min(float(getattr(self._prescreen, "cache_ttl_seconds", 0.0)), float(getattr(self._classifier, "cache_ttl_seconds", 0.0)))

    def _sharing_key(self, side: CombinablePrescreen | CombinableClassifier) -> str:
        """The side's sharing identity including the dimensions the transport cannot see (§2.2.5)."""
        return side.sharing_key(max_state_chars=side.max_state_chars, cache_size=side.cache_size, cache_ttl_seconds=side.cache_ttl_seconds)

    def _configuration_matches(self) -> bool:
        if not self._both_combinable():
            return False
        assert isinstance(self._prescreen, CombinablePrescreen)
        assert isinstance(self._classifier, CombinableClassifier)
        return self._sharing_key(self._prescreen) == self._sharing_key(self._classifier)

    # --- the judge -------------------------------------------------------

    def __call__(self, context: Mapping[str, object]) -> MemoryBatchVerdict:
        """Hook entry point: DeerMem hands over a plain mapping, not a host type.

        The vendored backend imports no host judging types (it uses the same
        mapping convention as ``extraction_callback``), so this adapts its payload
        to :class:`MemoryBatchContext`. The digest is derived here when the caller
        does not supply one, keeping the hashing policy in one place.
        """
        batch_text = str(context.get("batch_text") or "")
        signals = context.get("signals")
        return self.judge(
            MemoryBatchContext(
                batch_text=batch_text,
                digest=str(context.get("digest") or batch_digest(batch_text)),
                signals=frozenset(signals) if signals else frozenset(),
                staleness_review_enabled=bool(context.get("staleness_review_enabled")),
                consolidation_enabled=bool(context.get("consolidation_enabled")),
                bypass_watermark=bool(context.get("bypass_watermark")),
                judged=bool(context.get("judged", True)),
                thread_id=_optional_str(context.get("thread_id")),
                user_id=_optional_str(context.get("user_id")),
                agent_name=_optional_str(context.get("agent_name")),
                trace_id=_optional_str(context.get("trace_id")),
                message_count=int(context.get("message_count") or 0),
            )
        )

    def judge(self, context: MemoryBatchContext) -> MemoryBatchVerdict:
        """Judge one batch. Never raises for a request-level failure (locks S2 / L2).

        An ineligible side is a *fallback*, not silence: while any side is enabled
        the round still emits its record with the fallback reason (design §5's
        "local fallbacks"), so "why was this batch not judged" stays auditable. Only
        a round where every side is off produces an empty payload.
        """
        started = time.monotonic()
        batch_length = batch_chars(context.batch_text)
        prescreen_eligibility = self._prescreen_eligibility(context, batch_length)
        classifier_eligibility = self._classifier_eligibility(context, batch_length)

        if self._combined and (prescreen_eligibility.eligible or classifier_eligibility.eligible):
            prescreen_decision, classifier_decision = self._judge_combined(context, prescreen_eligibility, classifier_eligibility)
        else:
            prescreen_decision = self._decide_prescreen(context) if prescreen_eligibility.eligible else None
            classifier_decision = self._decide_classifier(context) if classifier_eligibility.eligible else None
        duration_ms = (time.monotonic() - started) * 1000

        return self._consume(
            context,
            prescreen_eligibility=prescreen_eligibility,
            classifier_eligibility=classifier_eligibility,
            prescreen_decision=prescreen_decision,
            classifier_decision=classifier_decision,
            duration_ms=duration_ms,
        )

    def _decide_prescreen(self, context: MemoryBatchContext) -> MemoryPrescreenDecision | None:
        if self._prescreen is None:
            return None
        return self._prescreen.decide(_prescreen_request(context))

    def _decide_classifier(self, context: MemoryBatchContext) -> MemorySignalDecision | None:
        if self._classifier is None:
            return None
        return self._classifier.decide(_signal_request(context))

    def _judge_combined(
        self,
        context: MemoryBatchContext,
        prescreen_eligibility: _Eligibility,
        classifier_eligibility: _Eligibility,
    ) -> tuple[MemoryPrescreenDecision | None, MemorySignalDecision | None]:
        """One shared deployment's request assembly (§2.2.3): cache first, then the missing questions.

        The bucket is keyed by the **full logical question set**, independent of what
        is sent this round, so an ineligible side costs no repeat request: its held
        answers are still found and its questions are simply not part of ``wanted``.
        """
        assert isinstance(self._prescreen, CombinablePrescreen)
        assert isinstance(self._classifier, CombinableClassifier)
        assert self._cache is not None
        logical_set = tuple(sorted({**dict(self._prescreen.questions()), **dict(self._classifier.questions())}))
        wanted: dict[str, Question] = {}
        if prescreen_eligibility.eligible:
            wanted.update(self._prescreen.questions())
        if classifier_eligibility.eligible:
            wanted.update(self._classifier.questions())
        cache_key = (self._sharing_key(self._prescreen), logical_set, context.digest)
        held = self._cache.get(cache_key)
        answers: dict[str, Answer] = dict(held.answers) if held is not None else {}
        # Per-answer model provenance: merging a later partial response must not
        # re-attribute answers already held (served by a different model) to the new
        # one, or a later full cache hit reports the wrong model for the verdict.
        models: dict[str, str] = dict(held.models) if held is not None else {}
        missing = {question_id: question for question_id, question in wanted.items() if question_id not in answers}
        # Question ids answered by the network this round. A side is a cache hit only
        # when it consumed none of them, so its ``cached`` flag — and the shadow
        # evaluation's network-sample count — tracks the answers it actually used,
        # not what the round as a whole did (S18 / per-question cache contract).
        fetched: set[str] = set()
        fetched_model: str | None = None

        if missing:
            # Either client can carry the request: a combined deployment guarantees
            # every effective setting matches, so the eligible side asks.
            asker = self._prescreen if prescreen_eligibility.eligible else self._classifier
            try:
                answer_set = asker.ask(context.batch_text, missing)
            except TypeSafeError:
                # A whole-request failure writes no bucket and yields no result for
                # either side: both fall back (S2/S7).
                return None, None
            answers.update(answer_set.answers)
            fetched = set(answer_set.answers)
            fetched_model = answer_set.model
            models.update({question_id: answer_set.model for question_id in answer_set.answers})
            if answer_set.answers:
                self._cache.put(cache_key, CachedVerdict(answers=dict(answers), models=dict(models)))

        return (
            self._interpret_side(self._prescreen, answers, fetched=fetched, fetched_model=fetched_model, bucket=held) if prescreen_eligibility.eligible else None,
            self._interpret_side(self._classifier, answers, fetched=fetched, fetched_model=fetched_model, bucket=held) if classifier_eligibility.eligible else None,
        )

    @staticmethod
    def _interpret_side(
        side: CombinablePrescreen | CombinableClassifier,
        answers: Mapping[str, Answer],
        *,
        fetched: set[str],
        fetched_model: str | None,
        bucket: CachedVerdict | None,
    ):
        """Interpret one side from per-answer provenance.

        A side is a cache hit — and reports the model that produced its answers —
        only when every question it consumes was held in the bucket. If any of its
        own questions was fetched this round, the side is a network sample and
        reports the served model. Reusing a verdict is not the same as fetching it.
        """
        if set(side.questions()) & fetched:
            return side.interpret(answers, model=fetched_model or "", cached=False)
        return side.interpret(answers, model=bucket.model_for(side.questions()) if bucket is not None else "", cached=True)

    # --- phase A ---------------------------------------------------------

    def _prescreen_eligibility(self, context: MemoryBatchContext, batch_length: int) -> _Eligibility:
        if self._prescreen is None or self._prescreen_mode == PRESCREEN_OFF:
            return _Eligibility(False, REASON_DISABLED)
        if not context.judged:
            return _Eligibility(False, REASON_DRAIN)
        if context.bypass_watermark:
            return _Eligibility(False, REASON_EMERGENCY)
        if context.signals:
            # L3: deterministic positive evidence outranks a model negative verdict.
            return _Eligibility(False, REASON_SIGNALS)
        if context.staleness_review_enabled or context.consolidation_enabled:
            # L8: a skip would also skip that batch's maintenance review.
            return _Eligibility(False, REASON_MAINTENANCE)
        if self._over_limit(self._prescreen, batch_length):
            return _Eligibility(False, REASON_OVER_LIMIT)
        return _Eligibility(True)

    def _classifier_eligibility(self, context: MemoryBatchContext, batch_length: int) -> _Eligibility:
        if self._classifier is None or self._classifier_mode == CLASSIFIER_OFF:
            return _Eligibility(False, REASON_DISABLED)
        if not context.judged:
            return _Eligibility(False, REASON_DRAIN)
        if context.bypass_watermark:
            return _Eligibility(False, REASON_EMERGENCY)
        if self._over_limit(self._classifier, batch_length):
            return _Eligibility(False, REASON_OVER_LIMIT)
        return _Eligibility(True)

    @staticmethod
    def _over_limit(side: object, batch_length: int) -> bool:
        """Each side enforces its own limit, in characters of the judged text (§2.3 / L5 / S16).

        ``max_state_chars`` is a character count over ``format_conversation_for_update``'s
        output, and the shared client's byte counting replaces no limit
        (shared-client design §2.4): a byte count would trip this fallback three
        times early on CJK text.
        """
        limit = getattr(side, "max_state_chars", None)
        return isinstance(limit, int) and batch_length > limit

    # --- phase C ---------------------------------------------------------

    def _consume(
        self,
        context: MemoryBatchContext,
        *,
        prescreen_eligibility: _Eligibility,
        classifier_eligibility: _Eligibility,
        prescreen_decision: MemoryPrescreenDecision | None,
        classifier_decision: MemorySignalDecision | None,
        duration_ms: float,
    ) -> MemoryBatchVerdict:
        payload: dict[str, object] = {}
        if (self._prescreen is not None and self._prescreen_mode != PRESCREEN_OFF) or (self._classifier is not None and self._classifier_mode != CLASSIFIER_OFF):
            payload["prescreen"] = self._prescreen_payload(context, prescreen_eligibility, prescreen_decision, duration_ms)
            payload["signal_classification"] = self._classifier_payload(context, classifier_eligibility, classifier_decision, duration_ms)

        skip = prescreen_eligibility.eligible and prescreen_decision is not None and prescreen_decision.verdict == VERDICT_SKIP and self._prescreen_mode == MODE_ENFORCE
        hints = classifier_decision.labels if (classifier_eligibility.eligible and classifier_decision is not None and self._classifier_mode == MODE_HINTS) else frozenset()
        vetoed = False
        if skip and hints:
            # §2.2.7: the only way a model verdict changes the extraction decision.
            skip = False
            vetoed = True
            payload["skip_vetoed_by_model_signal"] = True
        return MemoryBatchVerdict(skip=skip, vetoed_by_model_signal=vetoed, hints=frozenset(hints), payload=payload)

    def _prescreen_payload(self, context: MemoryBatchContext, eligibility: _Eligibility, decision: MemoryPrescreenDecision | None, duration_ms: float) -> dict[str, object] | None:
        if self._prescreen is None or self._prescreen_mode == PRESCREEN_OFF:
            return None
        return {
            "mode": self._prescreen_mode,
            "verdict": decision.verdict if decision is not None else None,
            "probability": decision.probability if decision is not None else None,
            "skip_threshold": getattr(self._prescreen, "skip_threshold", None),
            "model": decision.model if decision is not None else None,
            "cached": decision.cached if decision is not None else None,
            "digest": context.digest,
            "signals": sorted(context.signals),
            "message_count": context.message_count,
            "batch_chars": len(context.batch_text),
            "duration_ms": duration_ms,
            "fallback_reason": None if decision is not None else (eligibility.reason or REASON_NO_VERDICT),
        }

    def _classifier_payload(self, context: MemoryBatchContext, eligibility: _Eligibility, decision: MemorySignalDecision | None, duration_ms: float) -> dict[str, object] | None:
        if self._classifier is None or self._classifier_mode == CLASSIFIER_OFF:
            return None
        return {
            "mode": self._classifier_mode,
            "labels": sorted(decision.labels) if decision is not None else [],
            "probabilities": dict(decision.probabilities) if decision is not None else {},
            "model": decision.model if decision is not None else None,
            "cached": decision.cached if decision is not None else None,
            "digest": context.digest,
            # The deterministic set is recorded on both sides' records: the two
            # channels must stay separately auditable even when only one side is on.
            "signals": sorted(context.signals),
            "duration_ms": duration_ms,
            "fallback_reason": None if decision is not None else (eligibility.reason or REASON_NO_VERDICT),
        }

    # --- identity --------------------------------------------------------

    def release_policy_parameters(self) -> dict[str, object]:
        """Both sides' policy identities plus the combination policy (never a credential)."""
        return {
            "combine": self._combine,
            "combined": self._combined,
            "prescreen": self._prescreen.release_policy_parameters() if self._prescreen is not None else None,
            "signal_classification": self._classifier.release_policy_parameters() if self._classifier is not None else None,
        }


def _optional_str(value: object) -> str | None:
    """Identity fields arrive as ``None`` or text; anything else is dropped rather than stringified."""
    return value if isinstance(value, str) and value else None


def _prescreen_request(context: MemoryBatchContext):
    from deerflow.agents.memory.prescreen.contract import MemoryPrescreenRequest

    return MemoryPrescreenRequest(
        batch_text=context.batch_text,
        digest=context.digest,
        signals=context.signals,
        thread_id=context.thread_id,
        user_id=context.user_id,
        agent_name=context.agent_name,
        trace_id=context.trace_id,
        bypass_watermark=context.bypass_watermark,
        message_count=context.message_count,
    )


def _signal_request(context: MemoryBatchContext):
    from deerflow.agents.memory.signals.contract import MemorySignalRequest

    return MemorySignalRequest(
        batch_text=context.batch_text,
        digest=context.digest,
        signals=context.signals,
        thread_id=context.thread_id,
        user_id=context.user_id,
        agent_name=context.agent_name,
        trace_id=context.trace_id,
        bypass_watermark=context.bypass_watermark,
        message_count=context.message_count,
    )


def build_memory_judge(config=None) -> MemorySignalCoordinator | None:
    """Build the memory layer's judge from the host memory config, or ``None`` when every side is off.

    Callers inject the result into a backend as the ``judge`` host hook; ``None``
    means "no judging configured", which leaves the extraction path byte-identical
    to a deployment without this feature (L1/S1).
    """
    from deerflow.agents.memory.prescreen.contract import resolve_memory_prescreen
    from deerflow.agents.memory.signals.contract import resolve_memory_signal_classifier

    if config is None:
        from deerflow.config.memory_config import get_memory_config

        config = get_memory_config()
    prescreen_config = config.prescreen
    signal_config = config.signal_classification
    prescreen = resolve_memory_prescreen(mode=prescreen_config.mode, use=prescreen_config.use, config=prescreen_config.config)
    classifier = resolve_memory_signal_classifier(mode=signal_config.mode, use=signal_config.use, config=signal_config.config)
    if prescreen is None and classifier is None:
        return None
    return MemorySignalCoordinator(
        prescreen=prescreen,
        prescreen_mode=prescreen_config.mode,
        classifier=classifier,
        classifier_mode=signal_config.mode,
        combine=signal_config.combine,
    )


__all__ = [
    "CombinableClassifier",
    "CombinablePrescreen",
    "MemoryBatchContext",
    "MemoryBatchVerdict",
    "MemorySignalCoordinator",
    "build_memory_judge",
]
