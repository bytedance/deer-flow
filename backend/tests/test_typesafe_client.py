"""Tests for the shared ``deerflow.typesafe`` client.

The three provider suites pin the tool gate's behaviour *through* the client;
these pin what the client adds on its own:

* per-question partial success — one bad answer must not discard the good ones in
  the same response (design §2.3), and the tool gate must keep reporting its own
  question's failure exactly as it did before the parser was split;
* byte counting that replaces no character limit (design §2.4);
* the sharing identity (design §4 rule 2) — see ``test_typesafe_config.py`` for
  the identity split, this file covers the transport contract.
"""

from __future__ import annotations

import json

import httpx
import pytest

from deerflow.guardrails.provider import GuardrailRequest
from deerflow.guardrails.typesafe import TypeSafeGuardrailError, TypeSafeGuardrailProvider
from deerflow.typesafe.client import (
    CATEGORY_LABEL,
    CATEGORY_MISSING,
    CATEGORY_PROBABILITY,
    CATEGORY_TYPE,
    QUESTION_CHOICE,
    QUESTION_NOUL,
    ChoiceAnswer,
    NoulAnswer,
    Question,
    TypeSafeClient,
    wire_size,
)
from deerflow.typesafe.connection import resolve_connection
from deerflow.typesafe.errors import CAUSE_INVALID_RESPONSE, TypeSafeError

_API_KEY = "shared-client-test-key"
_FIRST = "first_question"
_SECOND = "second_question"
_GATE_QUESTION = "risky_tool_call"

_NOUL = Question(type=QUESTION_NOUL, instructions="Does this matter?")
_CHOICE = Question(type=QUESTION_CHOICE, instructions="Which label?", criteria={"keep": "worth keeping", "drop": "not worth keeping"})


