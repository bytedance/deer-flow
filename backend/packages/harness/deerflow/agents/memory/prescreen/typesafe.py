"""TypeSafe (Jev) memory pre-screen: one ``noul`` question per batch, judged off the turn path.

This is a **cost gate**. It answers "is this batch worth paying for an extraction
call?" and can only ever save a call — it gates no execution and no write, and
every failure mode extracts as usual (design L2). The direction is therefore the
opposite of the tool gate: there, a high probability denies; here, a probability
**below** ``skip_threshold`` skips (design §2.5).

What this adapter owns: the state (the formatted batch, nothing else), the
question and its rubric, ``skip_threshold``, the failure direction, its own
``digest``-keyed cache, and the audit policy for the served model version.
Transport, authentication, retry, the deadline budget and response validation are
the shared client's (``deerflow.typesafe``).
"""

from __future__ import annotations

from collections.abc import Mapping

from deerflow.agents.memory.judging import AnswerCache, CachedVerdict, conversation_tail_state
from deerflow.agents.memory.prescreen.contract import (
    CONFIGURATION_SOURCE,
    MODE_SHADOW,
    MODES,
    VERDICT_EXTRACT,
    VERDICT_SKIP,
    MemoryPrescreenDecision,
    MemoryPrescreenRequest,
)
from deerflow.typesafe.client import QUESTION_NOUL, Answer, Question, TransportFactory, TypeSafeClient, recordable_model
from deerflow.typesafe.connection import TypeSafeConnection, resolve_connection, typesafe_defaults
from deerflow.typesafe.errors import TypeSafeError
from deerflow.typesafe.validation import criteria_entry, defaulted_text, finite_float, whole_number

QUESTION_ID = "memory_worth_keeping"

_DEFAULT_INSTRUCTIONS = "Does this conversation contain durable, cross-task, user-level information that should be extracted into long-term memory? Judge the text alone."
_DEFAULT_CRITERIA_TRUE = (
    "Any of: a durable identity fact (role, profession, background); a long-term preference, working style or stable constraint; "
    "a long-term goal; a durable decision or working pattern that stays useful across unrelated tasks; an explicit correction of "
    "existing user-level information. These take precedence over the false criteria."
)
_DEFAULT_CRITERIA_FALSE = (
    "Task-local progress, status or next steps; greetings, acknowledgments and restatements of what was already said; process chatter "
    "about the current file, PR, thread or tool run; approval of the current result only; nothing new relative to what the user already stated."
)

DEFAULT_SKIP_THRESHOLD = 0.2
DEFAULT_MAX_STATE_CHARS = 6000


class TypeSafeMemoryPrescreen:
    """Skip the extraction call when a batch's durable-value probability is below ``skip_threshold``.

    ``mode`` is recorded for the policy identity but does not change this class's
    behaviour: the mode decides how a verdict is *consumed* (shadow records it,
    enforce acts on it) and that decision belongs to the caller (design §2.2.4).
    """

    name = "typesafe"
    policy_id = "deerflow.memory.prescreen.typesafe"
    policy_version = "1.0.0"

    def __init__(
        self,
        *,
        mode: str = MODE_SHADOW,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        skip_threshold: float = DEFAULT_SKIP_THRESHOLD,
        instructions: str | None = None,
        criteria: dict[object, object] | None = None,
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
            raise ValueError(f"memory.prescreen.mode must be one of {list(MODES)}, got {mode!r}")
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
        self.skip_threshold = finite_float("skip_threshold", skip_threshold, minimum=0.0, maximum=1.0)
        self._instructions = defaulted_text("instructions", instructions, _DEFAULT_INSTRUCTIONS)
        self._criteria_true = defaulted_text("criteria.true", criteria_entry(criteria, True), _DEFAULT_CRITERIA_TRUE)
        self._criteria_false = defaulted_text("criteria.false", criteria_entry(criteria, False), _DEFAULT_CRITERIA_FALSE)
        self.max_state_chars = whole_number("max_state_chars", max_state_chars, minimum=1)
        self.cache_size = whole_number("cache_size", cache_size, minimum=0)
        self.cache_ttl_seconds = finite_float("cache_ttl_seconds", cache_ttl_seconds, minimum=0.0)
        self._questions: dict[str, Question] = {
            QUESTION_ID: Question(
                type=QUESTION_NOUL,
                instructions=self._instructions,
                criteria={"true": self._criteria_true, "false": self._criteria_false},
            )
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

    def interpret(self, answers: Mapping[str, Answer], *, model: str, cached: bool) -> MemoryPrescreenDecision | None:
        """Map validated answers to a verdict, or ``None`` when this batch has no opinion.

        A question-level failure is "no opinion", never an error: the caller
        extracts as usual (L2).
        """
        answer = answers.get(QUESTION_ID)
        probability = getattr(answer, "probability", None)
        if not isinstance(probability, float):
            return None
        verdict = VERDICT_SKIP if probability < self.skip_threshold else VERDICT_EXTRACT
        reason = f"{verdict}: p={probability!r} {'<' if verdict == VERDICT_SKIP else '>='} skip_threshold={self.skip_threshold!r}"
        return MemoryPrescreenDecision(verdict=verdict, probability=probability, model=recordable_model(model), cached=cached, reason=reason)

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare behaviour-affecting parameters for assembly identity (never the key)."""
        from deerflow_extension_api import canonical_hash

        return {
            "mode": self._mode,
            **self._connection.public_parameters(),
            "skip_threshold": self.skip_threshold,
            "instructions_hash": canonical_hash(self._instructions),
            "criteria": {"true": self._criteria_true, "false": self._criteria_false},
            "max_state_chars": self.max_state_chars,
            "cache_size": self.cache_size,
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }

    # --- the contract's standalone entry point ----------------------------

    def decide(self, request: MemoryPrescreenRequest) -> MemoryPrescreenDecision | None:
        """Judge one batch with this side's own cache (the single-side path).

        Used when this side is the only one enabled, or when the deployment
        cannot combine requests. Never raises for a request-level failure — that
        is L2's "extract as usual".
        """
        cached = self._cache.get(request.digest)
        if cached is not None:
            return self.interpret(cached.answers, model=cached.model_for(self._questions), cached=True)
        try:
            answer_set = self._client.ask(conversation_tail_state(request.batch_text), self._questions)
        except TypeSafeError:
            return None
        decision = self.interpret(answer_set.answers, model=answer_set.model, cached=False)
        if decision is not None:
            self._cache.put(request.digest, CachedVerdict(answers=dict(answer_set.answers), models={question_id: answer_set.model for question_id in answer_set.answers}))
        return decision


__all__ = ["DEFAULT_MAX_STATE_CHARS", "DEFAULT_SKIP_THRESHOLD", "QUESTION_ID", "TypeSafeMemoryPrescreen"]
