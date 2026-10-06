"""Tests for the Layer 2 end-to-end RAGAS evaluation (spec 2026-08-23 §8).

Layer 2 walks the real conversation chain (agent picks tools, writes the
answer) instead of calling retrieval impls directly. The agent run itself is
injected as ``agent_runner`` so these tests never touch an LLM, Qdrant, or the
network — the judge LLM is stubbed through the ``ainvoke`` protocol (same
pattern as the graph extractor tests), and Langfuse is a fake client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.knowledge.eval.dataset import GoldenQuestion
from deerflow.knowledge.eval.ragas_eval import (
    JudgeParseError,
    TraceOutcome,
    build_lead_agent_runner,
    citation_precision_recall,
    compute_ragas_scores,
    expected_ragas_jobs,
    extract_answer,
    extract_citation_map,
    extract_cited_numbers,
    extract_retrieval_tools,
    extract_seed_entities,
    graph_entity_hit_rate,
    parse_judge_json,
    path_hit,
    push_scores_to_langfuse,
    render_markdown,
    report_from_dict,
    report_to_dict,
    run_layer2_evaluation,
    split_answer_claims,
)


class _FakeJudgeLLM:
    """Returns canned message contents in call order (last one repeats)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[object] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


class _ConcurrencyJudgeLLM:
    """Records the peak number of in-flight ``ainvoke`` calls.

    Each call yields once via ``asyncio.sleep`` so overlapping verdicts are
    observable — a serial chain can never report more than one active call.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def ainvoke(self, messages):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return SimpleNamespace(content='{"supported": true, "reason": "ok"}')


def _question(qid: str, *, category: str = "fact", expected_path: str = "vector", expected_paths: tuple[str, ...] | None = None, entities=(), reference: str | None = "参考答案") -> GoldenQuestion:
    return GoldenQuestion(
        id=qid,
        query=f"query-{qid}",
        expected_paths=expected_paths or (expected_path,),
        relevant_chunk_ids=(),
        relevant_entities=tuple(entities),
        category=category,
        reference_answer=reference,
    )


def _retrieval_exchange(tool: str, payload: dict, *, call_id: str | None = None) -> list:
    """One AIMessage(tool_call) + ToolMessage(JSON payload) pair, as LangChain emits them."""

    cid = call_id or f"call-{tool}-1"
    return [
        AIMessage(content="", tool_calls=[{"name": tool, "args": {"query": "q"}, "id": cid}]),
        ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=cid, name=tool),
    ]


def _outcome(
    qid: str,
    *,
    answer: str = "答案[1]",
    tools: tuple[str, ...] = ("hybrid_search",),
    citation_map: dict[int, str] | None = None,
    seed_entities: tuple[str, ...] = (),
    trace_id: str | None = "trace-1",
) -> TraceOutcome:
    return TraceOutcome(
        question_id=qid,
        answer=answer,
        retrieval_tools=tuple(tools),
        citation_map=dict(citation_map if citation_map is not None else {1: "证据一"}),
        seed_entities=tuple(seed_entities),
        thread_id=f"thread-{qid}",
        trace_id=trace_id,
    )


class TestParseJudgeJson:
    def test_valid_json(self):
        assert parse_judge_json('{"supported": true, "reason": "ok"}') == {"supported": True, "reason": "ok"}

    def test_code_fenced_json(self):
        assert parse_judge_json('```json\n{"supported": false, "reason": "x"}\n```')["supported"] is False

    def test_malformed_raises(self):
        with pytest.raises(JudgeParseError):
            parse_judge_json("我无法判定，这超出我的能力")

    def test_empty_raises(self):
        with pytest.raises(JudgeParseError):
            parse_judge_json("")

    def test_missing_supported_key_raises(self):
        with pytest.raises(JudgeParseError):
            parse_judge_json('{"verdict": true}')


class TestExtractors:
    def test_extract_retrieval_tools_orders_and_filters(self):
        messages = [
            HumanMessage(content="q"),
            *_retrieval_exchange("hybrid_search", {"results": [], "message": ""}),
            AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "call-bash"}]),
            ToolMessage(content="ok", tool_call_id="call-bash", name="bash"),
            *_retrieval_exchange("graph_search", {"entities": [], "relations": [], "evidence": [], "trace": {}, "message": ""}),
        ]

        assert extract_retrieval_tools(messages) == ("hybrid_search", "graph_search")

    def test_extract_retrieval_tools_empty(self):
        assert extract_retrieval_tools([HumanMessage(content="q"), AIMessage(content="a")]) == ()

    def test_extract_answer_last_ai_message_with_content(self):
        messages = [
            HumanMessage(content="q"),
            AIMessage(content="第一版"),
            AIMessage(content="", tool_calls=[{"name": "hybrid_search", "args": {}, "id": "c1"}]),
            ToolMessage(content="{}", tool_call_id="c1", name="hybrid_search"),
            AIMessage(content="最终答案[1]"),
        ]

        assert extract_answer(messages) == "最终答案[1]"

    def test_extract_answer_empty_when_no_ai_content(self):
        assert extract_answer([HumanMessage(content="q")]) == ""

    def test_extract_citation_map_from_three_tool_payloads(self):
        messages = [
            *_retrieval_exchange("hybrid_search", {"results": [{"chunk_id": "d#0001", "text": "切片一", "citation_no": 1}], "message": ""}),
            *_retrieval_exchange(
                "graph_search",
                {"entities": [], "relations": [], "evidence": [{"chunk_id": "d#0002", "text": "切片二", "citation_no": 2}], "trace": {}, "message": ""},
                call_id="call-graph-1",
            ),
            *_retrieval_exchange(
                "wiki_search",
                {"entries": [{"entry_id": "e1", "title": "条目", "content": "条目正文", "citation_no": 3}], "message": ""},
                call_id="call-wiki-1",
            ),
        ]

        assert extract_citation_map(messages) == {1: "切片一", 2: "切片二", 3: "条目正文"}

    def test_extract_citation_map_accepts_dict_content(self):
        messages = [ToolMessage(content={"results": [{"text": "切片", "citation_no": 7}], "message": ""}, tool_call_id="c", name="hybrid_search")]

        assert extract_citation_map(messages) == {7: "切片"}

    def test_extract_citation_map_ignores_unparseable_and_unrelated(self):
        messages = [
            ToolMessage(content="not-json", tool_call_id="c1", name="hybrid_search"),
            ToolMessage(content='{"ok": true}', tool_call_id="c2", name="bash"),
        ]

        assert extract_citation_map(messages) == {}

    def test_extract_seed_entities_merges_across_calls(self):
        messages = [
            *_retrieval_exchange(
                "graph_search",
                {"entities": [], "relations": [], "evidence": [], "trace": {"seed_entities": ["JVM", "GC"]}, "message": ""},
            ),
            *_retrieval_exchange(
                "graph_search",
                {"entities": [], "relations": [], "evidence": [], "trace": {"seed_entities": ["GC", "堆"]}, "message": ""},
                call_id="call-graph-2",
            ),
        ]

        assert extract_seed_entities(messages) == ("JVM", "GC", "堆")

    def test_extract_cited_numbers(self):
        assert extract_cited_numbers("先引用[1]，再组合[2][3]，重复[1]。") == [1, 2, 3]
        assert extract_cited_numbers("没有引用") == []

    def test_split_answer_claims_groups_markers(self):
        claims = split_answer_claims("无标注开头。论断一[1]。论断二[2][3]。结尾无标注。")

        assert [(c, nums) for c, nums in claims] == [("论断一", [1]), ("论断二", [2, 3])]


class TestPathHit:
    def test_expected_tool_in_sequence(self):
        assert path_hit(("vector",), ("hybrid_search", "graph_search")) is True
        assert path_hit(("graph",), ("hybrid_search", "graph_search")) is True

    def test_expected_tool_absent(self):
        assert path_hit(("graph",), ("hybrid_search",)) is False

    def test_no_retrieval_calls_is_a_miss(self):
        assert path_hit(("wiki",), ()) is False

    # ── 多路集合语义（spec 2026-08-28 §4）：任一期望工具被调用即命中 ──

    def test_multi_path_any_expected_tool_called_hits(self):
        assert path_hit(("vector", "graph"), ("hybrid_search",)) is True
        assert path_hit(("vector", "graph"), ("graph_search",)) is True

    def test_multi_path_only_unexpected_tool_called_misses(self):
        assert path_hit(("vector", "graph"), ("wiki_search",)) is False

    def test_multi_path_no_retrieval_calls_is_a_miss(self):
        assert path_hit(("vector", "graph"), ()) is False


class TestGraphEntityHitRate:
    def test_hit_ratio(self):
        assert graph_entity_hit_rate(("JVM", "GC"), ("JVM", "堆")) == 0.5

    def test_no_relevant_entities_returns_none(self):
        assert graph_entity_hit_rate(("JVM",), ()) is None

    def test_no_seed_entities_with_relevant_returns_zero(self):
        assert graph_entity_hit_rate((), ("JVM",)) == 0.0


class TestCitationScore:
    async def test_full_support(self):
        judge = _FakeJudgeLLM(['{"supported": true, "reason": "ok"}'])

        score = await citation_precision_recall("论断一[1]。论断二[2]。", {1: "证据一", 2: "证据二"}, judge_llm=judge)

        assert score.precision == 1.0
        assert score.recall == 1.0
        assert score.claims_judged == 2
        assert score.unsupported == ()
        assert score.missing == ()
        assert len(judge.calls) == 2

    async def test_partial_support(self):
        judge = _FakeJudgeLLM(['{"supported": true, "reason": "ok"}', '{"supported": false, "reason": "证据未提及"}'])

        score = await citation_precision_recall("论断一[1]。论断二[2]。", {1: "证据一", 2: "证据二"}, judge_llm=judge)

        assert score.precision == 0.5
        assert score.unsupported == (2,)

    async def test_missing_number_counts_unsupported_and_never_calls_judge(self):
        judge = _FakeJudgeLLM(['{"supported": true, "reason": "ok"}'])

        score = await citation_precision_recall("幻觉引用[9]。真实引用[1]。", {1: "证据一", 2: "证据二"}, judge_llm=judge)

        assert score.missing == (9,)
        assert score.precision == 0.5  # 1 supported of (1 judged + 1 hallucinated)
        assert score.recall == 0.5  # evidence 1 cited, evidence 2 never cited
        assert len(judge.calls) == 1  # only the existing number is judged

    async def test_no_citations_and_no_evidence_returns_none_pair(self):
        score = await citation_precision_recall("没有任何引用的答案。", {}, judge_llm=_FakeJudgeLLM([]))

        assert score.precision is None
        assert score.recall is None

    async def test_citations_with_empty_map_are_all_missing(self):
        score = await citation_precision_recall("全是幻觉[1][2]。", {}, judge_llm=_FakeJudgeLLM([]))

        assert score.precision == 0.0
        assert score.missing == (1, 2)
        assert score.recall is None

    async def test_no_citations_with_evidence_gives_zero_recall(self):
        score = await citation_precision_recall("没有引用。", {1: "证据一"}, judge_llm=_FakeJudgeLLM([]))

        assert score.precision is None
        assert score.recall == 0.0

    async def test_judge_malformed_output_degrades_to_unsupported(self):
        judge = _FakeJudgeLLM(["模型失控输出"])

        score = await citation_precision_recall("论断[1]。", {1: "证据一"}, judge_llm=judge)

        assert score.precision == 0.0
        assert score.unsupported == (1,)


class TestJudgeParallelism:
    """The citation judge is the scoring phase's long tail — verdicts must run
    concurrently (bounded by the shared cap), not one await chain per question."""

    async def test_verdicts_within_one_answer_run_concurrently(self):
        judge = _ConcurrencyJudgeLLM()

        score = await citation_precision_recall("论断一[1]。论断二[2]。论断三[3]。", {1: "证据一", 2: "证据二", 3: "证据三"}, judge_llm=judge)

        assert score.claims_judged == 3
        assert judge.max_active == 3

    async def test_semaphore_caps_concurrent_verdicts(self):
        judge = _ConcurrencyJudgeLLM()

        await citation_precision_recall("论断[1][2][3][4]。", {1: "一", 2: "二", 3: "三", 4: "四"}, judge_llm=judge, semaphore=asyncio.Semaphore(2))

        assert judge.max_active == 2

    async def test_unsupported_order_survives_concurrency(self):
        judge = _FakeJudgeLLM(['{"supported": false, "reason": "a"}', '{"supported": true, "reason": "b"}', '{"supported": false, "reason": "c"}'])

        score = await citation_precision_recall("论断一[1]。论断二[2]。论断三[3]。", {1: "证据一", 2: "证据二", 3: "证据三"}, judge_llm=judge)

        assert score.unsupported == (1, 3)
        assert score.precision == 1 / 3

    async def test_cross_question_judge_shares_the_concurrency_cap(self):
        from deerflow.knowledge.eval.ragas_eval import _JUDGE_CONCURRENCY

        questions = [_question(f"q{i}") for i in range(3)]

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id, answer="论断[1][2][3][4]。", citation_map={1: "一", 2: "二", 3: "三", 4: "四"})

        judge = _ConcurrencyJudgeLLM()
        report = await run_layer2_evaluation(questions, agent_runner=runner, judge_llm=judge, kb_id="kb-1")

        assert report.aggregate["failures"] == 0
        assert judge.calls == 12  # 3 questions x 4 marks, all judged
        assert judge.max_active == _JUDGE_CONCURRENCY  # 12 in flight share the one cap


class TestAnswerPhaseBudget:
    """D1 recursion budget (300 = ~20 model rounds at 15 super-steps each) and
    the D2 per-question wall clock — the answer phase must never hang a batch."""

    async def test_runner_recursion_limit_is_300(self, monkeypatch):
        import deerflow.agents.lead_agent.agent as lead_agent_mod

        captured: dict = {}

        class _FakeGraph:
            async def ainvoke(self, payload, config, context=None):
                captured.update(config)
                return {"messages": [AIMessage(content="答案")]}

        monkeypatch.setattr(lead_agent_mod, "make_lead_agent", lambda config: (captured.update(config), _FakeGraph())[1])

        runner = build_lead_agent_runner(kb_id="kb-1", user_id="u-1", run_id="run-1")
        await runner(_question("q1"))

        assert captured["recursion_limit"] == 300

    async def test_slow_question_times_out_and_batch_continues(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        monkeypatch.setattr(mod, "_ANSWER_TIMEOUT_S", 0.05, raising=False)
        seen: list[str] = []

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            seen.append(question.id)
            if question.id == "q1":
                await asyncio.sleep(0.3)
            return _outcome(question.id)

        report = await run_layer2_evaluation([_question("q1"), _question("q2")], agent_runner=runner, judge_llm=None, kb_id="kb-1")

        by_id = {r.question_id: r for r in report.results}
        assert "timeout" in (by_id["q1"].failure or "")
        assert by_id["q2"].failure is None
        assert seen == ["q1", "q2"]  # the batch ran on
        assert report.aggregate["failures"] == 1


class TestAnswerConcurrency:
    """D5: question runs overlap across the batch (bounded by
    ``_ANSWER_CONCURRENCY``), while results and progress stay in question order."""

    @staticmethod
    def _peak_runner(delays: dict[str, float], *, peak: dict):
        async def runner(question: GoldenQuestion) -> TraceOutcome:
            peak["active"] = peak.get("active", 0) + 1
            peak["max"] = max(peak.get("max", 0), peak["active"])
            await asyncio.sleep(delays.get(question.id, 0.02))
            peak["active"] -= 1
            return _outcome(question.id)

        return runner

    async def test_questions_run_concurrently(self):
        peak: dict = {}
        questions = [_question(f"q{i}") for i in range(3)]

        report = await run_layer2_evaluation(questions, agent_runner=self._peak_runner({}, peak=peak), judge_llm=None, kb_id="kb-1")

        assert report.aggregate["failures"] == 0
        assert peak["max"] == 3  # 3 questions < cap 4 -> all overlap

    async def test_answer_concurrency_capped(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        monkeypatch.setattr(mod, "_ANSWER_CONCURRENCY", 2)
        peak: dict = {}
        questions = [_question(f"q{i}") for i in range(4)]

        await run_layer2_evaluation(questions, agent_runner=self._peak_runner({}, peak=peak), judge_llm=None, kb_id="kb-1")

        assert peak["max"] == 2  # 4 questions share the cap of 2

    async def test_results_keep_question_order_and_progress_counts(self):
        events: list[tuple[str, int, int, int]] = []
        peak: dict = {}
        questions = [_question("q1"), _question("q2"), _question("q3")]

        def on_progress(phase, done, failed, total):
            events.append((phase, done, failed, total))

        # q1 finishes LAST yet must still be reported first — order is the contract.
        report = await run_layer2_evaluation(questions, agent_runner=self._peak_runner({"q1": 0.06, "q2": 0.01, "q3": 0.03}, peak=peak), judge_llm=None, kb_id="kb-1", progress_hook=on_progress)

        assert [r.question_id for r in report.results] == ["q1", "q2", "q3"]
        q_events = [e for e in events if e[0] == "questions"]
        assert q_events == [("questions", 0, 0, 3), ("questions", 1, 0, 3), ("questions", 2, 0, 3), ("questions", 3, 0, 3)]

    async def test_timeout_question_does_not_block_batch(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        monkeypatch.setattr(mod, "_ANSWER_TIMEOUT_S", 0.05)
        peak: dict = {}
        questions = [_question("q1"), _question("q2"), _question("q3")]

        report = await run_layer2_evaluation(questions, agent_runner=self._peak_runner({"q1": 0.3}, peak=peak), judge_llm=None, kb_id="kb-1")

        by_id = {r.question_id: r for r in report.results}
        assert "timeout" in (by_id["q1"].failure or "")
        assert by_id["q2"].failure is None and by_id["q3"].failure is None
        assert peak["max"] == 3  # the timed-out question overlapped, not queued


class TestRunConfigAndTiming:
    """D3 ragas RunConfig guard (retry/timeout cap) and the D4 per-call timing log."""

    def test_ragas_run_config_pins_retries_and_timeout(self):
        import deerflow.knowledge.eval.ragas_eval as mod

        factory = getattr(mod, "_ragas_run_config", None)
        assert factory is not None, "ragas RunConfig factory missing"
        cfg = factory()
        assert cfg.max_retries == 2
        assert cfg.timeout == 180

    async def test_runner_mounts_timing_handler(self, monkeypatch):
        import deerflow.agents.lead_agent.agent as lead_agent_mod
        import deerflow.knowledge.eval.ragas_eval as mod

        handler_cls = getattr(mod, "EvalCallTimingHandler", None)
        assert handler_cls is not None, "EvalCallTimingHandler missing"
        captured: dict = {}

        class _FakeGraph:
            async def ainvoke(self, payload, config, context=None):
                captured.update(config)
                return {"messages": [AIMessage(content="答案")]}

        monkeypatch.setattr(lead_agent_mod, "make_lead_agent", lambda config: (captured.update(config), _FakeGraph())[1])
        runner = build_lead_agent_runner(kb_id="kb-1", user_id="u-1", run_id="run-1")
        await runner(_question("q1"))

        assert any(isinstance(cb, handler_cls) for cb in captured.get("callbacks") or [])

    def test_timing_handler_logs_model_and_duration(self, caplog):
        import deerflow.knowledge.eval.ragas_eval as mod

        handler_cls = getattr(mod, "EvalCallTimingHandler", None)
        assert handler_cls is not None, "EvalCallTimingHandler missing"
        handler = handler_cls()
        run_id = uuid.uuid4()
        response = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(usage_metadata={"input_tokens": 3, "output_tokens": 5}))]])
        # Real-world shape: the model name rides serialized.kwargs, and on_llm_end
        # carries no invocation_params — reading it only at the end yields "?".
        serialized = {"name": "ChatOpenAI", "kwargs": {"model_name": "mimo-v2.6-flash"}}

        with caplog.at_level(logging.DEBUG, logger="deerflow.knowledge.eval.ragas_eval"):
            handler.on_llm_start(serialized, ["prompt"], run_id=run_id)
            handler.on_llm_end(response, run_id=run_id)

        timing = [r for r in caplog.records if "llm call" in r.getMessage()]
        assert timing, "no per-call timing line logged"
        assert "mimo-v2.6-flash" in timing[0].getMessage()
        assert "dur=" in timing[0].getMessage()


class TestRagasUnavailable:
    async def test_compute_ragas_scores_returns_none_when_unavailable(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        monkeypatch.setattr(mod, "_load_ragas", lambda: None)

        assert await compute_ragas_scores([{"question": "q"}], judge_llm=None, embeddings=None) is None


class TestCleanMetricValue:
    def test_nan_becomes_none(self):
        from deerflow.knowledge.eval.ragas_eval import _clean_metric_value

        assert _clean_metric_value(float("nan")) is None
        assert _clean_metric_value(0.85) == 0.85
        assert _clean_metric_value(0) == 0.0
        assert _clean_metric_value(True) is None  # bool is not a metric value
        assert _clean_metric_value(None) is None
        assert _clean_metric_value("0.9") is None


class _FakeLangfuseClient:
    def __init__(self) -> None:
        self.scores: list[dict] = []

    def create_score(self, **kwargs):
        self.scores.append(kwargs)


class TestRunLayer2Evaluation:
    async def test_end_to_end_stubbed(self):
        questions = [
            _question("q1", expected_path="vector"),
            _question("q2", expected_path="graph", category="relation", entities=("JVM",), reference=None),
        ]
        outcomes = {
            "q1": _outcome("q1", answer="答案一[1]。", tools=("hybrid_search",), citation_map={1: "证据一"}),
            # Wrong path: only hybrid called for a graph-expected question; no citations at all.
            "q2": _outcome("q2", answer="没有引用。", tools=("hybrid_search",), citation_map={}, seed_entities=()),
        }

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return outcomes[question.id]

        judge = _FakeJudgeLLM(['{"supported": true, "reason": "ok"}'])
        report = await run_layer2_evaluation(questions, agent_runner=runner, judge_llm=judge, kb_id="kb-1", run_id="run-1")

        assert report.ragas_available is False
        assert report.aggregate["questions"] == 2
        assert report.aggregate["failures"] == 0
        assert report.aggregate["path_accuracy"] == 0.5
        by_id = {r.question_id: r for r in report.results}
        assert by_id["q1"].path_hit is True
        assert by_id["q1"].citation is not None and by_id["q1"].citation.precision == 1.0
        assert by_id["q2"].path_hit is False
        assert by_id["q2"].citation is not None and by_id["q2"].citation.precision is None
        # q2 expects entity JVM but the (fake) graph path never ran -> 0% landing.
        assert by_id["q2"].graph_entity_hit_rate == 0.0

    async def test_multi_path_second_expected_tool_also_hits(self):
        # 多路题：期望 {vector, graph}，agent 只调了 graph_search → 仍应命中（§4 any 语义）。
        questions = [_question("q1", expected_paths=("vector", "graph"))]

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome("q1", answer="答案[1]。", tools=("graph_search",), citation_map={1: "证据一"})

        report = await run_layer2_evaluation(
            questions,
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            kb_id="kb-1",
        )

        r = report.results[0]
        assert r.expected_paths == ("vector", "graph")
        assert r.path_hit is True
        assert report.aggregate["path_accuracy"] == 1.0

    async def test_agent_runner_failure_degrades_to_failure_note(self):
        questions = [_question("q1"), _question("q2")]

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            if question.id == "q1":
                raise RuntimeError("agent run exploded")
            return _outcome("q2")

        report = await run_layer2_evaluation(questions, agent_runner=runner, judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']), kb_id="kb-1")

        by_id = {r.question_id: r for r in report.results}
        assert "agent run exploded" in (by_id["q1"].failure or "")
        assert by_id["q2"].failure is None
        assert report.aggregate["failures"] == 1

    async def test_ragas_scores_flow_into_results(self):
        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id)

        async def ragas_evaluator(samples, *, judge_llm, embeddings):
            return [{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": None, "context_recall": 0.7}]

        report = await run_layer2_evaluation(
            [_question("q1")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            ragas_evaluator=ragas_evaluator,
            kb_id="kb-1",
        )

        assert report.ragas_available is True
        assert report.results[0].ragas["faithfulness"] == 0.9
        assert report.aggregate["ragas"]["faithfulness"] == 0.9

    def test_report_round_trip(self):
        async def _build():
            async def runner(question: GoldenQuestion) -> TraceOutcome:
                return _outcome(question.id, answer="答案[1]。")

            return await run_layer2_evaluation(
                [_question("q1")],
                agent_runner=runner,
                judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
                kb_id="kb-1",
                run_id="run-rt",
            )

        import asyncio

        report = asyncio.run(_build())
        restored = report_from_dict(json.loads(json.dumps(report_to_dict(report), ensure_ascii=False)))

        assert restored.run_id == "run-rt"
        assert restored.results[0].question_id == "q1"
        assert restored.results[0].citation is not None and restored.results[0].citation.precision == 1.0
        assert restored.calibration["human_sample_ratio"] is None  # 人工校准占位字段
        assert restored.results[0].expected_paths == ("vector",)

    def test_report_dict_uses_expected_paths_list_key(self):
        async def _build():
            async def runner(question: GoldenQuestion) -> TraceOutcome:
                return _outcome(question.id, answer="答案[1]。")

            return await run_layer2_evaluation(
                [_question("q1", expected_paths=("vector", "graph"))],
                agent_runner=runner,
                judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
                kb_id="kb-1",
                run_id="run-mp",
            )

        import asyncio

        data = report_to_dict(asyncio.run(_build()))

        assert data["results"][0]["expected_paths"] == ["vector", "graph"]
        assert "expected_path" not in data["results"][0]

    def test_report_from_dict_accepts_legacy_single_key(self):
        # 旧 CLI 落盘的 layer 2 报告存单值 ``expected_path``（§9 双键兼容）。
        legacy = {
            "run_id": "run-old",
            "kb_id": "kb-1",
            "generated_at": None,
            "ragas_available": False,
            "ragas_skip_reason": None,
            "langfuse": {},
            "calibration": {},
            "aggregate": {},
            "results": [
                {
                    "question_id": "q1",
                    "category": "fact",
                    "expected_path": "graph",
                    "path_hit": True,
                    "first_tool": "graph_search",
                    "retrieval_tools": ["graph_search"],
                    "citation": None,
                    "graph_entity_hit_rate": None,
                    "ragas": {},
                    "thread_id": None,
                    "trace_id": None,
                    "failure": None,
                }
            ],
        }

        restored = report_from_dict(legacy)

        assert restored.results[0].expected_paths == ("graph",)

    async def test_langfuse_push_writes_one_score_per_metric(self):
        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id, answer="答案[1]。")

        report = await run_layer2_evaluation(
            [_question("q1")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            kb_id="kb-1",
        )
        client = _FakeLangfuseClient()

        status = push_scores_to_langfuse(report, client=client)

        assert status["pushed"] is True
        names = {s["name"] for s in client.scores}
        assert {"path_hit", "citation_precision", "citation_recall"} <= names
        assert all(s["trace_id"] == "trace-1" for s in client.scores)

    async def test_langfuse_unavailable_is_explicit_noop(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        monkeypatch.setattr(mod, "_default_langfuse_client", lambda: None)

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id, answer="答案[1]。")

        report = await run_layer2_evaluation(
            [_question("q1")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            kb_id="kb-1",
        )

        assert report.langfuse["pushed"] is False
        assert report.langfuse["skip_reason"]

    def test_render_markdown_sections(self):
        async def _build():
            async def runner(question: GoldenQuestion) -> TraceOutcome:
                return _outcome(question.id, answer="答案[1]。")

            return await run_layer2_evaluation(
                [_question("q1"), _question("q2", category="global", reference=None)],
                agent_runner=runner,
                judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
                kb_id="kb-1",
                run_id="run-md",
            )

        import asyncio

        md = render_markdown(asyncio.run(_build()))

        assert "人工校准" in md
        assert "ragas" in md.lower()  # skipped 状态被显式标注
        assert "Global 类" in md  # global 题单独分区
        assert "q1" in md and "q2" in md

    def test_write_reports(self, tmp_path):
        async def _build():
            async def runner(question: GoldenQuestion) -> TraceOutcome:
                return _outcome(question.id, answer="答案[1]。")

            return await run_layer2_evaluation(
                [_question("q1")],
                agent_runner=runner,
                judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
                kb_id="kb-1",
            )

        import asyncio

        from deerflow.knowledge.eval.ragas_eval import write_reports

        report = asyncio.run(_build())
        json_path, md_path = write_reports(report, tmp_path)

        assert json_path.exists() and md_path.exists()
        assert json.loads(json_path.read_text(encoding="utf-8"))["run_id"] == report.run_id


class TestRunLayer2ProgressHook:
    """spec 2026-09-06 run-progress Task 1：可选 progress hook 的回调序列契约。"""

    @pytest.mark.asyncio
    async def test_hook_sequence_counts_questions_then_ragas(self):
        calls: list[tuple[str, int, int, int]] = []

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id, answer="答案[1]。")

        await run_layer2_evaluation(
            [_question("q1"), _question("q2")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            kb_id="kb-1",
            run_id="run-hook",
            progress_hook=lambda phase, done, failed, total: calls.append((phase, done, failed, total)),
        )

        # 段入口事件 + 每题（agent 运行）毕回调一次；第三段（质量评估）= ragas jobs + citation judge 逐题，
        # 无 evaluator 时 ragas jobs=0，judge 2 题 → total=2（spec 2026-09-06 §9/§11）。
        assert calls == [
            ("questions", 0, 0, 2),
            ("questions", 1, 0, 2),
            ("questions", 2, 0, 2),
            ("ragas", 0, 0, 2),
            ("ragas", 1, 0, 2),
            ("ragas", 2, 0, 2),
        ]

    @pytest.mark.asyncio
    async def test_hook_counts_failed_question_in_failed_not_done(self):
        calls: list[tuple[str, int, int, int]] = []

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            if question.id == "q2":
                raise RuntimeError("agent blew up")
            return _outcome(question.id, answer="答案[1]。")

        await run_layer2_evaluation(
            [_question("q1"), _question("q2")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            kb_id="kb-1",
            run_id="run-hook-fail",
            progress_hook=lambda phase, done, failed, total: calls.append((phase, done, failed, total)),
        )

        # 段入口事件；单题失败：failed++，done 仍计（契约：failed 独立不从 done 扣）；
        # 第三段 total = 存活题的 judge job 数（1）。
        assert calls == [
            ("questions", 0, 0, 2),
            ("questions", 1, 0, 2),
            ("questions", 2, 1, 2),
            ("ragas", 0, 1, 1),
            ("ragas", 1, 1, 1),
        ]


class _FakeRagasResult:
    """ragas ``EvaluationResult`` 的最小形状：``to_pandas().to_dict(orient=...)``。"""

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def to_pandas(self) -> _FakeRagasResult:
        return self

    def to_dict(self, orient: str = "records") -> list[dict]:
        return self._records


class _FakeRagas:
    """假 ragas 模块：复刻 Executor 对外部 ``_pbar`` 的用法（每 job ``update(1)``）。"""

    metric_names = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

    def __init__(self) -> None:
        self.pbars: list[object] = []

    def evaluate(self, *, dataset, metrics, llm=None, embeddings=None, run_config=None, _pbar=None, **kwargs):
        assert _pbar is not None, "compute_ragas_scores must pass its own _pbar for per-job progress"
        self.pbars.append(_pbar)
        records = [dict.fromkeys(self.metric_names, 0.5) for _ in dataset.samples]
        for _ in range(len(dataset.samples) * len(metrics)):
            _pbar.update(1)
        return _FakeRagasResult(records)


class TestRagasJobProgress:
    """spec 2026-09-06 §9：ragas 段按 (样本 × 指标) job 上报 → 第三段定长。"""

    def test_expected_ragas_jobs_splits_reference_and_reference_free(self):
        samples = [
            {"question_id": "q1", "reference": "参考答案"},
            {"question_id": "q2", "reference": "参考答案"},
            {"question_id": "q3", "reference": None},
        ]

        # 有参考 4 指标、无参考 2 指标（context_* 需 reference）。
        assert expected_ragas_jobs(samples) == 2 * 4 + 1 * 2

    @pytest.mark.asyncio
    async def test_compute_ragas_scores_reports_every_job(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        fake = _FakeRagas()
        monkeypatch.setattr(mod, "_load_ragas", lambda: fake)
        calls: list[tuple[int, int]] = []
        samples = [
            {"question_id": "q1", "user_input": "u1", "response": "r1", "retrieved_contexts": ["c1"], "reference": "参考答案"},
            {"question_id": "q2", "user_input": "u2", "response": "r2", "retrieved_contexts": ["c2"], "reference": "参考答案"},
        ]

        rows = await compute_ragas_scores(samples, judge_llm=object(), embeddings=None, on_progress=lambda done, total: calls.append((done, total)))

        assert rows is not None and len(rows) == 2
        assert fake.pbars, "ragas evaluate must receive our _pbar"
        # 2 样本 × 4 指标 = 8 job：逐 job 递增、total 恒定。
        assert calls == [(i, 8) for i in range(1, 9)]

    @pytest.mark.asyncio
    async def test_compute_ragas_scores_without_hook_keeps_legacy_shape(self, monkeypatch):
        import deerflow.knowledge.eval.ragas_eval as mod

        fake = _FakeRagas()
        monkeypatch.setattr(mod, "_load_ragas", lambda: fake)
        samples = [{"question_id": "q1", "user_input": "u1", "response": "r1", "retrieved_contexts": ["c1"], "reference": None}]

        rows = await compute_ragas_scores(samples, judge_llm=object(), embeddings=None)

        assert rows is not None and len(rows) == 1

    @pytest.mark.asyncio
    async def test_run_layer2_third_phase_covers_ragas_jobs_then_judge(self):
        calls: list[tuple[str, int, int, int]] = []

        async def runner(question: GoldenQuestion) -> TraceOutcome:
            return _outcome(question.id, answer="答案[1]。")

        async def evaluator(samples, *, judge_llm, embeddings, on_progress=None):
            assert on_progress is not None, "progress_hook 存在时必须把逐 job 回调传进 evaluator"
            total = expected_ragas_jobs(samples)
            for done in range(1, total + 1):
                on_progress(done, total)
            return [{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": None, "context_recall": 0.7} for _ in samples]

        await run_layer2_evaluation(
            [_question("q1")],
            agent_runner=runner,
            judge_llm=_FakeJudgeLLM(['{"supported": true, "reason": "ok"}']),
            ragas_evaluator=evaluator,
            kb_id="kb-1",
            run_id="run-ragas-jobs",
            progress_hook=lambda phase, done, failed, total: calls.append((phase, done, failed, total)),
        )

        # 1 样本 × 4 指标 = 4 ragas job + 1 题 citation judge = 第三段 total 5，单调推进到满。
        ragas_calls = [call for call in calls if call[0] == "ragas"]
        assert [call[1] for call in ragas_calls] == [0, 1, 2, 3, 4, 5]
        assert {call[3] for call in ragas_calls} == {5}
