"""Tests for the OpenAI Decisions backend (issue #7005).

Three things are pinned here, and each is a claim the change could silently break:

* **The wire mapping both directions.** A ``noul`` question must leave as a ``predicate``
  question whose rubric still travels with it, and an answer array must come back as the same
  ``NoulAnswer`` / ``ChoiceAnswer`` / ``QuestionError`` shapes the Jev client produces — because
  every consumer's threshold, cache bucket and failure direction is written against those.
* **That the shared transport rules still hold for a second dialect.** Bounded never-decoded
  body, the two-layer error split, the identity encoding, and "a refusal is a per-question
  outcome". A duplicated transport would have had to re-earn each of those.
* **That the gate's direction did not move.** The tool gate still denies at or above its
  threshold and fails closed on a refusal, while the memory sides still fall back — the same
  request, opposite policies, owned by each adapter as before.

Everything runs offline through ``httpx.MockTransport``, the pattern the Jev suites use.
"""

from __future__ import annotations

import gzip
import hashlib
import json

import httpx
import pytest

from deerflow.agents.memory.prescreen.contract import MODE_ENFORCE, resolve_memory_prescreen
from deerflow.agents.memory.prescreen.openai_decisions import OpenAIDecisionsMemoryPrescreen
from deerflow.agents.memory.prescreen.typesafe import QUESTION_ID as PRESCREEN_QUESTION
from deerflow.agents.memory.prescreen.typesafe import TypeSafeMemoryPrescreen
from deerflow.agents.memory.signals.contract import LABEL_REINFORCEMENT
from deerflow.agents.memory.signals.coordinator import MemoryBatchContext, MemorySignalCoordinator
from deerflow.agents.memory.signals.openai_decisions import OpenAIDecisionsSignalClassifier
from deerflow.agents.memory.signals.typesafe import QUESTION_AFFIRMATION, QUESTION_NEGATION, TypeSafeSignalClassifier
from deerflow.guardrails.openai_decisions import OpenAIDecisionsGuardrailError, OpenAIDecisionsGuardrailProvider
from deerflow.guardrails.provider import GuardrailRequest
from deerflow.openai_decisions.client import (
    CATEGORY_REFUSAL,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    ENDPOINT_PATH,
    QUESTION_CHOICE,
    QUESTION_PREDICATE,
    OpenAIDecisionsClient,
    resolve_decisions_connection,
)
from deerflow.typesafe.client import (
    CATEGORY_LABEL,
    CATEGORY_MISSING,
    CATEGORY_PROBABILITY,
    CATEGORY_TYPE,
    MAX_RESPONSE_BYTES,
    QUESTION_NOUL,
    NoulAnswer,
    Question,
)
from deerflow.typesafe.errors import CAUSE_HTTP_STATUS, CAUSE_INVALID_RESPONSE, TypeSafeError

_API_KEY = "decisions-test-key"
_MODEL = "gpt-decisions-test"
_RUBRIC_TRUE = "it deletes data"
_RUBRIC_FALSE = "it only reads"
_PREDICATE = Question(type=QUESTION_NOUL, instructions="Is this risky?", criteria={"true": _RUBRIC_TRUE, "false": _RUBRIC_FALSE})
_CHOICE = Question(type=QUESTION_CHOICE, instructions="Which label?", criteria={"keep": "worth keeping", "drop": "not worth keeping"})

#: The canonical state JSON the gate digests, written out by hand rather than re-derived by the
#: code under test: the assertion below would pass even if the serialisation changed shape.
_EXPECTED_GATE_INPUT = '{"tool_call":{"arguments":"{\\"command\\":\\"ls\\"}","name":"bash"}}'


