"""Memory pre-screening and signal classification: contracts, adapters, insertion, locks.

Covers the pre-screening plan's §4 checklist (L1-L11, the watermark branches, the
boundary cases, ``mutations_accepted``) and the signal-classification design's
combination rules (§2.2: eligibility, assembly, per-question failure, the veto,
``combine`` policies), all against the real updater rather than mocks of it.
"""

from __future__ import annotations

import copy
import json
import pathlib

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.prompt import format_conversation_for_update
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater
from deerflow.agents.memory.prescreen.contract import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MemoryPrescreenRequest,
    resolve_memory_prescreen,
)
from deerflow.agents.memory.prescreen.typesafe import TypeSafeMemoryPrescreen
from deerflow.agents.memory.signals.contract import (
    COMBINE_ALWAYS,
    COMBINE_NEVER,
    LABEL_CORRECTION,
    LABEL_REINFORCEMENT,
    MODE_HINTS,
    MemorySignalRequest,
    resolve_memory_signal_classifier,
)
from deerflow.agents.memory.signals.coordinator import MemoryBatchContext, MemorySignalCoordinator
from deerflow.agents.memory.signals.typesafe import QUESTION_AFFIRMATION, QUESTION_NEGATION, TypeSafeSignalClassifier

_API_KEY = "memory-judge-test-key"
_PRESCREEN_Q = "memory_worth_keeping"
_JUDGE_HOOK = "judge"

# Signal-free on purpose: any deterministic signal removes the pre-screen's
# eligibility (L3), so a fixture that trips one would silently test the fallback.
_KEEPING_TEXT = "We reviewed the release candidate on Tuesday afternoon and the notes are in /tmp/notes.md"
_CHATTER_TEXT = "ok, thanks"

_PRESCREEN = "deerflow.agents.memory.prescreen.typesafe:TypeSafeMemoryPrescreen"
_CLASSIFIER = "deerflow.agents.memory.signals.typesafe:TypeSafeSignalClassifier"


class _Server:
    """Fake System One endpoint that records every request it receives."""

    def __init__(self, responder=None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder or (lambda request: httpx.Response(200, json=_answer(0.9)))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def count(self) -> int:
        return len(self.requests)

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def _answer(*probabilities: float, model: str = "jev-1.13.0", questions: tuple[str, ...] = (_PRESCREEN_Q,)) -> dict:
    return {"model": model, "answers": {question: {"type": "noul", "noul": probability} for question, probability in zip(questions, probabilities)}}


def _prescreen(server: _Server, *, mode: str = MODE_SHADOW, **kwargs) -> TypeSafeMemoryPrescreen:
    kwargs.setdefault("skip_threshold", 0.2)
    kwargs.setdefault("max_state_chars", 6000)
    kwargs.setdefault("transport_factory", server.transport)
    return TypeSafeMemoryPrescreen(mode=mode, api_key=_API_KEY, **kwargs)


def _classifier(server: _Server, *, mode: str = MODE_HINTS, **kwargs) -> TypeSafeSignalClassifier:
    kwargs.setdefault("hint_threshold", 0.5)
    kwargs.setdefault("max_state_chars", 6000)
    kwargs.setdefault("transport_factory", server.transport)
    return TypeSafeSignalClassifier(mode=mode, api_key=_API_KEY, **kwargs)


def _combined_judge(server: _Server, *, prescreen_mode: str = MODE_ENFORCE, classifier_mode: str = MODE_HINTS, combine: str = "auto", **overrides) -> MemorySignalCoordinator:
    """One judge over both sides sharing a single transport factory.

    The transport factory is part of the sharing identity (§2.2.5), so both sides
    must be handed the *same* factory object for a shared request.
    """
    factory = server.transport  # one bound method object: sharing identity must match (§2.2.5)
    return _judge(
        _prescreen(server, mode=prescreen_mode, transport_factory=factory, **overrides),
        prescreen_mode=prescreen_mode,
        classifier=_classifier(server, mode=classifier_mode, transport_factory=factory),
        classifier_mode=classifier_mode,
        combine=combine,
    )


def _judge(prescreen=None, prescreen_mode: str = MODE_SHADOW, classifier=None, classifier_mode: str = MODE_HINTS, combine: str = "auto") -> MemorySignalCoordinator:
    return MemorySignalCoordinator(prescreen=prescreen, prescreen_mode=prescreen_mode, classifier=classifier, classifier_mode=classifier_mode, combine=combine)


def _context(text: str = _KEEPING_TEXT, **overrides) -> MemoryBatchContext:
    context = {"batch_text": text, "digest": "digest-1"}
    context.update(overrides)
    return MemoryBatchContext(**context)


# --- the updater harness ---------------------------------------------------


class _FakeLLM:
    """Returns a fixed extraction payload and records the prompts it was given."""

    def __init__(self, payload: str | None = None) -> None:
        self.payload = payload or '{"user":{},"history":{},"newFacts":[],"factsToRemove":[]}'
        self.prompts: list[object] = []

    def invoke(self, prompt, config=None):
        self.prompts.append(prompt)
        return type("R", (), {"content": self.payload})()

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _memory() -> dict[str, object]:
    return {
        "version": "1.0",
        "revision": 0,
        "lastUpdated": "",
        "user": {section: {"summary": "", "updatedAt": ""} for section in ("workContext", "personalContext", "topOfMind", "cognitiveStyle")},
        "history": {section: {"summary": "", "updatedAt": ""} for section in ("recentMonths", "earlierContext", "longTermBackground")},
        "facts": [],
    }


def _fact(index: int, *, confidence: float) -> dict[str, object]:
    return {"id": f"fact_{index}", "content": f"Existing durable fact {index}", "category": "context", "confidence": confidence, "createdAt": "2026-01-01T00:00:00Z", "source": "t"}


def _memory_with_facts(facts: list[dict[str, object]]) -> dict[str, object]:
    memory = _memory()
    memory["facts"] = copy.deepcopy(facts)
    return memory


class _Storage(MemoryStorage):
    def __init__(self) -> None:
        self.memory = _memory()
        self.saves = 0

    def load(self, agent_name=None, *, user_id=None):
        return copy.deepcopy(self.memory)

    def reload(self, agent_name=None, *, user_id=None):
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data, agent_name=None, *, user_id=None, expected_revision=None):
        self.memory = copy.deepcopy(memory_data)
        self.saves += 1
        return True


def _updater(*, judge=None, llm=None, recorded: list | None = None, **config_overrides) -> MemoryUpdater:
    config = DeerMemConfig()
    # DeerMem defaults staleness_review_enabled=True, and L8 then removes the
    # pre-screen's eligibility entirely (a skip would also skip that batch's
    # maintenance review). Tests that need judging mirror a deployment which
    # allows skipping; the L8 cases flip it back on explicitly.
    config_overrides.setdefault("staleness_review_enabled", False)
    for key, value in config_overrides.items():
        setattr(config, key, value)
    if judge is not None:
        setattr(config, _JUDGE_HOOK, judge)
    if recorded is not None:
        config.extraction_callback = recorded.append
    return MemoryUpdater(config, _Storage(), llm or _FakeLLM())


