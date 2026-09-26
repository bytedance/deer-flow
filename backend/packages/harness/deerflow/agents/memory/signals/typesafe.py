"""TypeSafe (Jev) signal classifier: two ``noul`` questions, additive hints only.

Two independent questions per batch — does the text **explicitly endorse** a
previously stated user-level preference/constraint/approach, and does it
**explicitly reject or reverse** one — mapped to the deterministic labels
``reinforcement`` / ``correction`` (design §5).

What this adapter owns: the two questions and their rubrics, ``hint_threshold``,
the label mapping, its own ``digest``-keyed cache, and the audit policy for the
served model version. It never decides extraction and never drives deletion.
"""

from __future__ import annotations

from collections.abc import Mapping

from deerflow.agents.memory.judging import AnswerCache, CachedVerdict, conversation_tail_state
from deerflow.agents.memory.signals.contract import (
    CONFIGURATION_SOURCE,
    LABEL_CORRECTION,
    LABEL_REINFORCEMENT,
    MODE_SHADOW,
    MODES,
    MemorySignalDecision,
    MemorySignalRequest,
    direction_labels,
)
from deerflow.typesafe.client import QUESTION_NOUL, Answer, Question, TransportFactory, TypeSafeClient, recordable_model
from deerflow.typesafe.connection import TypeSafeConnection, resolve_connection, typesafe_defaults
from deerflow.typesafe.errors import TypeSafeError
from deerflow.typesafe.validation import criteria_entry, defaulted_text, finite_float, whole_number

QUESTION_AFFIRMATION = "signal_affirmation"
QUESTION_NEGATION = "signal_negation"

_DEFAULT_AFFIRMATION_INSTRUCTIONS = "Does this conversation explicitly endorse a user-level preference, constraint or approach that the user stated earlier? Judge the text alone."
_DEFAULT_AFFIRMATION_TRUE = 'The text explicitly endorses something the user previously asked for (for example "keep using X", "that approach is right, keep it up").'
_DEFAULT_AFFIRMATION_FALSE = "No explicit endorsement of a previously stated user-level preference, constraint or approach — approval of the current task, result or file does not count."

_DEFAULT_NEGATION_INSTRUCTIONS = "Does this conversation explicitly reject or reverse a user-level preference, constraint or approach that the user stated earlier? Judge the text alone."
_DEFAULT_NEGATION_TRUE = 'The text explicitly rejects or reverses something the user previously asked for (for example "stop using X", "no, do it the other way").'
_DEFAULT_NEGATION_FALSE = "No explicit rejection or reversal of a previously stated user-level preference, constraint or approach — criticism of the current task, result or file does not count."

DEFAULT_HINT_THRESHOLD = 0.5
DEFAULT_MAX_STATE_CHARS = 6000


