"""The shared TypeSafe (Jev) transport client: one request, one answer set.

What this layer owns — transport and lifecycle, authentication, retry and
backoff, the deadline budget, response parsing and the error taxonomy, UTF-8 wire
size counting, and the request skeleton (design §2.1).

What it deliberately does **not** own (design §2.2): state content, the
questions, criteria and thresholds, the failure policy that turns a failure into a
denial or a fallback, cache semantics, and business audit. Those stay in each
adapter, which is why this module has no branch that knows what a "risky tool
call" or a "memory worth keeping" is.

Consequences worth keeping in mind when editing:

* **Clients live for exactly one evaluation.** The framework has no provider
  lifecycle hook, and httpx closes an injected transport when its client closes,
  so a shared transport instance would be dead on the second evaluation.
  ``transport_factory`` is a factory, called once per network-needing evaluation
  and closed together with the client it was handed to. There is no connection
  pool here (design §3.3).
* **Timeouts are budgets, not guarantees.** The async path cancels the in-flight
  request through ``asyncio.timeout``. The sync path cannot preempt a blocking
  call, so it checks the deadline after the response headers, around the body
  read, and again after parsing — and drops a result that arrived late instead of
  adopting it.
* **A question-level failure is data, not an exception** (design §2.3). One
  malformed answer must not discard the other valid answers in the same response;
  the consumer decides what "no result for this question" means.
* **Wire size is a counting capability only** (design §2.4). No consumer's limit
  unit moves because this module exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from deerflow.typesafe.connection import TypeSafeConnection
from deerflow.typesafe.errors import (
    CAUSE_DEADLINE,
    CAUSE_HTTP_STATUS,
    CAUSE_INVALID_RESPONSE,
    CAUSE_TRANSPORT,
    TypeSafeError,
)

QUESTION_NOUL = "noul"
QUESTION_CHOICE = "choice"
_QUESTION_TYPES = (QUESTION_NOUL, QUESTION_CHOICE)

CATEGORY_MISSING = "missing"
CATEGORY_TYPE = "type"
CATEGORY_PROBABILITY = "probability"
CATEGORY_LABEL = "label"

_OK_STATUS = 200
_UNAUTHORIZED_STATUS = 401
_RETRYABLE_STATUS_CODES = frozenset({429, 529})

#: A callable returning a fresh transport, because httpx closes the transport it
#: was given when its client closes.
type TransportFactory = Callable[[], httpx.BaseTransport | httpx.AsyncBaseTransport]


def wire_size(value: object) -> int:
    """Return the bytes ``httpx`` would send for ``json=value``: compact UTF-8 JSON.

    A counting capability, not a limit (design §2.4). Characters and UTF-8 bytes
    differ — one CJK character is three bytes — so a consumer that swapped its
    existing character limit for this number would move its own fallback boundary.

    Unlike ``json.dumps`` defaults this uses ``ensure_ascii=False`` and compact
    separators, matching httpx exactly, and ``allow_nan=False``, matching httpx's
    rejection of ``NaN``/``Infinity``. A value httpx cannot send therefore raises
    here too, rather than reporting a size that no request would have.
    """
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


# The served ``model`` is the one response value every consumer records, and from
# there it reaches reason messages, audit records, logs and reports. Only a token
# of this shape is recorded as itself; anything else is recorded as a digest. See
# ``recordable_model``.
_MODEL_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}\Z")
_DIGEST_CHARS = 16


def recordable_model(model: str) -> str:
    """Return the served model token, or a digest when it is not safe to record.

    ``model`` is response content. A malformed or hostile endpoint can put an
    echoed batch of conversation text, injected instructions or a multi-megabyte
    string there, so only a token matching ``_MODEL_TOKEN`` is recorded verbatim.
    Anything else keeps a stable, bounded provenance record instead of being
    echoed, without discarding a verdict that is otherwise usable: rejecting the
    response would turn a cosmetic server quirk into a lost verdict.
    """
    if _MODEL_TOKEN.match(model):
        return model
    # surrogatepass: json.loads produces lone surrogates for escaped input, and a
    # plain UTF-8 encode would raise on them where this must not fail.
    digest = hashlib.sha256(model.encode("utf-8", "surrogatepass")).hexdigest()[:_DIGEST_CHARS]
    return f"unrecorded:sha256:{digest}"


@dataclass(frozen=True)
class Question:
    """One question in a request; the mapping key it is passed under is its id.

    ``criteria`` carries the answer labels for a ``choice`` question (required
    there: it is what makes a returned label valid) and the judgeable criteria for
    a ``noul`` question (optional).
    """

    type: str
    instructions: str
    criteria: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.type not in _QUESTION_TYPES:
            raise ValueError(f"question type must be one of {list(_QUESTION_TYPES)}, got {self.type!r}")
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("question instructions must be a non-empty string")
        if self.type == QUESTION_CHOICE and not self.criteria:
            raise ValueError("a choice question needs 'criteria' mapping every valid label to its description")
        if self.criteria is not None and (not isinstance(self.criteria, Mapping) or any(not isinstance(label, str) or not label or not isinstance(description, str) or not description for label, description in self.criteria.items())):
            raise ValueError("criteria must map non-empty labels to non-empty descriptions")


@dataclass(frozen=True)
class NoulAnswer:
    """A validated probability from a ``noul`` question."""

    probability: float


@dataclass(frozen=True)
class ChoiceAnswer:
    """A validated label from a ``choice`` question."""

    label: str


type Answer = NoulAnswer | ChoiceAnswer


@dataclass(frozen=True)
class QuestionError:
    """A question-level failure: the request was usable, this question's answer was not.

    ``category`` is one of ``missing``, ``type``, ``probability`` or ``label``.
    ``message`` names the problem without repeating the response body, which a
    malformed or hostile endpoint can fill with echoed state.
    """

    question_id: str
    category: str
    message: str


@dataclass(frozen=True)
class AnswerSet:
    """One response, split into envelope-level success plus per-question outcomes.

    ``answers`` holds the questions that validated; ``errors_by_question`` holds
    the ones that did not. Only the questions actually asked appear in either —
    an answer for a question this request never asked is ignored, not reported.
    """

    model: str
    answers: Mapping[str, Answer]
    errors_by_question: Mapping[str, QuestionError]

    def noul(self, question_id: str) -> NoulAnswer | None:
        """The validated ``noul`` answer for ``question_id``, or ``None`` when it failed."""
        answer = self.answers.get(question_id)
        return answer if isinstance(answer, NoulAnswer) else None


class _RetryableAttempt(TypeSafeError):
    """Internal: this attempt failed in a way another attempt may fix.

    Caught inside the retry loop and re-raised as a plain :class:`TypeSafeError`
    when the attempt budget is exhausted, so it never escapes this module.
    """


class TypeSafeClient:
    """One consumer's TypeSafe client, built from its effective connection.

    Holds no cache: cache ownership stays with each adapter, so a shared client
    never decides that two consumers' results are interchangeable (design §1.2,
    §3.1).
    """

    def __init__(self, connection: TypeSafeConnection, *, transport_factory: TransportFactory | None = None) -> None:
        self._connection = connection
        self._transport_factory = transport_factory

    @property
    def connection(self) -> TypeSafeConnection:
        """The effective connection this client was built from."""
        return self._connection

    def sharing_key(self, **dimensions: object) -> str:
        """Internal identity of "one request that could be shared" (never a credential).

        Two consumers may share a request only when every dimension here matches:
        the connection settings, the credential *fingerprint*, the
        ``transport_factory`` object, and whatever the consumer adds — its input
        limit (``max_state_chars``) and its cache settings.

        Questions, criteria and thresholds are deliberately absent: sides with
        different behaviour parameters can still share one request, while each
        consumer publishes its own policy identity separately through its
        ``release_policy_parameters()`` (design §4 rule 2).
        """
        from deerflow_extension_api import canonical_hash

        identity: dict[str, object] = {
            **self._connection.public_parameters(),
            "credential_fingerprint": self._connection.credential_fingerprint(),
            "transport_factory": _factory_identity(self._transport_factory),
            **dimensions,
        }
        return canonical_hash(identity)

    def ask(self, state: object, questions: Mapping[str, Question]) -> AnswerSet:
        """Ask ``questions`` about ``state`` and return the validated answer set.

        ``state`` is serialised by httpx, so it must be JSON-serialisable; a
        consumer whose policy is "never send an unserialisable state" validates it
        first, as the tool gate does, and answers locally instead.

        Raises :class:`TypeSafeError` for every request-level failure. A
        question-level failure is returned inside the answer set.

        Blocking: never call this from the event loop — use :meth:`aask` there.
        """
        deadline_at = time.monotonic() + self._connection.deadline_seconds
        payload = self._payload(state, questions)
        headers = self._headers()
        transport = None if self._transport_factory is None else self._transport_factory()
        with httpx.Client(timeout=self._connection.timeout, transport=transport) as client:
            for attempt in range(1, self._connection.max_attempts + 1):
                self._check_budget(deadline_at)
                try:
                    return self._attempt_sync(client, payload, headers, questions, deadline_at)
                except _RetryableAttempt as exc:
                    if attempt >= self._connection.max_attempts:
                        raise TypeSafeError(str(exc), cause=exc.cause) from exc
                    self._sleep_before_retry(attempt, deadline_at)

    async def aask(self, state: object, questions: Mapping[str, Question]) -> AnswerSet:
        """The async variant of :meth:`ask`; cancels an in-flight request at the deadline."""
        payload = self._payload(state, questions)
        headers = self._headers()
        # The cancellation scope covers the in-flight request and its body read:
        # it bounds the request duration, not the wall-clock cost of cleanup.
        try:
            async with asyncio.timeout(self._connection.deadline_seconds):
                deadline_at = time.monotonic() + self._connection.deadline_seconds
                transport = None if self._transport_factory is None else self._transport_factory()
                async with httpx.AsyncClient(timeout=self._connection.timeout, transport=transport) as client:
                    for attempt in range(1, self._connection.max_attempts + 1):
                        self._check_budget(deadline_at)
                        try:
                            return await self._attempt_async(client, payload, headers, questions, deadline_at)
                        except _RetryableAttempt as exc:
                            if attempt >= self._connection.max_attempts:
                                raise TypeSafeError(str(exc), cause=exc.cause) from exc
                            await self._async_sleep_before_retry(attempt, deadline_at)
        except TimeoutError as exc:
            # asyncio.timeout converts only the cancellation it triggered; an
            # outer CancelledError stays a CancelledError and keeps propagating.
            raise self._deadline_error() from exc

    # --- request skeleton -------------------------------------------------

    def _payload(self, state: object, questions: Mapping[str, Question]) -> dict[str, object]:
        return {
            "state": state,
            "model": self._connection.model,
            "questions": {question_id: {"type": question.type, "instructions": question.instructions, **({"criteria": dict(question.criteria)} if question.criteria else {})} for question_id, question in questions.items()},
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._connection.api_key}", "Accept": "application/json"}

    # --- transport --------------------------------------------------------

    def _attempt_sync(self, client: httpx.Client, payload: dict[str, object], headers: dict[str, str], questions: Mapping[str, Question], deadline_at: float) -> AnswerSet:
        try:
            with client.stream("POST", self._connection.url, json=payload, headers=headers) as response:
                self._check_budget(deadline_at)
                if response.status_code != _OK_STATUS:
                    raise self._status_error(response.status_code)
                self._check_budget(deadline_at)
                body = response.read()
                self._check_budget(deadline_at)
                answers = self._parse(body, questions)
                self._check_budget(deadline_at)
                return answers
        except httpx.TransportError as exc:
            # httpx.TransportError is an httpx.HTTPError subclass, so it is
            # matched first: a connection reset is worth another attempt, while a
            # request-building error is not.
            raise _RetryableAttempt(f"TypeSafe request failed: {type(exc).__name__}", cause=CAUSE_TRANSPORT) from exc
        except httpx.HTTPError as exc:
            raise TypeSafeError(f"TypeSafe request failed: {type(exc).__name__}", cause=CAUSE_TRANSPORT) from exc

    async def _attempt_async(self, client: httpx.AsyncClient, payload: dict[str, object], headers: dict[str, str], questions: Mapping[str, Question], deadline_at: float) -> AnswerSet:
        try:
            async with client.stream("POST", self._connection.url, json=payload, headers=headers) as response:
                self._check_budget(deadline_at)
                if response.status_code != _OK_STATUS:
                    raise self._status_error(response.status_code)
                self._check_budget(deadline_at)
                body = await response.aread()
                self._check_budget(deadline_at)
                answers = self._parse(body, questions)
                self._check_budget(deadline_at)
                return answers
        except httpx.TransportError as exc:
            raise _RetryableAttempt(f"TypeSafe request failed: {type(exc).__name__}", cause=CAUSE_TRANSPORT) from exc
        except httpx.HTTPError as exc:
            raise TypeSafeError(f"TypeSafe request failed: {type(exc).__name__}", cause=CAUSE_TRANSPORT) from exc

    def _status_error(self, status_code: int) -> TypeSafeError:
        # Only the numeric status is reported. The response body *and* the HTTP
        # status line are both server-controlled, TypeSafe may echo the state
        # (raw tool arguments, conversation text) in either, and this message
        # reaches middleware logs and the evaluation report.
        hint = " (check the API key configured via api_key / the API key environment variable)" if status_code == _UNAUTHORIZED_STATUS else ""
        message = f"TypeSafe returned HTTP {status_code}{hint}"
        if status_code in _RETRYABLE_STATUS_CODES:
            return _RetryableAttempt(message, cause=CAUSE_HTTP_STATUS)
        return TypeSafeError(message, cause=CAUSE_HTTP_STATUS)

    # --- response parsing -------------------------------------------------

    def _parse(self, body: bytes, questions: Mapping[str, Question]) -> AnswerSet:
        """Split one response into a usable envelope plus per-question outcomes (design §2.3)."""
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise TypeSafeError("TypeSafe response was not valid JSON", cause=CAUSE_INVALID_RESPONSE) from exc
        if not isinstance(payload, dict):
            raise TypeSafeError("TypeSafe response must be a JSON object", cause=CAUSE_INVALID_RESPONSE)
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            raise TypeSafeError("TypeSafe response is missing a non-empty 'model'", cause=CAUSE_INVALID_RESPONSE)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeError("TypeSafe response is missing an 'answers' object", cause=CAUSE_INVALID_RESPONSE)

        validated: dict[str, Answer] = {}
        errors: dict[str, QuestionError] = {}
        for question_id, question in questions.items():
            answer, error = _validate_answer(question_id, question, answers.get(question_id))
            if error is not None:
                errors[question_id] = error
            elif answer is not None:
                validated[question_id] = answer
        return AnswerSet(model=model, answers=validated, errors_by_question=errors)

    # --- deadline budget --------------------------------------------------

    def _check_budget(self, deadline_at: float) -> None:
        """Reject a result when the evaluation budget is spent, even on success."""
        if time.monotonic() >= deadline_at:
            raise self._deadline_error()

    def _deadline_error(self) -> TypeSafeError:
        return TypeSafeError(f"TypeSafe evaluation exceeded deadline_seconds={self._connection.deadline_seconds:g}", cause=CAUSE_DEADLINE)

    def _remaining(self, deadline_at: float) -> float:
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise self._deadline_error()
        return remaining

    def _sleep_before_retry(self, attempt: int, deadline_at: float) -> None:
        time.sleep(min(self._connection.retry_backoff * 2 ** (attempt - 1), self._remaining(deadline_at)))

    async def _async_sleep_before_retry(self, attempt: int, deadline_at: float) -> None:
        await asyncio.sleep(min(self._connection.retry_backoff * 2 ** (attempt - 1), self._remaining(deadline_at)))


def _validate_answer(question_id: str, question: Question, raw: object) -> tuple[Answer | None, QuestionError | None]:
    if raw is None:
        return None, QuestionError(question_id=question_id, category=CATEGORY_MISSING, message=f"TypeSafe response has no answer for question {question_id!r}")
    if not isinstance(raw, dict):
        return None, QuestionError(question_id=question_id, category=CATEGORY_TYPE, message=f"TypeSafe answer for question {question_id!r} is not an object (type={type(raw).__name__})")
    if raw.get("type") != question.type:
        # Only the type name is reported: the answer itself is response content
        # and may echo the state back into a log or the evaluation report.
        return None, QuestionError(question_id=question_id, category=CATEGORY_TYPE, message=f"TypeSafe answer for {question_id!r} is not a {question.type} answer (type={type(raw.get('type')).__name__})")
    if question.type == QUESTION_NOUL:
        return _validate_noul(question_id, raw)
    return _validate_choice(question_id, question, raw)


def _validate_noul(question_id: str, raw: dict[object, object]) -> tuple[Answer | None, QuestionError | None]:
    raw_probability = raw.get("noul")
    # bool is an int subclass, and json.loads parses NaN/Infinity literals, so both
    # are rejected here rather than reaching a consumer's comparison. Only the
    # offending type is reported, for the reason in _validate_answer.
    if isinstance(raw_probability, bool) or not isinstance(raw_probability, (int, float)):
        return None, QuestionError(question_id=question_id, category=CATEGORY_PROBABILITY, message=f"TypeSafe returned a non-numeric noul probability (type={type(raw_probability).__name__})")
    try:
        probability = float(raw_probability)
    except OverflowError:
        # A JSON integer too large for float() (e.g. 10**400) must stay a
        # per-question error: letting it escape would discard the other valid
        # answers in the same response (design §2.3).
        return None, QuestionError(question_id=question_id, category=CATEGORY_PROBABILITY, message="TypeSafe returned a noul probability outside [0, 1]")
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return None, QuestionError(question_id=question_id, category=CATEGORY_PROBABILITY, message="TypeSafe returned a noul probability outside [0, 1]")
    return NoulAnswer(probability=probability), None


def _validate_choice(question_id: str, question: Question, raw: dict[object, object]) -> tuple[Answer | None, QuestionError | None]:
    label = raw.get("choice")
    if not isinstance(label, str) or not label:
        return None, QuestionError(question_id=question_id, category=CATEGORY_LABEL, message=f"TypeSafe returned a non-textual choice label (type={type(label).__name__})")
    if question.criteria is None or label not in question.criteria:
        return None, QuestionError(question_id=question_id, category=CATEGORY_LABEL, message="TypeSafe returned a choice label outside the configured criteria")
    return ChoiceAnswer(label=label), None


def _factory_identity(factory: TransportFactory | None) -> str | None:
    """Identity of the injected transport factory, for ``sharing_key``.

    ``id()`` is process-local on purpose: sharing a request is a within-process
    decision, and merging two consumers that would use *different* transports is
    the failure this must not allow. Two distinct but equivalent factories
    therefore separate, which is the conservative direction. The factory is held
    by the client, so its address cannot be reused while the key is in use.
    """
    if factory is None:
        return None
    module = getattr(factory, "__module__", type(factory).__module__)
    qualname = getattr(factory, "__qualname__", type(factory).__qualname__)
    return f"{module}.{qualname}#{id(factory)}"


__all__ = [
    "CATEGORY_LABEL",
    "CATEGORY_MISSING",
    "CATEGORY_PROBABILITY",
    "CATEGORY_TYPE",
    "QUESTION_CHOICE",
    "QUESTION_NOUL",
    "Answer",
    "AnswerSet",
    "ChoiceAnswer",
    "NoulAnswer",
    "Question",
    "QuestionError",
    "TransportFactory",
    "TypeSafeClient",
    "recordable_model",
    "wire_size",
]