def _conversation(text: str = _KEEPING_TEXT):
    return [HumanMessage(content=text), AIMessage(content="Understood.")]


def _watermark(updater: MemoryUpdater) -> tuple | None:
    return updater._watermarks.get(("thread-1", "user-1", None))


# --- L1: no judge, no change ----------------------------------------------


class TestNoJudge:
    def test_an_unconfigured_deployment_extracts_and_sends_nothing(self):
        server = _Server()
        llm = _FakeLLM('{"user":{},"history":{},"newFacts":[{"content":"User prefers dark mode","category":"preference","confidence":0.9,"scope":"user","durability":"durable","authority":"descriptive"}],"factsToRemove":[]}')
        updater = _updater(judge=None, llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 1
        assert server.count == 0
        assert [fact["content"] for fact in updater._storage.memory["facts"]] == ["User prefers dark mode"]

    def test_no_judge_means_no_judge_payload_in_the_metrics(self):
        recorded: list = []
        updater = _updater(recorded=recorded)

        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1")

        assert recorded
        assert "prescreen" not in recorded[0]
        assert "signal_classification" not in recorded[0]


# --- phase A eligibility (L3 / L4 / L7 / L8 / L5) -------------------------


class TestEligibility:
    def test_deterministic_signals_force_extraction_without_a_request(self):
        # The updater re-detects signals on the post-watermark feed, so L3 reads
        # the same set the extraction hints use -- not the admission-time set the
        # queue already consumed.
        text = "No, that's wrong - use tabs not spaces"
        server = _Server()
        llm = _FakeLLM()
        recorded: list = []
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm, recorded=recorded)

        assert updater.update_memory(_conversation(text), thread_id="thread-1", user_id="user-1") is True

        assert server.count == 0, "L3: deterministic signals answer for the pre-screen"
        assert llm.calls == 1
        # §5 counts local fallbacks, so the reason has to reach the extraction record
        # the shadow evaluation reads.
        assert recorded[0]["prescreen"]["fallback_reason"] == "deterministic_signals"

    def test_the_emergency_flush_path_never_judges(self):
        server = _Server()
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1", bypass_watermark=True) is True

        assert server.count == 0, "L4: the batch is about to be removed by summarization"
        assert llm.calls == 1
        assert _watermark(updater) is None, "the emergency path never advances the conversation watermark"

    def test_the_shutdown_drain_never_judges(self):
        server = _Server()
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1", judge=False) is True

        assert server.count == 0, "L7: the drain budget belongs to persistence"
        assert llm.calls == 1

    @pytest.mark.parametrize("flag", ["staleness_review_enabled", "consolidation_enabled"])
    def test_maintenance_review_disables_skipping(self, flag):
        server = _Server()
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm, **{flag: True})

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert server.count == 0, "L8: a skip would also skip that batch's maintenance review"
        assert llm.calls == 1

    def test_a_cjk_batch_is_limited_by_characters_not_wire_bytes(self):
        """Shared-client design §2.4: the limit stays a character count over the judged text."""
        text = "我们决定用标签" * 5  # 35 characters, 105 UTF-8 bytes
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9)))
        judge = _judge(_prescreen(server, mode=MODE_ENFORCE, max_state_chars=len(text)), prescreen_mode=MODE_ENFORCE)

        verdict = judge.judge(_context(text))

        assert verdict.payload["prescreen"]["fallback_reason"] is None, "the batch fits its character limit"
        assert server.count == 1, "counting UTF-8 bytes would have refused this request three times too early"

    def test_an_over_limit_batch_extracts_without_a_request_or_truncation(self):
        server = _Server()
        llm = _FakeLLM()
        text = "x" * 4000
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE, max_state_chars=10), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(text), thread_id="thread-1", user_id="user-1") is True

        assert server.count == 0, "L5: no request, extract as usual"
        assert llm.calls == 1
        # No second truncation: the extractor sees exactly the formatter's output.
        formatted = format_conversation_for_update(_conversation(text))
        prompt_text = "\n".join(str(getattr(message, "content", message)) for message in llm.prompts[0])
        assert formatted in prompt_text


# --- L2: every failure direction extracts ---------------------------------