class _Server:
    """Fake System One endpoint that records every request it receives."""

    def __init__(self, responder=None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder or (lambda request: httpx.Response(200, json=_response({_GATE_QUESTION: {"type": "noul", "noul": 0.9}})))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def count(self) -> int:
        return len(self.requests)


def _response(answers: dict, model: str = "jev-1.13.0") -> dict:
    return {"model": model, "answers": answers}


def _ask(server: _Server, questions: dict[str, Question], **settings):
    connection = resolve_connection(settings={"api_key": _API_KEY, **settings}, configuration_source="tests.typesafe")
    return TypeSafeClient(connection, transport_factory=server.transport).ask({"tool_call": {"name": "bash", "arguments": "{}"}}, questions)


def _gate(server: _Server, **kwargs) -> TypeSafeGuardrailProvider:
    return TypeSafeGuardrailProvider(api_key=_API_KEY, transport_factory=server.transport, **kwargs)


def _tool_call() -> GuardrailRequest:
    return GuardrailRequest(tool_name="bash", tool_input={"command": "ls"})


# --- per-question partial success -----------------------------------------


class TestPartialSuccess:
    def test_a_valid_answer_survives_an_invalid_one(self):
        server = _Server(lambda request: httpx.Response(200, json=_response({_FIRST: {"type": "noul", "noul": 0.25}, _SECOND: {"type": "noul", "noul": "0.9"}})))

        answer_set = _ask(server, {_FIRST: _NOUL, _SECOND: _NOUL})

        assert answer_set.answers[_FIRST] == NoulAnswer(probability=0.25)
        assert answer_set.noul(_SECOND) is None
        error = answer_set.errors_by_question[_SECOND]
        assert error.category == CATEGORY_PROBABILITY
        assert "type=str" in error.message
        assert "0.9" not in error.message, "the response body is never repeated into a message"

    def test_an_oversized_noul_integer_does_not_discard_a_valid_sibling(self):
        """A JSON integer too large for float() is a per-question error, not a crash.

        ``float(10**400)`` raises OverflowError; letting it escape ``_parse`` would
        discard the valid answer in the same response (design §2.3 isolation).
        """
        server = _Server(lambda request: httpx.Response(200, json=_response({_FIRST: {"type": "noul", "noul": 0.25}, _SECOND: {"type": "noul", "noul": 10**400}})))

        answer_set = _ask(server, {_FIRST: _NOUL, _SECOND: _NOUL})

        assert answer_set.answers[_FIRST] == NoulAnswer(probability=0.25), "the valid sibling survives"
        assert answer_set.noul(_SECOND) is None
        assert answer_set.errors_by_question[_SECOND].category == CATEGORY_PROBABILITY

    @pytest.mark.parametrize(
        ("answers", "questions", "category"),
        [
            ({}, {_FIRST: _NOUL}, CATEGORY_MISSING),
            ({_FIRST: "not an object"}, {_FIRST: _NOUL}, CATEGORY_TYPE),
            ({_FIRST: {"type": "choice", "choice": "keep"}}, {_FIRST: _NOUL}, CATEGORY_TYPE),
            ({_FIRST: {"type": "noul", "noul": 1.5}}, {_FIRST: _NOUL}, CATEGORY_PROBABILITY),
            ({_FIRST: {"type": "noul", "noul": True}}, {_FIRST: _NOUL}, CATEGORY_PROBABILITY),
            ({_FIRST: {"type": "choice", "choice": "unknown"}}, {_FIRST: _CHOICE}, CATEGORY_LABEL),
            ({_FIRST: {"type": "choice", "choice": 7}}, {_FIRST: _CHOICE}, CATEGORY_LABEL),
        ],
    )
    def test_a_bad_answer_is_reported_per_question_not_per_request(self, answers, questions, category):
        server = _Server(lambda request: httpx.Response(200, json=_response(answers)))

        answer_set = _ask(server, questions)

        assert answer_set.answers == {}
        assert answer_set.errors_by_question[_FIRST].category == category

    def test_a_valid_choice_label_is_returned(self):
        server = _Server(lambda request: httpx.Response(200, json=_response({_FIRST: {"type": "choice", "choice": "keep"}})))

        answer_set = _ask(server, {_FIRST: _CHOICE})

        assert answer_set.answers[_FIRST] == ChoiceAnswer(label="keep")
        assert answer_set.errors_by_question == {}

    def test_an_answer_for_a_question_that_was_not_asked_is_ignored(self):
        server = _Server(lambda request: httpx.Response(200, json=_response({_FIRST: {"type": "noul", "noul": 0.25}, "never_asked": {"type": "noul", "noul": "not a number"}})))

        answer_set = _ask(server, {_FIRST: _NOUL})

        assert set(answer_set.answers) == {_FIRST}
        assert answer_set.errors_by_question == {}

    @pytest.mark.parametrize("content", [b"not json at all", b'[{"model": "jev-1.13.0"}]', b'{"model": "jev-1.13.0"}', b'{"answers": {"risky_tool_call": {"type": "noul", "noul": 0.1}}}', b'{"model": "", "answers": {}}'])
    def test_the_envelope_still_fails_the_whole_request(self, content):
        """A missing envelope is request level: the caller cannot use any of it."""
        server = _Server(lambda request, content=content: httpx.Response(200, content=content))

        with pytest.raises(TypeSafeError) as excinfo:
            _ask(server, {_FIRST: _NOUL})

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE

    def test_a_missing_answer_is_data_where_a_missing_envelope_raises(self):
        """Teeth for the layer split: the same questions, one envelope apart."""
        with_envelope = _Server(lambda request: httpx.Response(200, json=_response({_SECOND: {"type": "noul", "noul": 0.1}})))
        answer_set = _ask(with_envelope, {_FIRST: _NOUL})
        assert answer_set.errors_by_question[_FIRST].category == CATEGORY_MISSING

        without_envelope = _Server(lambda request: httpx.Response(200, content=b'{"model": "jev-1.13.0"}'))
        with pytest.raises(TypeSafeError):
            _ask(without_envelope, {_FIRST: _NOUL})


# --- the tool gate's mapping of a question-level failure -------------------


class TestGateQuestionMapping:
    def test_the_gate_reports_a_question_level_failure_as_invalid_response(self):
        server = _Server(lambda request: httpx.Response(200, json=_response({_GATE_QUESTION: {"type": "noul", "noul": "0.9"}})))

        with pytest.raises(TypeSafeGuardrailError) as excinfo:
            _gate(server).evaluate(_tool_call())

        assert excinfo.value.cause == CAUSE_INVALID_RESPONSE
        assert "type=str" in str(excinfo.value)

    def test_another_questions_failure_does_not_change_the_gates_verdict(self):
        """The gate asks one question; an unusable answer for anything else is ignored."""
        server = _Server(lambda request: httpx.Response(200, json=_response({_GATE_QUESTION: {"type": "noul", "noul": 0.1}, "other_question": {"type": "noul", "noul": "not a number"}})))

        decision = _gate(server).evaluate(_tool_call())

        assert decision.allow is True
        assert decision.metadata["probability"] == 0.1


# --- wire size and the limits it must not move -----------------------------


class TestWireSize:
    def test_wire_size_matches_what_httpx_sends(self):
        value = {"state": {"tool_call": {"name": "bash", "arguments": "{}"}}, "model": "jev-latest", "questions": {_FIRST: {"type": "noul", "instructions": "héllo 中文"}}}

        request = httpx.Request("POST", "https://api.typesafe.ai/v1/systemone", json=value)

        assert wire_size(value) == len(request.content)

    def test_wire_size_counts_utf8_bytes_not_characters(self):
        value = {"command": "中" * 100}
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        assert wire_size(value) == len(compact.encode("utf-8"))
        assert wire_size(value) > len(compact), "one CJK character is three UTF-8 bytes"

    def test_the_gates_argument_limit_stays_a_character_count(self):
        """Design §2.4: the client counts bytes, and moves no existing limit."""
        arguments = {"command": "中" * 100}
        arguments_text = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert wire_size(arguments) > len(arguments_text), "the wire is larger than this character count"

        refused_server = _Server()
        refused = _gate(refused_server, max_state_chars=len(arguments_text) - 1).evaluate(GuardrailRequest(tool_name="bash", tool_input=arguments))

        assert refused.allow is False
        assert refused.metadata["length"] == len(arguments_text)
        assert refused_server.count == 0

        sent_server = _Server()
        judged = _gate(sent_server, max_state_chars=len(arguments_text)).evaluate(GuardrailRequest(tool_name="bash", tool_input=arguments))

        assert sent_server.count == 1, "the same text fits under the character limit, so it is evaluated"
        assert judged.metadata["probability"] == 0.9