class _Server:
    """Fake Decisions endpoint that records every request it receives."""

    def __init__(self, responder=None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder or (lambda request: httpx.Response(200, json={"answers": [_predicate_answer("q", 0.9)]}))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def body(self) -> dict:
        return json.loads(self.requests[-1].content.decode("utf-8"))


def _predicate_probability_body(name: str, probability_json: str) -> bytes:
    return f'{{"answers":[{{"type":"{QUESTION_PREDICATE}","name":"{name}","probability":{probability_json}}}]}}'.encode()


def _predicate_answer(name: str, probability: float) -> dict:
    return {"type": QUESTION_PREDICATE, "name": name, "probability": probability}


def _client(server: _Server, **settings) -> OpenAIDecisionsClient:
    connection = resolve_decisions_connection(settings={"api_key": _API_KEY, "model": _MODEL, **settings}, configuration_source="tests.openai_decisions")
    return OpenAIDecisionsClient(connection, transport_factory=server.transport)


def _ask(server: _Server, questions: dict[str, Question], input_value: object = "judged text") -> object:
    return _client(server).ask(input_value, questions)


# --- request mapping --------------------------------------------------------


class TestRequestMapping:
    def test_a_noul_question_leaves_as_a_predicate_question(self):
        server = _Server()

        _ask(server, {"q": _PREDICATE})

        question = server.body["questions"][0]
        assert question["type"] == QUESTION_PREDICATE
        assert question["name"] == "q"

    def test_the_rubric_travels_because_a_predicate_question_has_no_field_for_it(self):
        """Dropping the criteria would move the decision boundary while the adapter kept reporting
        the same ``criteria`` in its policy identity."""
        server = _Server()

        _ask(server, {"q": _PREDICATE})

        instructions = server.body["questions"][0]["instructions"]
        assert instructions.startswith("Is this risky?")
        assert _RUBRIC_TRUE in instructions
        assert _RUBRIC_FALSE in instructions

    def test_a_choice_question_keeps_its_instructions_and_carries_its_options(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": QUESTION_CHOICE, "name": "q", "choice": "keep", "confidence": 0.9}]}))

        _ask(server, {"q": _CHOICE})

        question = server.body["questions"][0]
        assert question == {
            "type": QUESTION_CHOICE,
            "name": "q",
            "instructions": "Which label?",
            "choices": [{"value": "keep", "description": "worth keeping"}, {"value": "drop", "description": "not worth keeping"}],
        }

    def test_the_judged_value_is_input_and_no_state_envelope_is_sent(self):
        server = _Server()

        _ask(server, {"q": _PREDICATE}, input_value="the batch text")

        assert server.body["input"] == "the batch text"
        assert "state" not in server.body
        assert server.body["model"] == _MODEL

    def test_it_posts_to_the_decisions_endpoint_with_the_shared_headers(self):
        server = _Server()

        _ask(server, {"q": _PREDICATE})

        request = server.requests[-1]
        assert request.url.path == ENDPOINT_PATH
        assert request.method == "POST"
        assert request.headers["authorization"] == f"Bearer {_API_KEY}"
        # The bounded body read depends on this: an encoded body would make the *decoded* size the
        # number that matters, and the client would be counting the wrong thing.
        assert request.headers["accept-encoding"] == "identity"

    def test_questions_keep_their_request_order(self):
        server = _Server()

        _ask(server, {QUESTION_NEGATION: _PREDICATE, QUESTION_AFFIRMATION: _PREDICATE})

        assert [entry["name"] for entry in server.body["questions"]] == [QUESTION_NEGATION, QUESTION_AFFIRMATION]


class TestConnectionDefaults:
    @pytest.mark.parametrize("provider", [OpenAIDecisionsGuardrailProvider, OpenAIDecisionsMemoryPrescreen, OpenAIDecisionsSignalClassifier])
    @pytest.mark.parametrize("settings, field", [({"api_key": "", "model": _MODEL}, "API key"), ({"api_key": _API_KEY}, "model")])
    def test_construction_errors_name_the_configured_service(self, provider, settings, field):
        with pytest.raises(ValueError) as excinfo:
            provider(**settings)

        message = str(excinfo.value)
        assert "OpenAI Decisions" in message
        assert "TypeSafe" not in message
        assert field in message
        assert _API_KEY not in message

    def test_the_backend_defaults_to_its_own_service_not_the_jev_one(self):
        server = _Server()

        client = _client(server)

        assert client.connection.base_url == DEFAULT_BASE_URL
        assert client.connection.url == f"{DEFAULT_BASE_URL}{ENDPOINT_PATH}"
        assert client.connection.api_key_env == DEFAULT_API_KEY_ENV

    def test_a_deployment_must_name_its_model_rather_than_inheriting_another_services_default(self):
        """No checked-in model id: an empty default fails loudly at construction."""
        with pytest.raises(ValueError, match="model must be a non-empty string"):
            resolve_decisions_connection(settings={"api_key": _API_KEY}, configuration_source="tests.openai_decisions")

    def test_an_operator_override_still_wins(self):
        server = _Server()

        client = _client(server, base_url="http://127.0.0.1:8000", model="local-decisions")

        assert client.connection.url == "http://127.0.0.1:8000/v1/decisions"


# --- response mapping ------------------------------------------------------


class TestResponseMapping:
    def test_a_probability_comes_back_as_the_shared_answer_type(self):
        server = _Server(lambda request: httpx.Response(200, json={"model": "served-1.2", "answers": [_predicate_answer("q", 0.31)]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.answers["q"] == NoulAnswer(probability=0.31)
        assert answers.model == "served-1.2"

    def test_a_response_without_a_model_records_the_one_that_was_asked_for(self):
        """Provenance is still needed for the audit trail, and the requested model is the only
        value here that the endpoint did not choose."""
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("q", 0.31)]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.model == _MODEL

    def test_a_refusal_is_a_per_question_outcome_not_a_request_failure(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": "refusal", "name": "q"}]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.answers == {}
        error = answers.errors_by_question["q"]
        assert error.category == CATEGORY_REFUSAL
        assert "refused to answer" in error.message

    def test_a_valid_answer_survives_an_invalid_one_in_the_same_array(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("good", 0.4), {"type": QUESTION_PREDICATE, "name": "bad", "probability": "0.9"}]}))

        answers = _ask(server, {"good": _PREDICATE, "bad": _PREDICATE})

        assert answers.answers["good"] == NoulAnswer(probability=0.4)
        assert answers.errors_by_question["bad"].category == CATEGORY_PROBABILITY

    @pytest.mark.parametrize(
        ("probability_json", "expected"),
        [
            ("true", "non-numeric"),  # bool is an int subclass, so True would judge as 1.0
            ('"0.9"', "non-numeric"),  # a JSON string must not silently become a number
            ("1.5", "outside [0, 1]"),
            ("-0.1", "outside [0, 1]"),
            ("Infinity", "outside [0, 1]"),  # a bare literal json.loads accepts and a threshold cannot
        ],
    )
    def test_the_shared_numeric_rules_apply_to_this_dialect_too(self, probability_json, expected):
        """Written as raw JSON text rather than a Python value, because the payload under test is
        what an endpoint can actually put on the wire."""
        server = _Server(lambda request: httpx.Response(200, content=_predicate_probability_body("q", probability_json), headers={"content-type": "application/json"}))

        answers = _ask(server, {"q": _PREDICATE})

        error = answers.errors_by_question["q"]
        assert error.category == CATEGORY_PROBABILITY
        assert expected in error.message
        assert probability_json not in error.message, "the response body is never repeated into a message"

    def test_a_probability_answered_to_the_wrong_question_kind_is_not_a_verdict(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": "score", "name": "q", "score": 3}]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.errors_by_question["q"].category == CATEGORY_TYPE

    def test_a_choice_label_outside_the_asked_set_is_rejected(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": QUESTION_CHOICE, "name": "q", "choice": "shred"}]}))

        answers = _ask(server, {"q": _CHOICE})

        assert answers.errors_by_question["q"].category == CATEGORY_LABEL

    def test_the_first_answer_for_a_repeated_name_wins(self):
        """An array can repeat a name where a mapping cannot; which of two conflicting answers a
        consumer acts on must not depend on server ordering."""
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("q", 0.2), _predicate_answer("q", 0.9)]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.answers["q"] == NoulAnswer(probability=0.2)

    def test_an_answer_for_a_question_that_was_never_asked_is_ignored_not_reported(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("q", 0.2), _predicate_answer("somebody_elses_question", 0.95)]}))

        answers = _ask(server, {"q": _PREDICATE})

        assert set(answers.answers) == {"q"}
        assert answers.errors_by_question == {}

    def test_a_missing_entry_is_reported_as_missing(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": []}))

        answers = _ask(server, {"q": _PREDICATE})

        assert answers.errors_by_question["q"].category == CATEGORY_MISSING


class TestEnvelopeFailures:
    def test_a_non_200_names_this_service_and_not_the_other_one(self):
        server = _Server(lambda request: httpx.Response(500))

        with pytest.raises(TypeSafeError) as excinfo:
            _ask(server, {"q": _PREDICATE})

        assert excinfo.value.cause == CAUSE_HTTP_STATUS
        assert "OpenAI Decisions returned HTTP 500" in str(excinfo.value)

    def test_an_answers_object_is_not_an_array_and_is_not_a_verdict(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": {"q": {"probability": 0.9}}}))

        with pytest.raises(TypeSafeError, match="'answers' array") as excinfo:
            _ask(server, {"q": _PREDICATE})

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE

    def test_an_oversized_body_is_refused_rather_than_read(self):
        filler = "x" * (MAX_RESPONSE_BYTES + 1024)
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("q", 0.5), {"type": "refusal", "name": filler}]}))

        with pytest.raises(TypeSafeError, match="exceeded") as excinfo:
            _ask(server, {"q": _PREDICATE})

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE

    def test_a_compressed_body_is_refused_rather_than_expanded(self):
        """Refused by its encoding, not by a parse failure: this body decodes to a valid envelope."""
        envelope = json.dumps({"answers": [_predicate_answer("q", 0.5)]}).encode()
        server = _Server(lambda request: httpx.Response(200, content=gzip.compress(envelope), headers={"Content-Encoding": "gzip"}))

        with pytest.raises(TypeSafeError, match="non-identity") as excinfo:
            _ask(server, {"q": _PREDICATE})

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE


# --- the tool gate ---------------------------------------------------------


def _gate(server: _Server, **kwargs) -> OpenAIDecisionsGuardrailProvider:
    return OpenAIDecisionsGuardrailProvider(api_key=_API_KEY, model=_MODEL, transport_factory=server.transport, **kwargs)


def _tool_call() -> GuardrailRequest:
    return GuardrailRequest(tool_name="bash", tool_input={"command": "ls"})


class TestGuardrailGate:
    def test_a_probability_at_the_threshold_denies_and_names_this_provider(self):
        server = _Server(lambda request: httpx.Response(200, json={"model": "served-1.2", "answers": [_predicate_answer("risky_tool_call", 0.5)]}))

        decision = _gate(server, threshold=0.5).evaluate(_tool_call())

        assert decision.allow is False
        assert decision.reasons[0].code == "openai_decisions.tool_call_risky"
        assert "model=served-1.2" in decision.reasons[0].message

    def test_a_probability_below_the_threshold_allows(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("risky_tool_call", 0.4999)]}))

        decision = _gate(server, threshold=0.5).evaluate(_tool_call())

        assert decision.allow is True
        assert decision.reasons[0].code == "openai_decisions.allowed"

    def test_the_bytes_judged_are_the_bytes_the_audit_digest_identifies(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer("risky_tool_call", 0.9)]}))

        decision = _gate(server).evaluate(_tool_call())

        sent = server.body["input"]
        assert sent == _EXPECTED_GATE_INPUT
        assert decision.metadata["state_digest"] == hashlib.sha256(sent.encode("utf-8")).hexdigest()[:16]

    def test_a_refusal_denies_for_want_of_a_verdict(self):
        """The gate has no verdict without its answer, so a refusal is a denial here while the
        same outcome is 'no opinion' for the memory sides."""
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": "refusal", "name": "risky_tool_call"}]}))

        with pytest.raises(OpenAIDecisionsGuardrailError) as excinfo:
            _gate(server).evaluate(_tool_call())

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE
        assert "refused to answer" in str(excinfo.value)

    def test_a_request_failure_is_the_provider_error_family_the_middleware_already_maps(self):
        server = _Server(lambda request: httpx.Response(503))

        with pytest.raises(OpenAIDecisionsGuardrailError):
            _gate(server).evaluate(_tool_call())

    def test_an_oversized_call_is_denied_locally_without_a_request(self):
        server = _Server()

        decision = _gate(server, max_state_chars=10).evaluate(GuardrailRequest(tool_name="bash", tool_input={"command": "rm -rf /tmp/anything-at-all"}))

        assert decision.allow is False
        assert decision.reasons[0].code == "openai_decisions.state_unusable"
        assert server.requests == []