class TestFailureDirection:
    @pytest.mark.parametrize(
        "responder",
        [
            lambda request: httpx.Response(200, content=b"not json at all"),
            lambda request: httpx.Response(200, content=b'{"model": "jev-1.13.0"}'),
            lambda request: httpx.Response(200, json=_answer("not a number")),
            lambda request: httpx.Response(500, json={}),
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request)),
        ],
    )
    def test_a_failing_verdict_extracts_as_usual(self, responder):
        server = _Server(responder)
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE, retry_backoff=0.0), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 1, "L2: pre-screening never loses a memory"
        assert _watermark(updater) is not None, "extraction success still advances the watermark"

    def test_a_provider_exception_extracts_as_usual(self):
        class _Exploding:
            name = "exploding"

            def decide(self, request):
                raise RuntimeError("provider bug")

            def release_policy_parameters(self):
                return {}

        llm = _FakeLLM()
        updater = _updater(judge=_judge(_Exploding(), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 1


# --- modes: shadow / enforce ----------------------------------------------


class TestShadowAndEnforce:
    def test_shadow_records_the_verdict_and_extracts_anyway(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        recorded: list = []
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_SHADOW), prescreen_mode=MODE_SHADOW), llm=llm, recorded=recorded)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 1, "shadow changes nothing"
        assert _watermark(updater) is not None, "the watermark advances on extraction success, as today"
        record = recorded[0]["prescreen"]
        assert (record["mode"], record["verdict"], record["probability"]) == (MODE_SHADOW, "skip", 0.01)
        assert record["digest"] and record["skip_threshold"] == 0.2

    def test_enforce_skip_drops_the_call_and_advances_the_watermark(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        recorded: list = []
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm, recorded=recorded)

        assert updater.update_memory(_conversation(_CHATTER_TEXT), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 0, "enforce + skip saves the extraction call"
        assert _watermark(updater) is not None, "the batch is consumed, so it is not re-judged every turn"
        assert recorded, "a skip still emits its record"
        assert recorded[0]["success"] is True and recorded[0]["token_usage"] is None, "no LLM call, so no token usage, but the record is still emitted"
        assert "mutations_accepted" not in recorded[0], "no apply ran"
        assert recorded[0]["prescreen"]["verdict"] == "skip"

    def test_enforce_extract_matches_today(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.99)))
        llm = _FakeLLM()
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=llm)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert llm.calls == 1
        assert _watermark(updater) is not None

    def test_threshold_boundary_extracts(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.2)))
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE, skip_threshold=0.2), prescreen_mode=MODE_ENFORCE), llm=_FakeLLM())

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert updater._llm.calls == 1, "p == skip_threshold extracts (when unsure, extract)"

    def test_an_extraction_failure_leaves_the_watermark_alone(self):
        """The fourth watermark branch: a failed extraction advances nothing, so the
        batch is re-fed next turn -- and the judge's verdict did not consume it
        either (it said extract, and extraction did not succeed)."""
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.99)))

        class _ExplodingLLM:
            def invoke(self, prompt, config=None):
                raise RuntimeError("extraction provider down")

        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=_ExplodingLLM())

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is False
        assert _watermark(updater) is None

    def test_the_cache_makes_the_second_batch_free(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        recorded: list = []
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE), llm=_FakeLLM(), recorded=recorded)

        updater.update_memory(_conversation(_CHATTER_TEXT), thread_id="thread-1", user_id="user-1")
        updater.update_memory(_conversation(_CHATTER_TEXT), thread_id="thread-2", user_id="user-2")

        assert server.count == 1, "same digest, same verdict"
        assert recorded[0]["prescreen"]["cached"] is False
        assert recorded[1]["prescreen"]["cached"] is True, "a cache hit is recorded as one"

    def test_an_expired_cache_entry_is_requested_again(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        updater = _updater(judge=_judge(_prescreen(server, mode=MODE_ENFORCE, cache_ttl_seconds=0.01), prescreen_mode=MODE_ENFORCE), llm=_FakeLLM())

        updater.update_memory(_conversation(_CHATTER_TEXT), thread_id="thread-1", user_id="user-1")
        import time

        time.sleep(0.05)
        updater.update_memory(_conversation(_CHATTER_TEXT), thread_id="thread-2", user_id="user-2")

        assert server.count == 2


# --- signal classification: hints, per-question failure, the veto ---------


class TestSignalClassification:
    def test_hints_are_merged_into_the_extraction_prompt(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9, 0.1, questions=(QUESTION_AFFIRMATION, QUESTION_NEGATION))))
        recorded: list = []
        llm = _FakeLLM()
        updater = _updater(judge=_judge(classifier=_classifier(server), classifier_mode=MODE_HINTS), llm=llm, recorded=recorded)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        prompt_text = "\n".join(str(getattr(message, "content", message)) for message in llm.prompts[0])
        assert "Positive reinforcement signals were detected" in prompt_text
        assert "Explicit correction signals were detected" not in prompt_text, "negation stayed below the threshold"
        assert recorded[0]["signal_classification"]["labels"] == [LABEL_REINFORCEMENT]

    def test_a_failed_direction_keeps_the_other_one(self):
        server = _Server(lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": "not a number"}}}))
        recorded: list = []
        updater = _updater(judge=_judge(classifier=_classifier(server), classifier_mode=MODE_HINTS), recorded=recorded)

        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1")

        record = recorded[0]["signal_classification"]
        assert record["labels"] == [LABEL_REINFORCEMENT], "failure is counted per question, never per side"
        assert LABEL_CORRECTION not in record["probabilities"]

    def test_a_model_hint_vetoes_a_skip_only_under_enforce(self):
        answering = _Server(
            lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.01}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})
        )
        recorded: list = []
        llm = _FakeLLM()
        updater = _updater(judge=_combined_judge(answering), llm=llm, recorded=recorded)

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is True

        assert answering.count == 1, "one shared request serves both sides"
        assert set(answering.bodies()[0]["questions"]) == {_PRESCREEN_Q, QUESTION_AFFIRMATION, QUESTION_NEGATION}
        assert llm.calls == 1, "the veto recovered the extraction"
        assert _watermark(updater) is not None
        assert recorded[0]["skip_vetoed_by_model_signal"] is True

    def test_a_hint_does_not_veto_without_enforce(self):
        answering = _Server(lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.01}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}}}))
        recorded: list = []
        llm = _FakeLLM()
        updater = _updater(judge=_combined_judge(answering, prescreen_mode=MODE_SHADOW), llm=llm, recorded=recorded)

        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1")

        assert llm.calls == 1, "shadow has no skip, so there is nothing to veto (S11)"
        assert "skip_vetoed_by_model_signal" not in recorded[0]

    def test_classifier_only_asks_its_own_questions(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9, 0.1, questions=(QUESTION_AFFIRMATION, QUESTION_NEGATION))))
        updater = _updater(judge=_judge(classifier=_classifier(server), classifier_mode=MODE_HINTS))

        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1")

        assert set(server.bodies()[0]["questions"]) == {QUESTION_AFFIRMATION, QUESTION_NEGATION}


# --- the coordinator's contract (unit level) ------------------------------


