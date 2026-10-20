"""OpenAI Decisions transport: DeerFlow's question set spoken as one ``/v1/decisions`` request.

Issue #7005 asked for a second decision backend behind the interfaces the TypeSafe (Jev)
integration already uses, not a new decision system. The provider slots
(``guardrails.provider.use``, ``memory.prescreen.use``, ``memory.signal_classification.use``)
already resolve a class path and hand it the consumer's ``config``, so a new backend is a
sibling adapter and the workflows, thresholds and failure directions stay where they are.

Ownership follows `deerflow.typesafe`: this module owns the wire — endpoint, envelope, how a
question is encoded, how an answer is validated, and the error taxonomy — and nothing else.
Thresholds, rubrics, caches and the direction a failure takes stay in each adapter, so the
memory pre-screen still means "skip the extraction call" here exactly as it means there.
Transport itself (authentication, retry, backoff, the deadline budget, the bounded and
never-decoded body read) is inherited unchanged from
:class:`~deerflow.typesafe.client.TypeSafeClient`; re-declaring it in a second module would put
those security properties where they can drift.

Two differences are structural, and the mapping below exists because of them:

* **``input`` is the judged text, not a state object.** Jev takes a ``state`` mapping whose
  shape each consumer owns. Here the consumer decides the same thing through its
  ``_judge_state`` hook, so nothing in this module knows what a tool call or a conversation
  batch is.
* **A ``predicate`` question has no field for the two criteria.** A ``noul`` question's
  ``criteria`` say when the answer is true and when it is false; the Decisions endpoint only
  carries ``instructions``. Folding them into the instruction text keeps one rubric per
  question instead of silently dropping half of it, which would move the decision boundary
  while the adapter went on reporting the same ``criteria`` in its policy identity.

A refusal is an *answer* on this endpoint (``{"type": "refusal"}``), not an HTTP failure.
It therefore becomes a question-level :class:`~deerflow.typesafe.client.QuestionError` — the
same channel a malformed answer uses — so the gate denies for want of a verdict while the
memory paths carry on, which is each consumer's existing policy rather than a new branch.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from deerflow.typesafe.client import (
    CATEGORY_MISSING,
    CATEGORY_TYPE,
    Answer,
    AnswerSet,
    Question,
    QuestionError,
    TypeSafeClient,
    validate_choice_label,
    validate_probability,
)
from deerflow.typesafe.connection import TypeSafeConnection, resolve_connection
from deerflow.typesafe.errors import CAUSE_INVALID_RESPONSE, TypeSafeError

DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
ENDPOINT_PATH = "/v1/decisions"

#: The Decisions spelling of a bounded yes/no judgement, which is what ``noul`` asks for.
QUESTION_PREDICATE = "predicate"
QUESTION_CHOICE = "choice"

#: ``refusal`` is a value of an answer's ``type``, so it is a per-question outcome.
ANSWER_TYPE_REFUSAL = "refusal"
CATEGORY_REFUSAL = "refusal"


def provider_defaults() -> dict[str, object]:
    """The fallback layer this backend passes to ``resolve_connection``.

    ``model`` is deliberately blank rather than a model id. Which decision model answers is an
    operator choice with a cost and a data-handling implication, and a checked-in default would
    send conversation and tool text to a model nobody selected. The resolver rejects a blank
    model at construction, so a deployment naming this backend has to name a model too.
    """
    return {"base_url": DEFAULT_BASE_URL, "api_key_env": DEFAULT_API_KEY_ENV, "model": ""}


def resolve_decisions_connection(*, settings: Mapping[str, object] | None = None, defaults: Mapping[str, object] | None = None, configuration_source: str) -> TypeSafeConnection:
    """Resolve a connection that speaks this endpoint, or raise at construction.

    One owner pairs the provider's defaults with its request path: a "Decisions" connection
    resolved without ``ENDPOINT_PATH`` would post to the other service's URL, and nothing but a
    live request would say so. ``defaults`` is layered *over* the provider's own defaults, which
    are in turn overridden by ``settings`` — the precedence each adapter already documents.
    """
    return resolve_connection(
        settings=settings,
        defaults={**provider_defaults(), **(defaults or {})},
        configuration_source=configuration_source,
        endpoint_path=ENDPOINT_PATH,
        provider_label="OpenAI Decisions",
    )


class OpenAIDecisionsClient(TypeSafeClient):
    """One consumer's Decisions client, built from its effective connection.

    Inherits the whole transport lifecycle; overrides only the request skeleton and the
    response parsing, which are the parts that are protocol-specific.
    """

    #: ``noul``/System One wording in an inherited message would attribute a decision to the
    #: wrong service, and these messages reach logs, denial reasons and the evaluation report.
    provider_label = "OpenAI Decisions"

    def _payload(self, state: object, questions: Mapping[str, Question]) -> dict[str, object]:
        return {
            "model": self._connection.model,
            "input": state,
            "questions": [encode_question(question_id, question) for question_id, question in questions.items()],
        }

    def _parse(self, body: bytes, questions: Mapping[str, Question]) -> AnswerSet:
        """Split one response into an envelope plus per-question outcomes, as ``typesafe`` does."""
        try:
            payload = json.loads(body)
        # ``RecursionError`` and not ``ValueError`` is what deep nesting raises, and it must stay
        # inside this taxonomy: a hostile or broken endpoint must not escape as an unrelated
        # exception, which the consumer would lose the round's record over.
        except (ValueError, RecursionError) as exc:
            raise TypeSafeError(f"{self.provider_label} response was not valid JSON", cause=CAUSE_INVALID_RESPONSE) from exc
        if not isinstance(payload, dict):
            raise TypeSafeError(f"{self.provider_label} response must be a JSON object", cause=CAUSE_INVALID_RESPONSE)
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, list):
            raise TypeSafeError(f"{self.provider_label} response is missing an 'answers' array", cause=CAUSE_INVALID_RESPONSE)

        by_name = _answers_by_name(raw_answers)
        # ``model`` is optional here: the endpoint may echo the served version, and when it does
        # that value is what a consumer records. When it does not, the model this request named is
        # recorded instead — provenance is still needed for the audit trail, and unlike a value
        # the endpoint returned it cannot have been chosen to be echoed into a log.
        model = payload.get("model")
        served = model if isinstance(model, str) and model else self._connection.model

        validated: dict[str, Answer] = {}
        errors: dict[str, QuestionError] = {}
        for question_id, question in questions.items():
            answer, error = validate_answer(question_id, question, by_name.get(question_id), provider_label=self.provider_label)
            if error is not None:
                errors[question_id] = error
            elif answer is not None:
                validated[question_id] = answer
        return AnswerSet(model=served, answers=validated, errors_by_question=errors)


def encode_question(question_id: str, question: Question) -> dict[str, object]:
    """Encode one shared :class:`Question` as a Decisions question object."""
    if question.type == QUESTION_CHOICE:
        # A choice question does carry its options, so the criteria map onto them directly and the
        # instruction text is left alone; silently narrowing it would change what is judged.
        return {
            "type": QUESTION_CHOICE,
            "name": question_id,
            "instructions": question.instructions,
            "choices": [{"value": label, "description": description} for label, description in (question.criteria or {}).items()],
        }
    return {"type": QUESTION_PREDICATE, "name": question_id, "instructions": predicate_instructions(question)}


def predicate_instructions(question: Question) -> str:
    """The rubric a predicate question has no field for, folded into its instructions."""
    if not question.criteria:
        return question.instructions
    rubric = "".join(f"\nAnswer {label} when: {description}" for label, description in question.criteria.items())
    return f"{question.instructions}{rubric}"


def _answers_by_name(raw_answers: list[object]) -> dict[str, dict[object, object]]:
    """Index the answer array by ``name``, first occurrence winning.

    An array can repeat a name while a mapping cannot, and which of two conflicting answers a
    consumer would act on must not depend on how a server orders them. Answers without a usable
    name, and names nobody asked about, are ignored rather than reported: the shared contract is
    that only the questions actually asked appear in the outcome.
    """
    by_name: dict[str, dict[object, object]] = {}
    for entry in raw_answers:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name not in by_name:
            by_name[name] = entry
    return by_name


def validate_answer(question_id: str, question: Question, entry: dict[object, object] | None, *, provider_label: str) -> tuple[Answer | None, QuestionError | None]:
    """Validate one answer against the question that was asked, reusing the shared rules."""
    if entry is None:
        return None, QuestionError(question_id=question_id, category=CATEGORY_MISSING, message=f"{provider_label} response has no answer for question {question_id!r}")
    answer_type = entry.get("type")
    if answer_type == ANSWER_TYPE_REFUSAL:
        # Only the outcome is reported. A refusal object is response content and can carry text the
        # endpoint chose, which must not reach a log or a reason message unchecked.
        return None, QuestionError(question_id=question_id, category=CATEGORY_REFUSAL, message=f"{provider_label} refused to answer question {question_id!r}")
    expected = QUESTION_CHOICE if question.type == QUESTION_CHOICE else QUESTION_PREDICATE
    if answer_type != expected:
        return None, QuestionError(
            question_id=question_id,
            category=CATEGORY_TYPE,
            message=f"{provider_label} answer for {question_id!r} is not a {expected} answer (type={type(answer_type).__name__})",
        )
    if expected == QUESTION_PREDICATE:
        return validate_probability(question_id, entry.get("probability"), provider_label=provider_label, field_name="predicate")
    return validate_choice_label(question_id, question, entry.get("choice"), provider_label=provider_label)


__all__ = [
    "ANSWER_TYPE_REFUSAL",
    "CATEGORY_REFUSAL",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "ENDPOINT_PATH",
    "QUESTION_CHOICE",
    "QUESTION_PREDICATE",
    "OpenAIDecisionsClient",
    "encode_question",
    "predicate_instructions",
    "provider_defaults",
    "resolve_decisions_connection",
]