# --- the memory sides ------------------------------------------------------


def _prescreen(server: _Server, **kwargs) -> OpenAIDecisionsMemoryPrescreen:
    return OpenAIDecisionsMemoryPrescreen(mode=MODE_ENFORCE, api_key=_API_KEY, model=_MODEL, transport_factory=server.transport, **kwargs)


class TestMemorySides:
    def test_the_pre_screen_skips_below_its_threshold_on_the_same_text_it_always_judged(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [_predicate_answer(PRESCREEN_QUESTION, 0.1)]}))
        provider = _prescreen(server, skip_threshold=0.2)

        decision = provider.decide(_prescreen_request("user: keep using uv\nassistant: noted"))

        assert decision.verdict == "skip"
        assert server.body["input"] == "user: keep using uv\nassistant: noted"
        assert server.body["questions"][0]["name"] == PRESCREEN_QUESTION

    def test_a_refusal_is_no_opinion_so_the_batch_still_extracts(self):
        server = _Server(lambda request: httpx.Response(200, json={"answers": [{"type": "refusal", "name": PRESCREEN_QUESTION}]}))

        assert _prescreen(server).decide(_prescreen_request("anything")) is None

    def test_both_directions_travel_in_one_request_and_a_refusal_only_costs_its_own_label(self):
        server = _Server(
            lambda request: httpx.Response(
                200,
                json={"answers": [_predicate_answer(QUESTION_AFFIRMATION, 0.8), {"type": "refusal", "name": QUESTION_NEGATION}]},
            )
        )
        provider = OpenAIDecisionsSignalClassifier(mode="hints", api_key=_API_KEY, model=_MODEL, transport_factory=server.transport)

        decision = provider.decide(_signal_request("user: yes keep using uv"))

        assert [entry["name"] for entry in server.body["questions"]] == [QUESTION_AFFIRMATION, QUESTION_NEGATION]
        assert decision.probabilities == {LABEL_REINFORCEMENT: 0.8}
        assert decision.labels == frozenset({LABEL_REINFORCEMENT})

    def test_the_two_backends_never_share_one_combined_request(self):
        """``sharing_key`` is what lets two sides travel together; a different endpoint or a
        different credential must separate them or a verdict could be served to the wrong service."""
        server = _Server()
        settings = {"api_key": _API_KEY, "model": _MODEL, "base_url": "https://decision-gateway.example", "transport_factory": server.transport}
        left = TypeSafeMemoryPrescreen(**settings)
        right = OpenAIDecisionsMemoryPrescreen(**settings)

        assert left._connection.url != right._connection.url
        assert left.sharing_key() != right.sharing_key()

    def test_it_resolves_from_the_existing_provider_slot_without_a_schema_change(self):
        provider = resolve_memory_prescreen(
            mode="shadow",
            use="deerflow.agents.memory.prescreen.openai_decisions:OpenAIDecisionsMemoryPrescreen",
            config={"api_key": _API_KEY, "model": _MODEL},
        )

        assert provider.name == "openai_decisions"
        assert provider.policy_id == "deerflow.memory.prescreen.openai_decisions"