class TestCoordinatorRules:
    def test_both_off_is_a_no_op(self):
        verdict = _judge().judge(_context())

        assert verdict.payload == {}
        assert verdict.skip is False and verdict.hints == frozenset()

    def test_combine_never_sends_two_requests(self):
        server = _Server(
            lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})
        )
        judge = _combined_judge(server, combine=COMBINE_NEVER)

        judge.judge(_context())

        assert server.count == 2, "each side keeps its own request and its own cache"

    def test_a_limit_mismatch_splits_the_requests(self):
        server = _Server(
            lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})
        )
        factory = server.transport
        judge = _judge(_prescreen(server, mode=MODE_ENFORCE, transport_factory=factory), prescreen_mode=MODE_ENFORCE, classifier=_classifier(server, max_state_chars=7000, transport_factory=factory), classifier_mode=MODE_HINTS)

        judge.judge(_context())

        assert server.count == 2, "auto separates rather than silently widening the stricter side's limit"

    def test_combine_always_refuses_a_mismatched_pair(self):
        server = _Server()
        factory = server.transport
        with pytest.raises(ValueError, match="combine='always'"):
            _judge(
                _prescreen(server, mode=MODE_ENFORCE, transport_factory=factory),
                prescreen_mode=MODE_ENFORCE,
                classifier=_classifier(server, max_state_chars=7000, transport_factory=factory),
                classifier_mode=MODE_HINTS,
                combine=COMBINE_ALWAYS,
            )

    def test_a_full_cache_hit_sends_nothing(self):
        server = _Server(
            lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})
        )
        judge = _combined_judge(server)

        first = judge.judge(_context())
        second = judge.judge(_context())

        assert server.count == 1, "the second round is a full hit"
        assert first.payload["prescreen"]["cached"] is False
        assert second.payload["prescreen"]["cached"] is True
        assert second.payload["signal_classification"]["labels"] == [LABEL_REINFORCEMENT]

    def test_a_partial_response_is_topped_up_into_the_same_bucket(self):
        """One direction missing in a response is asked again next time; the other is not."""
        bodies: list[dict] = []

        def responder(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            questions = bodies[-1]["questions"]
            answers = {question: {"type": "noul", "noul": 0.9} for question in questions if question != QUESTION_NEGATION}
            return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})

        server = _Server(responder)
        judge = _combined_judge(server)

        judge.judge(_context())
        second = judge.judge(_context())

        assert set(bodies[0]["questions"]) == {_PRESCREEN_Q, QUESTION_AFFIRMATION, QUESTION_NEGATION}, "the combined request carries every side's questions"
        assert set(bodies[1]["questions"]) == {QUESTION_NEGATION}, "only the unanswered question is retried"
        assert second.payload["signal_classification"]["labels"] == [LABEL_REINFORCEMENT], "the cached direction is reused"

    def test_the_shared_bucket_answers_before_eligibility_narrows_the_question_set(self):
        """§2.2.3 step 1: the key holds the full logical set, so an ineligible side costs no request."""
        server = _Server(
            lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})
        )
        judge = _combined_judge(server)

        judge.judge(_context())
        signalled = judge.judge(_context(signals=frozenset({"correction"})))

        assert server.count == 1, "the answers were already bucketed for this digest"
        assert signalled.payload["prescreen"]["fallback_reason"] == "deterministic_signals"
        assert signalled.payload["signal_classification"]["labels"] == [LABEL_REINFORCEMENT], "the still-eligible side consumes the held answers"

    def test_an_enabled_side_records_why_it_could_not_judge(self):
        """§5 counts local fallbacks, so a round with no eligible side still emits its record."""
        server = _Server()
        judge = _judge(_prescreen(server, mode=MODE_ENFORCE), prescreen_mode=MODE_ENFORCE)

        verdict = judge.judge(_context(signals=frozenset({"correction"})))

        assert server.count == 0
        assert verdict.decided is True
        assert verdict.payload["prescreen"]["verdict"] is None
        assert verdict.payload["prescreen"]["fallback_reason"] == "deterministic_signals"
        assert verdict.skip is False

    def test_a_reused_verdict_is_not_reported_as_a_network_sample_when_the_other_side_fetches(self):
        """Per-answer provenance: a verdict reused from the bucket stays a cache hit.

        Rounds differ in which questions the network answered. When the pre-screen
        answer is already held and only the classifier question is fetched, stamping
        the reused verdict ``cached=False`` (with the new response's model) makes the
        shadow evaluation count it as another network sample, inflating the
        confidence-bound denominator.
        """
        bodies: list[dict] = []

        def responder(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            if len(bodies) == 1:
                return httpx.Response(200, json={"model": "jev-1.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}}})
            return httpx.Response(200, json={"model": "jev-2.0", "answers": {question: {"type": "noul", "noul": 0.9} for question in body["questions"]}})

        server = _Server(responder)
        judge = _combined_judge(server)

        first = judge.judge(_context())
        second = judge.judge(_context())

        assert first.payload["prescreen"]["cached"] is False, "the first round fetched the pre-screen answer"
        assert set(bodies[1]["questions"]) == {QUESTION_AFFIRMATION, QUESTION_NEGATION}, "only the missing classifier questions are asked"
        assert second.payload["prescreen"]["cached"] is True, "the pre-screen answer came from the bucket"
        assert second.payload["prescreen"]["model"] == "jev-1.0", "the reused verdict keeps the model that produced it"
        assert second.payload["signal_classification"]["cached"] is False, "the classifier answer was fetched this round"

    def test_a_full_cache_hit_reports_each_answers_original_model(self):
        """Model provenance is per answer, not per bucket.

        Filling a bucket with a newer model must not re-attribute the answers it
        already held, or a later full cache hit audits the older model's verdict
        under the newer model's name.
        """
        bodies: list[dict] = []

        def responder(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            if len(bodies) == 1:
                return httpx.Response(200, json={"model": "jev-A", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.9}}})
            return httpx.Response(200, json={"model": "jev-B", "answers": {QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}})

        server = _Server(responder)
        judge = _combined_judge(server)

        judge.judge(_context())  # buckets the pre-screen answer, served by jev-A
        judge.judge(_context())  # fills the classifier answers, served by jev-B
        third = judge.judge(_context())  # full cache hit, no request

        assert server.count == 2, "the third round is a full cache hit"
        assert third.payload["prescreen"]["cached"] is True and third.payload["prescreen"]["model"] == "jev-A"
        assert third.payload["signal_classification"]["cached"] is True and third.payload["signal_classification"]["model"] == "jev-B"

    def test_per_side_limits_are_enforced_separately(self):
        judged_chars = len(_KEEPING_TEXT)  # the limit is a character count, not the wire size (design §2.4)
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9, 0.1, questions=(QUESTION_AFFIRMATION, QUESTION_NEGATION))))
        factory = server.transport
        judge = _judge(
            _prescreen(server, mode=MODE_ENFORCE, max_state_chars=judged_chars - 1, transport_factory=factory),
            prescreen_mode=MODE_ENFORCE,
            classifier=_classifier(server, max_state_chars=judged_chars + 100, transport_factory=factory),
            classifier_mode=MODE_HINTS,
        )

        verdict = judge.judge(_context())

        assert verdict.payload["prescreen"]["fallback_reason"] == "over_limit"
        assert verdict.payload["signal_classification"]["fallback_reason"] is None
        assert set(server.bodies()[0]["questions"]) == {QUESTION_AFFIRMATION, QUESTION_NEGATION}, "the side under its limit still asks"

    def test_only_the_side_over_its_limit_falls_back(self):
        """Scenario row 11: the classifier is over *its* limit while the pre-screen is not."""
        judged_chars = len(_KEEPING_TEXT)  # the limit is a character count, not the wire size (design §2.4)
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        factory = server.transport
        judge = _judge(
            _prescreen(server, mode=MODE_ENFORCE, max_state_chars=judged_chars + 100, transport_factory=factory),
            prescreen_mode=MODE_ENFORCE,
            classifier=_classifier(server, max_state_chars=judged_chars - 1, transport_factory=factory),
            classifier_mode=MODE_HINTS,
        )

        verdict = judge.judge(_context())

        assert verdict.payload["signal_classification"]["fallback_reason"] == "over_limit"
        assert verdict.payload["prescreen"]["fallback_reason"] is None
        assert set(server.bodies()[0]["questions"]) == {_PRESCREEN_Q}, "only the eligible side asks"

    def test_the_veto_requires_both_conditions(self):
        server = _Server(lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {_PRESCREEN_Q: {"type": "noul", "noul": 0.01}, QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}}}))
        hints_only = _judge(classifier=_classifier(server, mode=MODE_HINTS), classifier_mode=MODE_HINTS)
        shadow_classifier = _combined_judge(server, classifier_mode="shadow")

        assert hints_only.judge(_context()).skip is False, "no pre-screen enforce, no skip to veto"
        shadowed = shadow_classifier.judge(_context())
        assert shadowed.skip is True and shadowed.vetoed_by_model_signal is False, "a shadow classifier records only, so the skip stands"
        assert shadowed.hints == frozenset(), "shadow hints are not merged"

    def test_release_policy_parameters_carry_no_credential(self):
        server = _Server()
        declared = _combined_judge(server).release_policy_parameters()

        serialized = json.dumps(declared)
        assert _API_KEY not in serialized
        assert "api_key_env" not in serialized
        assert declared["combine"] == "auto"


# --- the adapters' own contracts ------------------------------------------