class TypeSafeSignalClassifier:
    """Turn a batch's affirmation / negation probabilities into hint labels.

    ``mode`` is recorded for the policy identity but does not change this class's
    behaviour: the mode decides whether labels are consumed, recorded only, or
    ignored (design §2.2.4).
    """

    name = "typesafe"
    policy_id = "deerflow.memory.signals.typesafe"
    policy_version = "1.0.0"

    def __init__(
        self,
        *,
        mode: str = MODE_SHADOW,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        hint_threshold: float = DEFAULT_HINT_THRESHOLD,
        instructions: Mapping[str, object] | None = None,
        criteria: Mapping[str, Mapping[object, object]] | None = None,
        max_state_chars: int = DEFAULT_MAX_STATE_CHARS,
        timeout: float | None = None,
        deadline_seconds: float | None = None,
        max_attempts: int | None = None,
        retry_backoff: float | None = None,
        cache_size: int = 256,
        cache_ttl_seconds: float = 300.0,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"memory.signal_classification.mode must be one of {list(MODES)}, got {mode!r}")
        self._mode = mode
        connection: TypeSafeConnection = resolve_connection(
            settings={
                "api_key": api_key,
                "api_key_env": api_key_env,
                "base_url": base_url,
                "model": model,
                "timeout": timeout,
                "deadline_seconds": deadline_seconds,
                "max_attempts": max_attempts,
                "retry_backoff": retry_backoff,
            },
            defaults=typesafe_defaults(),
            configuration_source=CONFIGURATION_SOURCE,
        )
        self._connection = connection
        self._client = TypeSafeClient(connection, transport_factory=transport_factory)
        self.hint_threshold = finite_float("hint_threshold", hint_threshold, minimum=0.0, maximum=1.0)
        affirmation_criteria = _side_criteria(criteria, QUESTION_AFFIRMATION)
        negation_criteria = _side_criteria(criteria, QUESTION_NEGATION)
        self._affirmation = _QuestionText(
            instructions=defaulted_text(f"{QUESTION_AFFIRMATION}.instructions", _instructions(instructions, QUESTION_AFFIRMATION), _DEFAULT_AFFIRMATION_INSTRUCTIONS),
            true=defaulted_text(f"{QUESTION_AFFIRMATION}.criteria.true", criteria_entry(affirmation_criteria, True), _DEFAULT_AFFIRMATION_TRUE),
            false=defaulted_text(f"{QUESTION_AFFIRMATION}.criteria.false", criteria_entry(affirmation_criteria, False), _DEFAULT_AFFIRMATION_FALSE),
        )
        self._negation = _QuestionText(
            instructions=defaulted_text(f"{QUESTION_NEGATION}.instructions", _instructions(instructions, QUESTION_NEGATION), _DEFAULT_NEGATION_INSTRUCTIONS),
            true=defaulted_text(f"{QUESTION_NEGATION}.criteria.true", criteria_entry(negation_criteria, True), _DEFAULT_NEGATION_TRUE),
            false=defaulted_text(f"{QUESTION_NEGATION}.criteria.false", criteria_entry(negation_criteria, False), _DEFAULT_NEGATION_FALSE),
        )
        self.max_state_chars = whole_number("max_state_chars", max_state_chars, minimum=1)
        self.cache_size = whole_number("cache_size", cache_size, minimum=0)
        self.cache_ttl_seconds = finite_float("cache_ttl_seconds", cache_ttl_seconds, minimum=0.0)
        self._questions: dict[str, Question] = {
            QUESTION_AFFIRMATION: Question(type=QUESTION_NOUL, instructions=self._affirmation.instructions, criteria={"true": self._affirmation.true, "false": self._affirmation.false}),
            QUESTION_NEGATION: Question(type=QUESTION_NOUL, instructions=self._negation.instructions, criteria={"true": self._negation.true, "false": self._negation.false}),
        }
        self._cache = AnswerCache(size=self.cache_size, ttl_seconds=self.cache_ttl_seconds)

    # --- side interface (shared with the coordinator) ---------------------

    def questions(self) -> Mapping[str, Question]:
        """The questions this side asks. The batch is added by :meth:`ask`/the coordinator."""
        return self._questions

    def ask(self, batch_text: str, questions: Mapping[str, Question]):
        """Send ``questions`` about ``batch_text`` through this side's client."""
        return self._client.ask(conversation_tail_state(batch_text), questions)

    def sharing_key(self, **dimensions: object) -> str:
        """Internal sharing identity (credential fingerprint, connection, limits, cache)."""
        return self._client.sharing_key(**dimensions)

    def interpret(self, answers: Mapping[str, Answer], *, model: str, cached: bool) -> MemorySignalDecision | None:
        """Map validated answers to hint labels, or ``None`` when neither direction is usable.

        A direction with no validated answer contributes nothing while the other
        direction in the same response is still used (per question, never per
        side — S7/S18).
        """
        affirmation = _probability(answers.get(QUESTION_AFFIRMATION))
        negation = _probability(answers.get(QUESTION_NEGATION))
        if affirmation is None and negation is None:
            return None
        probabilities: dict[str, float] = {}
        if affirmation is not None:
            probabilities[LABEL_REINFORCEMENT] = affirmation
        if negation is not None:
            probabilities[LABEL_CORRECTION] = negation
        return MemorySignalDecision(
            labels=direction_labels(affirmation, negation, hint_threshold=self.hint_threshold),
            probabilities=probabilities,
            model=recordable_model(model),
            cached=cached,
        )

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare behaviour-affecting parameters for assembly identity (never the key)."""
        from deerflow_extension_api import canonical_hash

        return {
            "mode": self._mode,
            **self._connection.public_parameters(),
            "hint_threshold": self.hint_threshold,
            "affirmation": {"instructions_hash": canonical_hash(self._affirmation.instructions), "criteria": {"true": self._affirmation.true, "false": self._affirmation.false}},
            "negation": {"instructions_hash": canonical_hash(self._negation.instructions), "criteria": {"true": self._negation.true, "false": self._negation.false}},
            "max_state_chars": self.max_state_chars,
            "cache_size": self.cache_size,
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }

    # --- the contract's standalone entry point ----------------------------

    def decide(self, request: MemorySignalRequest) -> MemorySignalDecision | None:
        """Classify one batch with this side's own cache (the single-side path).

        Never raises for a request-level failure: no model result is the
        documented fallback to the deterministic signals (S2).

        A bucket is per question, never per side (§2.2.6 / S18): holding one
        direction must not count as a full hit, so this round sends the missing
        direction and merges its answer into the same bucket. A whole-request
        failure yields no result for this round.
        """
        cached = self._cache.get(request.digest)
        answers: dict[str, Answer] = dict(cached.answers) if cached is not None else {}
        models: dict[str, str] = dict(cached.models) if cached is not None else {}
        missing = {question_id: question for question_id, question in self._questions.items() if question_id not in answers}
        if not missing:
            assert cached is not None
            return self.interpret(answers, model=cached.model_for(self._questions), cached=True)
        try:
            answer_set = self._client.ask(conversation_tail_state(request.batch_text), missing)
        except TypeSafeError:
            return None
        answers.update(answer_set.answers)
        models.update({question_id: answer_set.model for question_id in answer_set.answers})
        if answer_set.answers:
            self._cache.put(request.digest, CachedVerdict(answers=dict(answers), models=dict(models)))
            # A validated answer arrived this round, so the verdict includes a
            # network sample and reports the model that served it.
            return self.interpret(answers, model=answer_set.model, cached=False)
        # Nothing new was validated: the verdict (if any) rests on the answers the
        # bucket already held, so it reports their model. A retry that returned no
        # valid answers supplied none of the consumed evidence.
        return self.interpret(answers, model=cached.model_for(self._questions) if cached is not None else "", cached=True)


class _QuestionText:
    """One question's configurable text."""

    __slots__ = ("false", "instructions", "true")

    def __init__(self, *, instructions: str, true: str, false: str) -> None:
        self.instructions = instructions
        self.true = true
        self.false = false


def _instructions(instructions: Mapping[str, object] | None, question_id: str) -> object:
    """Look up one question's instruction override, keyed by question id or direction name."""
    if instructions is None:
        return None
    entry = instructions.get(question_id)
    if isinstance(entry, Mapping):
        return entry.get("instructions")
    return entry


def _side_criteria(criteria: Mapping[str, Mapping[object, object]] | None, question_id: str) -> Mapping[object, object] | None:
    if criteria is None:
        return None
    if not isinstance(criteria, Mapping):
        raise ValueError("criteria must be a mapping of question id -> {true, false}")
    entry = criteria.get(question_id)
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise ValueError(f"criteria.{question_id} must be a mapping with optional 'true'/'false' entries")
    return entry


def _probability(answer: Answer | None) -> float | None:
    probability = getattr(answer, "probability", None)
    return probability if isinstance(probability, float) else None


__all__ = ["DEFAULT_HINT_THRESHOLD", "DEFAULT_MAX_STATE_CHARS", "QUESTION_AFFIRMATION", "QUESTION_NEGATION", "TypeSafeSignalClassifier"]