def _gateway_response(request: httpx.Request) -> httpx.Response:
    """One gateway serves both dialects, with different classifier opinions."""
    questions = json.loads(request.content)["questions"]
    if request.url.path == "/v1/systemone":
        assert isinstance(questions, dict)
        return httpx.Response(200, json={"model": "jev-test", "answers": {name: {"type": "noul", "noul": 0.1} for name in questions}})
    assert request.url.path == "/v1/decisions"
    probabilities = {PRESCREEN_QUESTION: 0.1, QUESTION_AFFIRMATION: 0.9, QUESTION_NEGATION: 0.1}
    return httpx.Response(200, json={"answers": [_predicate_answer(question["name"], probabilities[question["name"]]) for question in questions]})


def _judge_gateway(prescreen_type, classifier_type, combine):
    server = _Server(_gateway_response)
    settings = {"api_key": _API_KEY, "model": _MODEL, "base_url": "https://decision-gateway.example", "transport_factory": server.transport}
    coordinator = MemorySignalCoordinator(
        prescreen=prescreen_type(mode="enforce", **settings),
        prescreen_mode="enforce",
        classifier=classifier_type(mode="hints", **settings),
        classifier_mode="hints",
        combine=combine,
    )
    text = "user: Continue using the same editor preference."
    verdict = coordinator.judge(MemoryBatchContext(batch_text=text, digest=hashlib.sha256(text.encode()).hexdigest()[:16]))
    return server, verdict