class TestAdapterContracts:
    def test_the_prescreen_decides_without_a_coordinator(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        decision = _prescreen(server).decide(MemoryPrescreenRequest(batch_text=_CHATTER_TEXT, digest="d1"))

        assert decision is not None and decision.verdict == "skip" and decision.cached is False
        assert _prescreen(server).decide(MemoryPrescreenRequest(batch_text=_CHATTER_TEXT, digest="d1")) is not None

    def test_the_prescreen_sends_only_the_batch_text(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9)))
        _prescreen(server).decide(MemoryPrescreenRequest(batch_text=_KEEPING_TEXT, digest="d1", signals=frozenset({"correction"}), user_id="u1"))

        body = server.bodies()[0]
        assert body["state"] == {"conversation_tail": {"text": _KEEPING_TEXT}}, "no memory, no signals, no tool arguments"
        assert set(body["questions"]) == {_PRESCREEN_Q}

    def test_a_recordable_model_token_is_bounded(self):
        hostile = "rm -rf /tmp/secret " + "x" * 4000
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01, model=hostile)))
        decision = _prescreen(server).decide(MemoryPrescreenRequest(batch_text=_CHATTER_TEXT, digest="d1"))

        assert decision is not None
        assert decision.model.startswith("unrecorded:sha256:")
        assert len(decision.model) == len("unrecorded:sha256:") + 16
        assert hostile not in decision.model

    def test_the_classifier_maps_both_directions(self):
        server = _Server(lambda request: httpx.Response(200, json=_answer(0.9, 0.9, questions=(QUESTION_AFFIRMATION, QUESTION_NEGATION))))
        decision = _classifier(server).decide(MemorySignalRequest(batch_text=_KEEPING_TEXT, digest="d1"))

        assert decision is not None and decision.labels == frozenset({LABEL_REINFORCEMENT, LABEL_CORRECTION})

    def test_a_missing_direction_is_asked_again_rather_than_read_as_a_hit(self):
        """S18: a partial answer is not a full hit, and the answered direction is still consumed."""
        bodies: list[dict] = []

        def responder(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            answers = {question: {"type": "noul", "noul": 0.9} for question in bodies[-1]["questions"] if question != QUESTION_NEGATION}
            return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})

        server = _Server(responder)
        classifier = _classifier(server)
        request = MemorySignalRequest(batch_text=_KEEPING_TEXT, digest="d1")

        first = classifier.decide(request)
        second = classifier.decide(request)

        assert set(bodies[0]["questions"]) == {QUESTION_AFFIRMATION, QUESTION_NEGATION}
        assert set(bodies[1]["questions"]) == {QUESTION_NEGATION}, "the unanswered direction is sent again"
        assert first is not None and second is not None
        assert second.labels == frozenset({LABEL_REINFORCEMENT}), "the cached direction is reused"

    def test_a_retry_with_no_valid_answers_keeps_the_cached_answers_model(self):
        """A retry that validates nothing supplied none of the consumed evidence.

        The bucket's answer was served by the first model; reporting the empty
        retry's model would attribute the verdict to a model that returned no
        usable answer, corrupting the classification audit record.
        """
        bodies: list[dict] = []

        def responder(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                return httpx.Response(200, json={"model": "jev-A", "answers": {QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}}})
            return httpx.Response(200, json={"model": "jev-B", "answers": {}})

        server = _Server(responder)
        classifier = _classifier(server)
        request = MemorySignalRequest(batch_text=_KEEPING_TEXT, digest="d1")

        first = classifier.decide(request)
        second = classifier.decide(request)

        assert first is not None and first.cached is False and first.model == "jev-A"
        assert set(bodies[1]["questions"]) == {QUESTION_NEGATION}, "only the missing direction is retried"
        assert second is not None and second.cached is True
        assert second.model == "jev-A", "the empty retry's model must not replace the cached answer's model"
        assert second.labels == first.labels

    def test_invalid_configuration_fails_at_construction(self):
        with pytest.raises(ValueError, match="skip_threshold"):
            TypeSafeMemoryPrescreen(mode=MODE_SHADOW, api_key=_API_KEY, skip_threshold=1.5)
        with pytest.raises(ValueError, match="hint_threshold"):
            TypeSafeSignalClassifier(mode=MODE_HINTS, api_key=_API_KEY, hint_threshold=True)
        with pytest.raises(ValueError, match="max_state_chars"):
            TypeSafeMemoryPrescreen(mode=MODE_SHADOW, api_key=_API_KEY, max_state_chars=0)
        with pytest.raises(ValueError, match="mode"):
            TypeSafeMemoryPrescreen(mode="sometimes", api_key=_API_KEY)

    def test_mode_off_resolves_nothing(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        assert resolve_memory_prescreen(mode=MODE_OFF, use=_PRESCREEN) is None
        assert resolve_memory_signal_classifier(mode=MODE_OFF, use=_CLASSIFIER) is None

    def test_an_enabled_mode_without_a_usable_class_path_fails(self):
        with pytest.raises(ValueError, match="needs 'use'"):
            resolve_memory_prescreen(mode=MODE_SHADOW, use=None)
        with pytest.raises(ValueError, match="could not be resolved"):
            resolve_memory_prescreen(mode=MODE_SHADOW, use="not.a.real.module:Cls")


# --- the audit metric ------------------------------------------------------


class TestMutationsAccepted:
    @pytest.mark.parametrize(
        ("payload", "expected", "signal"),
        [
            ('{"user":{},"history":{},"newFacts":[{"content":"User prefers dark mode","category":"preference","confidence":0.9,"scope":"user","durability":"durable","authority":"descriptive"}],"factsToRemove":[]}', 1, frozenset()),
            ('{"user":{"workContext":{"shouldUpdate":true,"summary":"Works on memory","scope":"user","durability":"durable","authority":"descriptive"}},"history":{},"newFacts":[],"factsToRemove":[]}', 0, frozenset()),
        ],
    )
    def test_only_real_mutations_count(self, payload, expected, signal):
        recorded: list = []
        updater = _updater(llm=_FakeLLM(payload), recorded=recorded)

        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1", signals=signal)

        assert recorded[0]["mutations_accepted"] == expected, "a summary rewrite is not a kept memory"

    def test_confirmation_and_removal_count(self):
        memory = _memory()
        memory["facts"] = [
            {"id": "fact_a", "content": "User prefers dark mode", "category": "preference", "confidence": 0.9, "createdAt": "2026-01-01T00:00:00Z", "source": "t"},
            {"id": "fact_b", "content": "Old context", "category": "context", "confidence": 0.8, "createdAt": "2026-01-01T00:00:00Z", "source": "t"},
        ]
        storage = _Storage()
        storage.memory = memory
        config = DeerMemConfig()
        config.fact_eviction_policy = "hybrid-v1"
        llm = _FakeLLM('{"user":{},"history":{},"newFacts":[],"factsToReinforce":[{"id":"fact_a","scope":"user","reason":"explicit confirmation"}],"factsToRemove":[{"id":"fact_b","scope":"user","reason":"explicit retraction"}]}')
        metrics: dict = {}
        updater = MemoryUpdater(config, storage, llm)

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(llm.payload), metrics=metrics, signals=frozenset({"reinforcement"}), user_id="user-1")

        assert result["facts"][0]["confirmationCount"] == 1
        assert "fact_b" not in {fact["id"] for fact in result["facts"]}
        assert metrics["mutations_accepted"] == 2

    def test_a_capacity_evicted_new_fact_is_not_an_accepted_mutation(self):
        """A proposal that passes the confidence gate but is evicted leaves the facts unchanged.

        Reporting the append would make a shadow skip look like a lost memory:
        ``eval_memory_prescreen`` reads any positive ``mutations_accepted`` on a
        skip as a miss, so the counter must track the persistent fact set.
        """
        existing = [_fact(index, confidence=0.9) for index in range(10)]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "A brand new fact that capacity will discard", "category": "context", "confidence": 0.8, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), max_facts=10)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert [fact["id"] for fact in result["facts"]] == [fact["id"] for fact in existing], "the proposal was evicted, so the persistent set is unchanged"
        assert metrics["mutations_accepted"] == 0, "an evicted proposal did not land"

    def test_a_surviving_new_fact_at_capacity_is_counted(self):
        """The counter still reports a genuine addition when the trim actually runs."""
        existing = [_fact(index, confidence=0.75) for index in range(10)]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "A higher-confidence fact that survives the trim", "category": "context", "confidence": 0.95, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), max_facts=10)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        contents = {fact["content"] for fact in result["facts"]}
        assert len(result["facts"]) == 10
        assert "A higher-confidence fact that survives the trim" in contents
        assert metrics["mutations_accepted"] == 1, "the surviving addition landed"

    def test_nonexistent_removal_and_reinforcement_targets_do_not_count(self):
        """A scope-valid op on an id that does not exist changes nothing.

        Counting it would report an accepted mutation that never landed, and the
        pre-screen evaluation reads any positive count on a skip as a lost
        memory.
        """
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [],
                "factsToReinforce": [{"id": "does-not-exist", "scope": "user", "reason": "explicit confirmation"}],
                "factsToRemove": [{"id": "also-missing", "scope": "user", "reason": "explicit retraction"}],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), fact_eviction_policy="hybrid-v1")
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, signals=frozenset({"reinforcement"}), user_id="user-1")

        assert result["facts"] == []
        assert metrics["mutations_accepted"] == 0, "neither target existed, so nothing landed"

    def test_a_failed_persist_does_not_publish_the_accepted_mutation_counter(self):
        """A rejected commit persisted nothing, so it must be censored, not scored.

        The apply counted a mutation, but ``save`` refused the commit; publishing the
        counter would let the shadow evaluation read a failed extraction as a lost
        memory instead of a missing sample (persistent-mutation contract).
        """
        recorded: list = []
        payload = '{"user":{},"history":{},"newFacts":[{"content":"User prefers dark mode","category":"preference","confidence":0.9,"scope":"user","durability":"durable","authority":"descriptive"}],"factsToRemove":[]}'
        updater = _updater(llm=_FakeLLM(payload), recorded=recorded)
        updater._storage.save = lambda *args, **kwargs: False  # persistence rejects the commit

        assert updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1") is False

        assert recorded and recorded[0]["success"] is False
        assert "mutations_accepted" not in recorded[0], "nothing persisted, so nothing was accepted"

    def test_a_persisted_near_duplicate_confidence_raise_counts(self):
        """A merge that raises an existing fact's confidence persisted a change.

        Counting only appends made a dedup-only batch look like it wrote nothing,
        so a shadow skip for that batch read as a safe saving instead of lost
        information.
        """
        existing = [{"id": "fact_existing", "content": "User prefers dark mode", "category": "preference", "confidence": 0.5, "createdAt": "2026-01-01T00:00:00Z", "source": "old"}]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "User prefers dark mode always", "category": "preference", "confidence": 0.9, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), fact_dedup_enabled=True)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert len(result["facts"]) == 1, "the proposal merged into the existing fact"
        assert result["facts"][0]["confidence"] == 0.9
        assert metrics["mutations_accepted"] == 1, "the merge persisted a confidence change"

    def test_a_no_op_near_duplicate_merge_does_not_count(self):
        """A merge whose proposed confidence is not higher changes nothing."""
        existing = [{"id": "fact_existing", "content": "User prefers dark mode", "category": "preference", "confidence": 0.95, "createdAt": "2026-01-01T00:00:00Z", "source": "old"}]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "User prefers dark mode always", "category": "preference", "confidence": 0.8, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), fact_dedup_enabled=True)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert result["facts"][0]["confidence"] == 0.95, "an unconfirmed restatement never lowers the stored confidence"
        assert metrics["mutations_accepted"] == 0, "a no-op merge persisted nothing"

    def test_a_merge_target_evicted_by_capacity_does_not_count(self):
        """A changed merge target counts only if it survives, like an appended fact."""
        existing = [{"id": "fact_existing", "content": "User prefers dark mode", "category": "preference", "confidence": 0.5, "createdAt": "2026-01-01T00:00:00Z", "source": "old"}]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [
                    {"content": "User prefers dark mode always", "category": "preference", "confidence": 0.9, "scope": "user", "durability": "durable", "authority": "descriptive"},
                    {"content": "User ships on Fridays", "category": "context", "confidence": 0.99, "scope": "user", "durability": "durable", "authority": "descriptive"},
                ],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), fact_dedup_enabled=True, max_facts=1)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert [fact["content"] for fact in result["facts"]] == ["User ships on Fridays"], "capacity kept only the highest-confidence fact"
        assert metrics["mutations_accepted"] == 1, "only the surviving new fact counts; the evicted merge target's change was discarded"

    def test_a_persisted_merge_into_an_id_less_legacy_fact_counts(self):
        """An id-less legacy target cannot be matched by id, so it is tracked by identity.

        Otherwise the same undercount returns for hand-edited/legacy facts, which
        the staleness path already tolerates.
        """
        existing = [{"content": "User prefers dark mode", "category": "preference", "confidence": 0.5, "createdAt": "2026-01-01T00:00:00Z", "source": "old"}]
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "User prefers dark mode always", "category": "preference", "confidence": 0.9, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload), fact_dedup_enabled=True)
        updater._storage.memory = _memory_with_facts(existing)
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert len(result["facts"]) == 1 and "id" not in result["facts"][0], "the target is an id-less legacy fact"
        assert result["facts"][0]["confidence"] == 0.9
        assert metrics["mutations_accepted"] == 1, "the merge into the id-less target persisted a change"

    def test_an_upload_event_fact_discarded_at_finalization_does_not_count(self):
        """A fact accepted by the apply but scrubbed before persistence has not landed.

        Upload events are session-scoped and scrubbed on the way to storage, so the
        shadow evaluation must not read the rejected proposal as a lost memory.
        """
        payload = json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "User uploaded a test file for verification purposes", "category": "context", "confidence": 0.9, "scope": "user", "durability": "durable", "authority": "descriptive"}],
                "factsToRemove": [],
            }
        )
        updater = _updater(llm=_FakeLLM(payload))
        metrics: dict = {}

        result = updater._apply_updates(updater.get_memory_data(user_id="user-1"), json.loads(payload), metrics=metrics, user_id="user-1")

        assert result["facts"] == [], "the upload-event fact is scrubbed before persistence"
        assert metrics["mutations_accepted"] == 0, "a proposal removed before persistence did not land"


def _patterns_dir(tmp_path, **patterns: str) -> pathlib.Path:
    """A complete custom pattern set: ``detect_signals`` loads every class file.

    ``patterns_dir`` must hold all of them, so a test that overrides one class
    writes an inert pattern for the rest.
    """
    directory = tmp_path / "patterns"
    directory.mkdir(exist_ok=True)
    for name in ("correction", "reinforcement", "preference", "identity", "goal", "decision"):
        (directory / f"{name}.yaml").write_text(patterns.get(name, "- pattern: 'never matches anything'\n"), encoding="utf-8")
    return directory


# --- the production wiring: memory config -> host hooks -> DeerMem ---------


class TestHostWiring:
    """The path the app actually takes: config -> factory hooks -> backend slot.

    The other tests inject the judge straight into ``DeerMemConfig``; this one
    exercises ``_collect_host_hooks`` + ``DeerMem.from_config``, where a wiring
    mistake would silently disable the feature.
    """

    def _hooks_with(self, memory: dict) -> dict:
        from deerflow.config.memory_config import get_memory_config, load_memory_config_from_dict, set_memory_config

        previous = get_memory_config()
        load_memory_config_from_dict(memory)
        try:
            from deerflow.agents.memory.manager import _collect_host_hooks

            return _collect_host_hooks()
        finally:
            set_memory_config(previous)

    def test_both_sides_off_injects_no_judge(self, tmp_path):
        from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

        hooks = self._hooks_with({"enabled": True})

        assert hooks["judge"] is None, "L1: an unconfigured deployment gets no judge at all"
        dm = DeerMem.from_config({"storage_path": str(tmp_path)}, **hooks)
        assert dm._config.judge is None

    def test_a_configured_pre_screen_reaches_the_backend_slot(self, tmp_path):
        from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

        hooks = self._hooks_with(
            {
                "enabled": True,
                "prescreen": {
                    "mode": MODE_SHADOW,
                    "use": _PRESCREEN,
                    "config": {"api_key": "SECRET-MEMORY-KEY", "skip_threshold": 0.3},
                },
            }
        )

        assert isinstance(hooks["judge"], MemorySignalCoordinator)
        dm = DeerMem.from_config({"storage_path": str(tmp_path)}, **hooks)
        assert dm._config.judge is hooks["judge"], "the hook the factory built is the one the updater calls"
        assert dm.backend_config == {"storage_path": str(tmp_path)}, "the judge stays out of the serializable backend_config"
        declared = json.dumps(hooks["judge"].release_policy_parameters())
        assert '"skip_threshold": 0.3' in declared
        assert "SECRET-MEMORY-KEY" not in declared and "api_key_env" not in declared

    def test_an_enabled_mode_without_use_fails_at_config_load(self):
        from deerflow.config.memory_config import MemoryConfig

        with pytest.raises(ValueError, match="memory.prescreen.use is required"):
            MemoryConfig(prescreen={"mode": MODE_SHADOW})
        with pytest.raises(ValueError, match="memory.signal_classification.use is required"):
            MemoryConfig(signal_classification={"mode": MODE_HINTS})