class TestSameGatewayCoordination:
    @pytest.mark.parametrize("combine", ["auto", "never"])
    @pytest.mark.parametrize(
        "prescreen_type, classifier_type, paths, veto",
        [
            (TypeSafeMemoryPrescreen, OpenAIDecisionsSignalClassifier, ["/v1/systemone", "/v1/decisions"], True),
            (OpenAIDecisionsMemoryPrescreen, TypeSafeSignalClassifier, ["/v1/decisions", "/v1/systemone"], False),
        ],
    )
    def test_mixed_backends_keep_their_requests_and_verdicts(self, combine, prescreen_type, classifier_type, paths, veto):
        server, verdict = _judge_gateway(prescreen_type, classifier_type, combine)

        assert [request.url.path for request in server.requests] == paths
        for request, expected_questions in zip(server.requests, [{PRESCREEN_QUESTION}, {QUESTION_AFFIRMATION, QUESTION_NEGATION}], strict=True):
            body = json.loads(request.content)
            if request.url.path == "/v1/systemone":
                assert set(body["questions"]) == expected_questions
                assert "state" in body and "input" not in body
            else:
                assert {question["name"] for question in body["questions"]} == expected_questions
                assert "input" in body and "state" not in body
        assert verdict.skip is not veto
        assert verdict.vetoed_by_model_signal is veto
        assert verdict.hints == (frozenset({LABEL_REINFORCEMENT}) if veto else frozenset())

    @pytest.mark.parametrize(
        "prescreen_type, classifier_type, path, veto",
        [
            (TypeSafeMemoryPrescreen, TypeSafeSignalClassifier, "/v1/systemone", False),
            (OpenAIDecisionsMemoryPrescreen, OpenAIDecisionsSignalClassifier, "/v1/decisions", True),
        ],
    )
    def test_matching_backends_still_combine(self, prescreen_type, classifier_type, path, veto):
        server, verdict = _judge_gateway(prescreen_type, classifier_type, "auto")

        assert [request.url.path for request in server.requests] == [path]
        questions = json.loads(server.requests[0].content)["questions"]
        names = set(questions) if path == "/v1/systemone" else {question["name"] for question in questions}
        assert names == {PRESCREEN_QUESTION, QUESTION_AFFIRMATION, QUESTION_NEGATION}
        assert verdict.skip is not veto
        assert verdict.vetoed_by_model_signal is veto


def _prescreen_request(text: str):
    from deerflow.agents.memory.prescreen.contract import MemoryPrescreenRequest

    return MemoryPrescreenRequest(batch_text=text, digest=hashlib.sha256(text.encode()).hexdigest()[:16])


def _signal_request(text: str):
    from deerflow.agents.memory.signals.contract import MemorySignalRequest

    return MemorySignalRequest(batch_text=text, digest=hashlib.sha256(text.encode()).hexdigest()[:16])