class TestJudgeHotReload:
    """A judging-config edit reaches the cached manager's judge (no restart).

    The manager singleton is built once, so without a refresh an ``enforce`` ->
    ``off`` switch would keep skipping extraction and sending conversation text
    externally, and ``off`` -> ``shadow`` would silently never record.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch, tmp_path):
        import deerflow.config.runtime_paths as runtime_paths
        from deerflow.agents.memory.manager import reset_memory_manager
        from deerflow.config.memory_config import get_memory_config, set_memory_config
        from deerflow.config.typesafe_config import reset_typesafe_config

        monkeypatch.setattr(runtime_paths, "runtime_home", lambda: tmp_path)
        previous = get_memory_config()
        reset_memory_manager()
        reset_typesafe_config()
        yield
        set_memory_config(previous)
        reset_memory_manager()
        reset_typesafe_config()

    def test_a_mode_toggle_rebuilds_the_injected_judge(self):
        from deerflow.agents.memory.manager import get_memory_manager
        from deerflow.config.memory_config import MemoryConfig, set_memory_config

        set_memory_config(MemoryConfig(manager_class="deermem"))
        manager = get_memory_manager()
        assert manager._config.judge is None, "both sides default off"

        set_memory_config(MemoryConfig(manager_class="deermem", prescreen={"mode": MODE_SHADOW, "use": _PRESCREEN, "config": {"api_key": "SECRET-HOT-RELOAD-KEY"}}))
        reloaded = get_memory_manager()
        assert reloaded is manager, "the stateful manager singleton is reused, not rebuilt"
        assert isinstance(reloaded._config.judge, MemorySignalCoordinator), "off -> shadow takes effect"
        assert reloaded._config.judge._prescreen_mode == MODE_SHADOW
        assert "SECRET-HOT-RELOAD-KEY" not in json.dumps(reloaded._config.judge.release_policy_parameters())

        set_memory_config(MemoryConfig(manager_class="deermem"))
        assert get_memory_manager()._config.judge is None, "shadow -> off stops judging (and any external call)"

    def test_an_unchanged_judging_config_keeps_the_same_judge(self):
        from deerflow.agents.memory.manager import get_memory_manager
        from deerflow.config.memory_config import MemoryConfig, set_memory_config

        set_memory_config(MemoryConfig(manager_class="deermem", prescreen={"mode": MODE_ENFORCE, "use": _PRESCREEN, "config": {"api_key": _API_KEY}}))
        first = get_memory_manager()._config.judge
        assert get_memory_manager()._config.judge is first, "no config change, no rebuild"

    def test_a_shared_typesafe_edit_rebuilds_the_judge(self, monkeypatch):
        """A judge inheriting its connection from the top-level ``typesafe`` block
        must pick up an endpoint/model/credential/deadline edit there, and a
        credential rotation, not just a memory-slot edit."""
        from deerflow.agents.memory.manager import get_memory_manager
        from deerflow.config.memory_config import MemoryConfig, set_memory_config
        from deerflow.config.typesafe_config import load_typesafe_config_from_dict

        monkeypatch.setenv("TYPESAFE_API_KEY", "first-key")
        set_memory_config(MemoryConfig(manager_class="deermem", prescreen={"mode": MODE_SHADOW, "use": _PRESCREEN}))
        load_typesafe_config_from_dict({"base_url": "https://first.example"})
        first = get_memory_manager()._config.judge
        assert first is not None
        assert "https://first.example" in json.dumps(first._prescreen.release_policy_parameters())

        # An inherited endpoint edit invalidates without touching a memory slot.
        load_typesafe_config_from_dict({"base_url": "https://second.example"})
        second = get_memory_manager()._config.judge
        assert second is not first, "a shared typesafe edit must invalidate the cached judge"
        assert "https://second.example" in json.dumps(second._prescreen.release_policy_parameters())

        # A rotated env credential invalidates even though no config text changed:
        # the signature carries the resolved credential fingerprint, not just the block.
        monkeypatch.setenv("TYPESAFE_API_KEY", "second-key")
        assert get_memory_manager()._config.judge is not second, "a rotated credential must invalidate the cached judge"

        # A credential set in the block is picked up the same way.
        load_typesafe_config_from_dict({"api_key": "block-key"})
        assert get_memory_manager()._config.judge is not second, "a block credential edit must invalidate the cached judge"

    def test_an_enabled_build_does_not_land_after_a_rollback(self, monkeypatch):
        """A build that started before a rollback must not be published after it.

        The judging config can be rolled back (enforce -> off) while another thread
        is still building the enabled judge; installing that build afterwards would
        resurrect the superseded mode for already-queued batches. Publication
        revalidates the config generation, so the stale build is dropped.
        """
        import threading

        from deerflow.agents.memory import manager as manager_module
        from deerflow.agents.memory.manager import get_memory_manager
        from deerflow.config.memory_config import MemoryConfig, set_memory_config

        set_memory_config(MemoryConfig(manager_class="deermem"))
        manager = get_memory_manager()
        assert manager._config.judge is None

        set_memory_config(MemoryConfig(manager_class="deermem", prescreen={"mode": MODE_ENFORCE, "use": _PRESCREEN, "config": {"api_key": _API_KEY}}))

        started = threading.Event()
        released = threading.Event()
        real_build = manager_module._host_default_judge

        def build_then_hold():
            judge = real_build()  # the enabled judge, built before the rollback lands
            started.set()
            released.wait(timeout=5)
            return judge

        monkeypatch.setattr(manager_module, "_host_default_judge", build_then_hold)
        refresher = threading.Thread(target=manager_module._refresh_judge_for_reloaded_config, args=(manager,))
        refresher.start()
        assert started.wait(timeout=5), "the enabled build started"
        set_memory_config(MemoryConfig(manager_class="deermem"))  # roll back to off mid-build
        released.set()
        refresher.join(timeout=5)

        assert not refresher.is_alive()
        assert manager._config.judge is None, "a superseded enabled judge must not be published after the rollback"


class TestConfirmationInvariant:
    """O3 invariant 1: a model verdict must not change confirmation writes (S4).

    The reinforcement gate is evidence that the user really restated something, so
    it reads the deterministic signal set only. Model hints reach the hint text and
    (under enforce) the veto, never this gate.
    """

    def _updater_with_fact(self, *, judge=None, llm=None, patterns_dir: str | None = None) -> MemoryUpdater:
        storage = _Storage()
        storage.memory = _memory()
        storage.memory["facts"] = [
            {"id": "fact_a", "content": "User prefers concise answers", "category": "preference", "confidence": 0.8, "createdAt": "2026-01-01T00:00:00Z", "source": "t"},
        ]
        config = DeerMemConfig()
        config.fact_eviction_policy = "hybrid-v1"
        config.staleness_review_enabled = False
        if patterns_dir is not None:
            config.patterns_dir = patterns_dir
        if judge is not None:
            setattr(config, _JUDGE_HOOK, judge)
        return MemoryUpdater(config, storage, llm or _FakeLLM('{"user":{},"history":{},"newFacts":[],"factsToReinforce":[{"id":"fact_a","scope":"user","reason":"explicit confirmation"}],"factsToRemove":[]}'))

    @staticmethod
    def _confirmation(updater: MemoryUpdater):
        updater.update_memory(_conversation(), thread_id="thread-1", user_id="user-1")
        fact = next(fact for fact in updater._storage.memory["facts"] if fact["id"] == "fact_a")
        return fact.get("confirmationCount")

    def test_a_model_hint_alone_never_confirms(self):
        hinting = _Server(lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {QUESTION_AFFIRMATION: {"type": "noul", "noul": 0.9}, QUESTION_NEGATION: {"type": "noul", "noul": 0.1}}}))
        with_hints = self._updater_with_fact(judge=_combined_judge(hinting))
        without_judge = self._updater_with_fact()

        assert self._confirmation(with_hints) is None, "a model hint is not confirmation evidence"
        assert self._confirmation(without_judge) is None, "and the baseline confirms nothing either"

    def test_the_deterministic_channel_still_confirms(self, tmp_path):
        """Teeth: the gate is live -- it just reads the other channel.

        A custom pattern set makes the feed's re-detected reinforcement signal
        match, which is the only thing that may satisfy this gate.
        """
        patterns = _patterns_dir(tmp_path, reinforcement="- pattern: 'release candidate'\n")

        assert self._confirmation(self._updater_with_fact(patterns_dir=str(patterns))) == 1


class TestThroughTheQueue:
    """End to end through the real backend: add -> debounce queue -> updater -> judge."""

    def test_a_queued_chatter_batch_is_skipped_without_an_extraction_call(self, tmp_path):
        from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        recorded: list = []
        deer_mem = DeerMem.from_config(
            {"storage_path": str(tmp_path), "staleness_review_enabled": False},
            judge=_combined_judge(server),
            extraction_callback=recorded.append,
        )
        llm = _FakeLLM()
        deer_mem._llm = llm
        deer_mem._updater._llm = llm

        deer_mem.add(thread_id="t1", messages=_conversation(_CHATTER_TEXT), user_id="u1")
        deer_mem._queue.flush()

        assert llm.calls == 0, "enforce + skip saved the extraction call"
        assert recorded and recorded[0]["prescreen"]["verdict"] == "skip"
        assert "mutations_accepted" not in recorded[0], "no apply ran, so there is nothing to count"
        # DeerMem resolves a default agent bucket, so match the thread/user scope.
        assert [key for key in deer_mem._updater._watermarks if key[:2] == ("t1", "u1")], "the skipped batch is consumed, not re-judged every turn"

    def test_a_queued_batch_with_a_signal_still_extracts(self, tmp_path):
        from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

        server = _Server(lambda request: httpx.Response(200, json=_answer(0.01)))
        recorded: list = []
        deer_mem = DeerMem.from_config(
            {"storage_path": str(tmp_path), "staleness_review_enabled": False},
            judge=_combined_judge(server),
            extraction_callback=recorded.append,
        )
        llm = _FakeLLM()
        deer_mem._llm = llm
        deer_mem._updater._llm = llm

        # A correction phrase trips detect_signals, which answers for the pre-screen.
        deer_mem.add(thread_id="t2", messages=[HumanMessage(content="No, that's wrong - use tabs not spaces"), AIMessage(content="Understood.")], user_id="u1")
        deer_mem._queue.flush()

        assert llm.calls == 1, "L3: a deterministic signal forces extraction"
        # L3 removes only the *pre-screen's* eligibility: the classifier has no such
        # rule and still asks its own questions (design §2.2.3, scenario row 6).
        assert set(server.bodies()[0]["questions"]) == {QUESTION_AFFIRMATION, QUESTION_NEGATION}
        assert _PRESCREEN_Q not in server.bodies()[0]["questions"], "the pre-screen was never asked"
