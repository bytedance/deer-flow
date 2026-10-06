"""Layer 2 end-to-end RAGAS evaluation (spec 2026-08-23 §8).

Unlike Layer 1 (which calls the retrieval impls directly), Layer 2 walks the
**real conversation chain**: the lead agent picks retrieval tools and writes
the answer, then each golden question is scored on

- the four standard RAGAS metrics (faithfulness / answer_relevancy /
  context_precision / context_recall — reference-based metrics degrade to
  reference-free when the question has no ``reference_answer``), and
- three architecture-specific metrics implemented locally:
  path selection (actual retrieval-tool sequence vs ``expected_path``),
  citation accuracy (``[n]`` marks vs the tool-returned ``citation_no``
  slices, judge-LLM support check — doubles as the regression guard for the
  shared citation-numbering mechanism), and graph entity landing
  (``trace.seed_entities`` vs ``relevant_entities``).

Design rules honored here:

- **Report-only, never a gate** — no threshold, no failing exit code.
- **Degradation contract** (same as recall_test / Layer 1): one question's
  agent run failing records a failure note and never sinks the evaluation.
- ``ragas`` is an optional dependency; when it is not installed the standard
  metrics are explicitly marked skipped instead of failing or faking green.
- The judge prompt is frozen in this module (``CITATION_JUDGE_SYSTEM_PROMPT``)
  so the scoring rubric cannot drift with the runtime environment.
- The agent run is injected as ``agent_runner``; the production runner
  (``build_lead_agent_runner``) drives ``make_lead_agent`` per question with a
  fresh thread so citation numbers restart at 1 per question.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from deerflow.knowledge.eval.dataset import GoldenQuestion

logger = logging.getLogger(__name__)

#: Retrieval tool names as exposed to the agent (function name = tool name).
RETRIEVAL_TOOL_NAMES: tuple[str, ...] = ("hybrid_search", "graph_search", "wiki_search")

#: golden ``expected_path`` → the retrieval tool the agent is expected to call.
EXPECTED_PATH_TO_TOOL: dict[str, str] = {
    "vector": "hybrid_search",
    "graph": "graph_search",
    "wiki": "wiki_search",
}

#: Standard RAGAS metrics reported alongside the architecture-specific ones.
RAGAS_METRIC_NAMES: tuple[str, ...] = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

# Frozen judge prompt (spec §8: judge prompt 固化在评测模块内). The judge only
# answers whether the evidence text supports the claim; strict JSON output.
CITATION_JUDGE_SYSTEM_PROMPT = """你是引用支撑性判定器。给定一个论断（claim）和一条知识库证据（evidence），判断证据是否支撑该论断。

规则：
- 「支撑」指证据文本直接或明确蕴含论断的核心事实；论断中的细节超出证据范围即为不支撑。
- 只输出严格 JSON：{"supported": true|false, "reason": "一句话理由"}。
- 不要输出任何其他内容。"""

_CITATION_JUDGE_USER_TEMPLATE = "论断：{claim}\n\n证据：{evidence}\n\n请判定。"

_CITATION_MARK_RE = re.compile(r"\[(\d+)\]")


class JudgeParseError(ValueError):
    """Judge LLM returned output that is not the expected strict JSON."""


@dataclass(frozen=True)
class TraceOutcome:
    """Observable result of one agent run over a golden question."""

    question_id: str
    answer: str
    retrieval_tools: tuple[str, ...]
    citation_map: Mapping[int, str]
    seed_entities: tuple[str, ...]
    thread_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class CitationScore:
    """Citation accuracy for one answer.

    precision — share of citation marks whose evidence actually supports the
    claim (judge-LLM verdict; marks pointing at a non-existent ``citation_no``
    count as unsupported — hallucinated references are the regression this
    metric guards against).
    recall — share of tool-returned evidence slices the answer actually cited.
    ``None`` when the respective denominator is empty (no marks / no evidence).
    """

    precision: float | None
    recall: float | None
    claims_judged: int
    unsupported: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()


@dataclass(frozen=True)
class QuestionEvalResult:
    question_id: str
    category: str
    expected_paths: tuple[str, ...]
    path_hit: bool | None
    first_tool: str | None
    retrieval_tools: tuple[str, ...]
    citation: CitationScore | None
    graph_entity_hit_rate: float | None
    ragas: Mapping[str, float | None]
    thread_id: str | None = None
    trace_id: str | None = None
    failure: str | None = None


@dataclass(frozen=True)
class Layer2Report:
    run_id: str
    kb_id: str
    generated_at: str
    results: tuple[QuestionEvalResult, ...]
    aggregate: Mapping[str, Any]
    ragas_available: bool
    ragas_skip_reason: str | None
    langfuse: Mapping[str, Any]
    # 人工校准占位（spec §8：每月抽样 ≥10% 人工评分，Cohen's κ 回填报告头部）。
    calibration: Mapping[str, Any] = field(
        default_factory=lambda: {
            "human_sample_ratio": None,
            "cohens_kappa": None,
            "notes": "每月抽样 ≥10% 人工评分后回填 human_sample_ratio 与 cohens_kappa。",
        }
    )


# ---------------------------------------------------------------------------
# Trace extraction (pure functions over the agent's message history)
# ---------------------------------------------------------------------------


def extract_retrieval_tools(messages: Sequence[Any]) -> tuple[str, ...]:
    """Ordered retrieval-tool call sequence extracted from the message history."""

    tools: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, Mapping) else getattr(call, "name", None)
            if name in RETRIEVAL_TOOL_NAMES:
                tools.append(name)
    return tuple(tools)


def extract_answer(messages: Sequence[Any]) -> str:
    """The final non-empty AI message content — the answer the user would see."""

    from langchain_core.messages import AIMessage

    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        content = message.content
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text = "".join(block.get("text", "") for block in content if isinstance(block, Mapping))
            if text.strip():
                return text
    return ""


def _tool_payload(content: Any) -> Mapping[str, Any] | None:
    if isinstance(content, Mapping):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            try:
                # ToolMessage coerces a dict content to its Python repr
                # (single quotes) — still recoverable.
                import ast

                parsed = ast.literal_eval(content)
            except (ValueError, SyntaxError):
                return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _iter_evidence_items(payload: Mapping[str, Any]):
    """Yield ``(citation_no, text)`` pairs from any retrieval tool payload."""

    for key, text_field in (("results", "text"), ("evidence", "text"), ("entries", "content")):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            no = item.get("citation_no")
            text = item.get(text_field)
            if isinstance(no, int) and isinstance(text, str):
                yield no, text


def extract_citation_map(messages: Sequence[Any]) -> dict[int, str]:
    """``citation_no → evidence text`` across all retrieval tool responses.

    The three retrieval tools share one per-run counter, so numbers never
    collide within a single agent run.
    """

    from langchain_core.messages import ToolMessage

    mapping: dict[int, str] = {}
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name not in RETRIEVAL_TOOL_NAMES:
            continue
        payload = _tool_payload(message.content)
        if payload is None:
            continue
        for no, text in _iter_evidence_items(payload):
            mapping[no] = text
    return mapping


def extract_seed_entities(messages: Sequence[Any]) -> tuple[str, ...]:
    """Hop-0 entity landings from every graph_search call, de-duplicated, order-stable."""

    from langchain_core.messages import ToolMessage

    seen: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name != "graph_search":
            continue
        payload = _tool_payload(message.content)
        trace = (payload or {}).get("trace")
        seeds = trace.get("seed_entities") if isinstance(trace, Mapping) else None
        for name in seeds or []:
            if isinstance(name, str) and name and name not in seen:
                seen.append(name)
    return tuple(seen)


def extract_cited_numbers(answer: str) -> list[int]:
    """Distinct ``[n]`` citation marks in first-appearance order."""

    return list(dict.fromkeys(int(match) for match in _CITATION_MARK_RE.findall(answer)))


def split_answer_claims(answer: str) -> list[tuple[str, list[int]]]:
    """Split the answer into ``(claim_text, cited_numbers)`` pairs.

    A citation mark (or a run of adjacent marks like ``[2][3]``) owns the
    sentence immediately before it; earlier uncited prose in the same segment
    is not part of the claim. Text with no marks at all yields no claims.
    """

    marks = list(_CITATION_MARK_RE.finditer(answer))
    if not marks:
        return []

    # Group adjacent marks ("[2][3]" shares one claim).
    groups: list[list[re.Match]] = []
    for match in marks:
        if groups and not answer[groups[-1][-1].end() : match.start()].strip():
            groups[-1].append(match)
        else:
            groups.append([match])

    claims: list[tuple[str, list[int]]] = []
    prev_end = 0
    for group in groups:
        segment = answer[prev_end : group[0].start()]
        sentences = re.split(r"(?<=[。！？!?；;\n])", segment)
        claim = sentences[-1].strip(" \t\r\n。；;，,：:！!？?、") if sentences else ""
        if claim:
            claims.append((claim, [int(m.group(1)) for m in group]))
        prev_end = group[-1].end()
    return claims


# ---------------------------------------------------------------------------
# Architecture-specific metrics (pure)
# ---------------------------------------------------------------------------


def path_hit(expected_paths: Sequence[str], retrieval_tools: Sequence[str]) -> bool:
    """Whether the agent called any tool matching the expected paths.

    Set semantics (spec 2026-08-28 §4): a question expected on {vector,
    graph} counts when either ``hybrid_search`` or ``graph_search`` appears
    in the call sequence — mirroring layer-1's winner-in-set judgement. The
    agent calling *no* retrieval tool at all counts as a miss.
    """

    expected_tools = {EXPECTED_PATH_TO_TOOL[path] for path in expected_paths if path in EXPECTED_PATH_TO_TOOL}
    return any(tool in retrieval_tools for tool in expected_tools)


def graph_entity_hit_rate(seed_entities: Sequence[str], relevant_entities: Sequence[str]) -> float | None:
    """Share of annotated entities that landed as graph hop-0 seeds.

    ``None`` when the question annotates no entities (metric not applicable).
    """

    if not relevant_entities:
        return None
    seeds = set(seed_entities)
    hits = sum(1 for name in relevant_entities if name in seeds)
    return hits / len(relevant_entities)


# ---------------------------------------------------------------------------
# Judge LLM (prompt frozen in this module)
# ---------------------------------------------------------------------------


def parse_judge_json(text: str) -> dict[str, Any]:
    """Parse the judge's strict-JSON output, tolerating markdown code fences."""

    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate).strip()
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError) as exc:
        raise JudgeParseError(f"judge output is not JSON: {text[:120]!r}") from exc
    if not isinstance(data, dict) or "supported" not in data:
        raise JudgeParseError(f"judge output missing 'supported': {text[:120]!r}")
    return data


#: citation judge 的全局并发上限（所有题共享一个信号量）——与答题并发统一 4
#: （他拍「统一 4」）：评测与聊天共用 LLM 端点，统一低档留邻居余量；代价=judge
#: 尾巴对 8 路翻倍（~57→~110s/17 题）。数字可调。
_JUDGE_CONCURRENCY = 4

#: 答题段每题墙钟预算（秒）——兜底（D2）：「失控题 × 慢端点」组合无上界
#: （20 轮 × 60s ≈ 20 分钟/题），墙钟保批不保题；超时题记 TimeoutError 续跑。
#: 初值 180s = 观测最大 ~90s 的 2 倍，跑一阵校准。
_ANSWER_TIMEOUT_S = 180

#: 答题段题间并发上限（D5，与 `_JUDGE_CONCURRENCY` 统一 4——他拍「统一 4」）：
#: 4 题一波、端点上最多 4 路长调用，给共用同一 LLM 端点的聊天邻居留余量。
_ANSWER_CONCURRENCY = 4

#: ragas 每次 LLM 调用的重试/超时上限（D3 兜底）：重试 2、超时 180s（他拍乙=
#: ragas 上游默认——比 120s 宽是因「慢 judge 太紧」是当年实证过的病；仍比旧的
#: 600s×10 收紧 3.3×/5×）。
_RAGAS_MAX_RETRIES = 2
_RAGAS_TIMEOUT_S = 180


def _ragas_run_config() -> Any:
    """Per-LLM-call retry/timeout profile for every ragas evaluation call."""

    from ragas.run_config import RunConfig

    return RunConfig(max_retries=_RAGAS_MAX_RETRIES, timeout=_RAGAS_TIMEOUT_S)


class EvalCallTimingHandler(BaseCallbackHandler):
    """Debug-level per-LLM-call timing for the eval chain (D4 观测项).

    One line per call — model name, wall time, token counts. Prompts and
    completions are deliberately never logged (no content, no keys).
    """

    def __init__(self) -> None:
        self._started: dict[Any, tuple[float, str]] = {}

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id: Any, **kwargs: Any) -> None:
        params = kwargs.get("invocation_params") or {}
        model = params.get("model_name") or params.get("model") or params.get("ls_model_name") or (serialized or {}).get("kwargs", {}).get("model_name") or (serialized or {}).get("name") or "?"
        self._started[run_id] = (time.monotonic(), model)

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        started = self._started.pop(run_id, None)
        if started is None:
            return
        begin, model = started
        usage = "-"
        try:
            meta = getattr(response.generations[0][0].message, "usage_metadata", None) or {}
            usage = f"in={meta.get('input_tokens')}/out={meta.get('output_tokens')}"
        except Exception:  # noqa: BLE001 — best-effort observability
            pass
        logger.debug("eval llm call model=%s dur=%.2fs usage=%s", model, time.monotonic() - begin, usage)


async def judge_citation_support(claim: str, evidence: str, *, judge_llm: Any) -> bool:
    """One support verdict for a (claim, evidence) pair.

    Malformed judge output degrades to ``False`` (the mark is unsupported) so
    judge jitter can never crash a question — it only ever lowers the score,
    which the report makes visible.
    """

    from langchain_core.messages import HumanMessage, SystemMessage

    response = await judge_llm.ainvoke(
        [
            SystemMessage(content=CITATION_JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=_CITATION_JUDGE_USER_TEMPLATE.format(claim=claim, evidence=evidence)),
        ]
    )
    try:
        return bool(parse_judge_json(str(response.content))["supported"])
    except JudgeParseError:
        logger.warning("citation judge returned unparseable output; counting as unsupported")
        return False


async def citation_precision_recall(
    answer: str,
    citation_map: Mapping[int, str],
    *,
    judge_llm: Any,
    semaphore: asyncio.Semaphore | None = None,
) -> CitationScore:
    """Citation accuracy for one answer against the run's evidence map.

    The (claim, evidence) verdicts are fetched concurrently (bounded by the
    caller's optional semaphore) — the old serial ``await`` chain was the
    scoring phase's long tail (10-30 judge calls queued per question).
    Verdicts are collected in input order, so ``unsupported`` ordering and the
    missing-bookkeeping semantics are unchanged.
    """

    claims = split_answer_claims(answer)
    supported = 0
    judged = 0
    unsupported: list[int] = []
    missing_instances = 0
    missing_numbers: list[int] = []
    jobs: list[tuple[str, int, str]] = []
    for claim, numbers in claims:
        for number in numbers:
            evidence = citation_map.get(number)
            if evidence is None:
                # Hallucinated reference: the tool never issued this number.
                missing_instances += 1
                if number not in missing_numbers:
                    missing_numbers.append(number)
                continue
            jobs.append((claim, number, evidence))

    async def _verdict(claim: str, number: int, evidence: str) -> tuple[int, bool]:
        if semaphore is None:
            ok = await judge_citation_support(claim, evidence, judge_llm=judge_llm)
        else:
            async with semaphore:
                ok = await judge_citation_support(claim, evidence, judge_llm=judge_llm)
        return number, ok

    for number, ok in await asyncio.gather(*(_verdict(claim, number, evidence) for claim, number, evidence in jobs)):
        judged += 1
        if ok:
            supported += 1
        elif number not in unsupported:
            unsupported.append(number)

    total_marks = judged + missing_instances
    precision = supported / total_marks if total_marks else None
    if citation_map:
        cited_known = {n for _, numbers in claims for n in numbers if n in citation_map}
        recall = len(cited_known) / len(citation_map)
    else:
        recall = None
    return CitationScore(
        precision=precision,
        recall=recall,
        claims_judged=judged,
        unsupported=tuple(unsupported),
        missing=tuple(missing_numbers),
    )


# ---------------------------------------------------------------------------
# RAGAS standard metrics (optional dependency)
# ---------------------------------------------------------------------------


def _load_ragas():
    """Import ragas if installed; ``None`` otherwise (optional dependency)."""

    try:
        import ragas

        return ragas
    except ImportError:
        return None


def ragas_unavailable_reason() -> str | None:
    """``None`` when ragas is importable, else the human-readable skip reason."""

    if _load_ragas() is None:
        return "ragas 未安装（可选依赖；`uv sync --extra ragas` 后可用）"
    return None


def build_ragas_sample(question: GoldenQuestion, outcome: TraceOutcome) -> dict[str, Any]:
    """One ragas SingleTurnSample-shaped dict; ``reference`` is ``None`` when the
    golden question has no ``reference_answer`` (reference-free degradation)."""

    return {
        "question_id": question.id,
        "user_input": question.query,
        "response": outcome.answer,
        "retrieved_contexts": [outcome.citation_map[no] for no in sorted(outcome.citation_map)],
        "reference": question.reference_answer or None,
    }


def _clean_metric_value(value: Any) -> float | None:
    """Normalize one ragas metric cell: failed jobs come back as NaN, which we
    surface as ``None`` (report shows '-', aggregates skip) instead of a bogus
    'nan%'. Booleans and non-numerics also degrade to ``None``."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    import math

    return None if math.isnan(float(value)) else float(value)


#: ragas submits one job per (sample, metric): reference samples get the four
#: standard metrics, reference-free samples only the two that need no reference.
RAGAS_REFERENCE_METRICS = 4
RAGAS_REFERENCE_FREE_METRICS = 2


def expected_ragas_jobs(samples: Sequence[dict[str, Any]]) -> int:
    """How many ragas jobs a sample list will submit (spec 2026-09-06 §9).

    ragas' ``Executor`` submits one job per (sample, metric) pair, so the job
    count is the honest denominator for the quality-scoring progress segment.
    """

    with_reference = sum(1 for sample in samples if sample.get("reference"))
    return with_reference * RAGAS_REFERENCE_METRICS + (len(samples) - with_reference) * RAGAS_REFERENCE_FREE_METRICS


class _RagasJobBar:
    """Duck-typed ``tqdm`` stand-in handed to ragas as ``evaluate(_pbar=...)``.

    ragas' Executor calls ``update(1)`` per completed job and uses an external
    bar as-is when supplied — so this yields per-job progress without touching
    ragas' batching/parallelism, and silences its own console bar.
    """

    def __init__(self, total: int, on_progress: Callable[[int, int], None] | None) -> None:
        self.total = total
        self.n = 0
        self._on_progress = on_progress

    def update(self, n: int = 1) -> None:
        self.n += n
        if self._on_progress is not None:
            self._on_progress(self.n, self.total)

    def close(self) -> None:
        return None

    def set_description(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def __enter__(self) -> _RagasJobBar:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


async def compute_ragas_scores(
    samples: list[dict[str, Any]],
    *,
    judge_llm: Any,
    embeddings: Any,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, float | None]] | None:
    """Run the four standard RAGAS metrics; ``None`` when ragas is not installed.

    Samples with a ``reference`` get all four metrics; reference-free samples
    only faithfulness / answer_relevancy (the two context_* metrics need a
    reference). ragas' ``evaluate`` is synchronous, so it runs in a thread.

    ``on_progress(done, total)`` (spec 2026-09-06 §9) fires once per ragas job
    across both sample groups; ``None`` keeps the legacy behavior untouched.
    """

    if not samples:
        return []
    if _load_ragas() is None:
        return None

    bar = _RagasJobBar(expected_ragas_jobs(samples), on_progress)

    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    run_config = _ragas_run_config()

    def _evaluate(group: list[dict[str, Any]], metrics: list[Any]) -> list[dict[str, Any]]:
        dataset = EvaluationDataset(
            samples=[
                SingleTurnSample(
                    user_input=s["user_input"],
                    response=s["response"],
                    retrieved_contexts=s["retrieved_contexts"],
                    reference=s["reference"],
                )
                for s in group
            ]
        )
        result = _load_ragas().evaluate(dataset=dataset, metrics=metrics, llm=judge_llm, embeddings=embeddings, run_config=run_config, _pbar=bar, show_progress=False)
        return result.to_pandas().to_dict(orient="records")

    with_reference = [s for s in samples if s.get("reference")]
    without_reference = [s for s in samples if not s.get("reference")]
    rows: dict[str, dict[str, Any]] = {}
    if with_reference:
        records = await asyncio.to_thread(_evaluate, with_reference, [faithfulness, answer_relevancy, context_precision, context_recall])
        for sample, record in zip(with_reference, records, strict=True):
            rows[sample["question_id"]] = record
    if without_reference:
        records = await asyncio.to_thread(_evaluate, without_reference, [faithfulness, answer_relevancy])
        for sample, record in zip(without_reference, records, strict=True):
            rows[sample["question_id"]] = record

    return [{name: _clean_metric_value(rows.get(s["question_id"], {}).get(name)) for name in RAGAS_METRIC_NAMES} for s in samples]


# ---------------------------------------------------------------------------
# Langfuse score push (best-effort; never blocks the report)
# ---------------------------------------------------------------------------


def _default_langfuse_client():
    """The shared langfuse client when langfuse tracing is enabled; else ``None``."""

    try:
        from deerflow.config import get_enabled_tracing_providers

        if "langfuse" not in get_enabled_tracing_providers():
            return None
        from langfuse import get_client

        return get_client()
    except Exception:
        return None


def _iter_question_scores(result: QuestionEvalResult):
    yield "path_hit", (None if result.path_hit is None else (1.0 if result.path_hit else 0.0))
    if result.citation is not None:
        yield "citation_precision", result.citation.precision
        yield "citation_recall", result.citation.recall
    yield "graph_entity_hit_rate", result.graph_entity_hit_rate
    for name, value in (result.ragas or {}).items():
        yield f"ragas_{name}", value


def push_scores_to_langfuse(report: Layer2Report, *, client: Any = None) -> dict[str, Any]:
    """Push per-question metric scores onto the question's Langfuse trace.

    Best-effort by design (Layer 2 is report-only): a missing client or a
    failing score write is recorded in the returned status, never raised.
    """

    if client is None:
        client = _default_langfuse_client()
    if client is None:
        return {"pushed": False, "skip_reason": "langfuse 未启用或未安装", "scores_written": 0, "failures": []}

    written = 0
    failures: list[str] = []
    for result in report.results:
        if not result.trace_id:
            continue
        for name, value in _iter_question_scores(result):
            if value is None:
                continue
            try:
                client.create_score(trace_id=result.trace_id, name=name, value=float(value), comment=f"rag-eval qid={result.question_id} run={report.run_id}")
                written += 1
            except Exception as exc:  # noqa: BLE001 — best-effort push
                failures.append(f"{result.question_id}/{name}: {exc}")
    return {"pushed": written > 0, "skip_reason": None, "scores_written": written, "failures": failures}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _failure_result(question: GoldenQuestion, exc: BaseException) -> QuestionEvalResult:
    return QuestionEvalResult(
        question_id=question.id,
        category=question.category,
        expected_paths=question.expected_paths,
        path_hit=None,
        first_tool=None,
        retrieval_tools=(),
        citation=None,
        graph_entity_hit_rate=None,
        ragas={name: None for name in RAGAS_METRIC_NAMES},
        failure=f"{type(exc).__name__}: {exc}",
    )


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _aggregate(results: list[QuestionEvalResult]) -> dict[str, Any]:
    live = [r for r in results if r.failure is None]
    by_category: dict[str, dict[str, Any]] = {}
    for result in live:
        bucket = by_category.setdefault(result.category, {"questions": 0, "path_hits": []})
        bucket["questions"] += 1
        bucket["path_hits"].append(None if result.path_hit is None else (1.0 if result.path_hit else 0.0))
    return {
        "questions": len(results),
        "failures": len(results) - len(live),
        "path_accuracy": _mean([None if r.path_hit is None else (1.0 if r.path_hit else 0.0) for r in live]),
        "citation_precision": _mean([r.citation.precision if r.citation else None for r in live]),
        "citation_recall": _mean([r.citation.recall if r.citation else None for r in live]),
        "graph_entity_hit_rate": _mean([r.graph_entity_hit_rate for r in live]),
        "ragas": {name: _mean([r.ragas.get(name) for r in live]) for name in RAGAS_METRIC_NAMES},
        "by_category": {category: {"questions": bucket["questions"], "path_accuracy": _mean(bucket["path_hits"])} for category, bucket in sorted(by_category.items())},
    }


async def run_layer2_evaluation(
    questions: Sequence[GoldenQuestion],
    *,
    agent_runner: Callable[[GoldenQuestion], Awaitable[TraceOutcome]],
    judge_llm: Any = None,
    ragas_evaluator: Callable[..., Awaitable[list[dict[str, float | None]] | None]] | None = None,
    langfuse_client: Any = None,
    kb_id: str = "",
    run_id: str | None = None,
    progress_hook: Callable[[str, int, int, int], None] | None = None,
) -> Layer2Report:
    """Evaluate every golden question over the real conversation chain.

    One question's agent run failing degrades to a failure note — the run
    always produces a complete report (same contract as recall_test).

    ``progress_hook`` (spec 2026-09-06 run-progress / §9) is optional and fires
    ``(phase, done, failed, total)``: once per question after its agent run
    (phase ``"questions"``, determinate), then through the quality-scoring phase
    (phase ``"ragas"``, determinate too — ``total`` = ragas jobs (sample ×
    metric) + one citation-judge job per live question, ``done`` advancing per
    ragas job and per judged question). ``None`` keeps the legacy behavior
    untouched (CLI and existing callers).
    """

    run_id = run_id or f"ragas-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    outcomes: dict[str, TraceOutcome] = {}
    failures: dict[str, BaseException] = {}
    total_questions = len(questions)
    if progress_hook is not None:
        # 段入口事件（spec §11 实施校正，与 ragas 段入口同词汇）：旧实现只在每题
        # 毕才回调 → 首题在飞期间（agent 多轮可达分钟级）phase 停 layer1，UI 一直
        # 显「检索评测」——与用户批评过的假进度同族缺陷。
        progress_hook("questions", 0, 0, total_questions)
    # 答题段题间并发（D5）：所有题的任务一次全启动、共享 `_ANSWER_CONCURRENCY`
    # 信号量，按题序收割——结果顺序与 progress 计数和串行时代逐字一致。
    answer_sem = asyncio.Semaphore(_ANSWER_CONCURRENCY)

    async def _answer_one(question: GoldenQuestion) -> tuple[TraceOutcome | None, BaseException | None]:
        async with answer_sem:
            try:
                return await asyncio.wait_for(agent_runner(question), timeout=_ANSWER_TIMEOUT_S), None
            except TimeoutError:
                logger.warning("agent run timed out for %s after %ss", question.id, _ANSWER_TIMEOUT_S)
                return None, TimeoutError("timeout")
            except Exception as exc:  # noqa: BLE001 — degradation contract
                logger.warning("agent run failed for %s: %s", question.id, exc)
                return None, exc

    answer_tasks = {question.id: asyncio.create_task(_answer_one(question)) for question in questions}
    for question in questions:
        outcome, exc = await answer_tasks[question.id]
        if exc is not None:
            failures[question.id] = exc
        else:
            outcomes[question.id] = outcome  # type: ignore[assignment]
        if progress_hook is not None:
            # 单题失败计入 failed，done 仍计（failed 独立不从 done 扣）。
            progress_hook("questions", len(outcomes) + len(failures), len(failures), total_questions)

    # Standard RAGAS metrics over the questions whose agent run succeeded.
    ragas_rows: list[dict[str, float | None]] | None = None
    ragas_skip_reason: str | None = None
    live_questions = [q for q in questions if q.id in outcomes]
    samples = [build_ragas_sample(q, outcomes[q.id]) for q in live_questions]
    # 第三段（质量评估）总量 = ragas jobs + 逐题 citation judge；judge 循环此前
    # 完全静默，会让进度条在 ragas 结束后提前满格（spec 2026-09-06 §9）。
    ragas_jobs = expected_ragas_jobs(samples) if ragas_evaluator is not None else 0
    judge_jobs = len(live_questions) if judge_llm is not None else 0
    scoring_total = ragas_jobs + judge_jobs
    if progress_hook is not None:
        progress_hook("ragas", 0, len(failures), scoring_total)
    if ragas_evaluator is not None:
        # on_progress 仅在有 hook 时传入：既有假 evaluator（CLI/测试）协议不变。
        scoring_kwargs: dict[str, Any] = {} if progress_hook is None else {"on_progress": lambda done, _total: progress_hook("ragas", done, len(failures), scoring_total)}
        try:
            ragas_rows = await ragas_evaluator(samples, judge_llm=judge_llm, embeddings=None, **scoring_kwargs)
        except Exception as exc:  # noqa: BLE001 — report-only path
            logger.warning("ragas evaluation failed: %s", exc)
            ragas_skip_reason = f"ragas 执行失败: {exc}"
    else:
        ragas_skip_reason = ragas_unavailable_reason()
    if ragas_rows is None and ragas_skip_reason is None:
        ragas_skip_reason = ragas_unavailable_reason() or "ragas 未产出结果"
    ragas_by_question: dict[str, dict[str, float | None]] = {}
    if ragas_rows is not None:
        for question, row in zip(live_questions, ragas_rows, strict=True):
            ragas_by_question[question.id] = row

    # 逐题 citation judge 全并发启动（共享 `_JUDGE_CONCURRENCY` 信号量限流）、
    # 按题序收割：两层串行链（题间×题内）是评分段长尾的全部来源。
    judge_sem = asyncio.Semaphore(_JUDGE_CONCURRENCY) if judge_llm is not None else None
    citation_tasks: dict[str, asyncio.Task[CitationScore]] = {}
    if judge_llm is not None:
        for question in questions:
            if question.id in failures:
                continue
            outcome = outcomes[question.id]
            citation_tasks[question.id] = asyncio.create_task(citation_precision_recall(outcome.answer, outcome.citation_map, judge_llm=judge_llm, semaphore=judge_sem))

    results: list[QuestionEvalResult] = []
    judged = 0
    for question in questions:
        if question.id in failures:
            results.append(_failure_result(question, failures[question.id]))
            continue
        outcome = outcomes[question.id]
        citation = None
        if question.id in citation_tasks:
            citation = await citation_tasks[question.id]
            judged += 1
            if progress_hook is not None:
                # ragas 失败/跳过也按预期 job 数结算，保证第三段单调推进到满。
                progress_hook("ragas", ragas_jobs + judged, len(failures), scoring_total)
        results.append(
            QuestionEvalResult(
                question_id=question.id,
                category=question.category,
                expected_paths=question.expected_paths,
                path_hit=path_hit(question.expected_paths, outcome.retrieval_tools),
                first_tool=outcome.retrieval_tools[0] if outcome.retrieval_tools else None,
                retrieval_tools=outcome.retrieval_tools,
                citation=citation,
                graph_entity_hit_rate=graph_entity_hit_rate(outcome.seed_entities, question.relevant_entities),
                ragas=ragas_by_question.get(question.id, dict.fromkeys(RAGAS_METRIC_NAMES)),
                thread_id=outcome.thread_id,
                trace_id=outcome.trace_id,
            )
        )

    report = Layer2Report(
        run_id=run_id,
        kb_id=kb_id,
        generated_at=datetime.now(UTC).isoformat(),
        results=tuple(results),
        aggregate=_aggregate(results),
        ragas_available=ragas_rows is not None,
        ragas_skip_reason=None if ragas_rows is not None else ragas_skip_reason,
        langfuse={"pushed": False, "skip_reason": "未执行推送", "scores_written": 0, "failures": []},
    )
    langfuse_status = push_scores_to_langfuse(report, client=langfuse_client)
    return Layer2Report(
        run_id=report.run_id,
        kb_id=report.kb_id,
        generated_at=report.generated_at,
        results=report.results,
        aggregate=report.aggregate,
        ragas_available=report.ragas_available,
        ragas_skip_reason=report.ragas_skip_reason,
        langfuse=langfuse_status,
        calibration=report.calibration,
    )


# ---------------------------------------------------------------------------
# Production agent runner (real conversation chain via the lead agent)
# ---------------------------------------------------------------------------


def build_lead_agent_runner(
    *,
    kb_id: str,
    user_id: str,
    run_id: str,
    model_name: str | None = None,
) -> Callable[[GoldenQuestion], Awaitable[TraceOutcome]]:
    """Real ``agent_runner``: one fresh lead-agent run per golden question.

    Each question gets a new thread_id (fresh runtime context → the shared
    citation counter restarts at 1, so the citation map is per-question) and
    runs as the ``rag`` agent — the only preset whose ``tool_groups`` carry the
    three retrieval tools. ``deep_research`` is deliberately left UNSET so the
    DeepResearchMiddleware stays passive and the agent picks paths on its own;
    otherwise the mandatory three-path instruction would make path-selection
    accuracy trivially 100% and meaningless.
    """

    async def runner(question: GoldenQuestion) -> TraceOutcome:
        from deerflow.agents.lead_agent.agent import make_lead_agent
        from deerflow.tracing import build_langfuse_trace_metadata

        thread_id = uuid.uuid4().hex
        context: dict[str, Any] = {"kb_id": kb_id, "user_id": user_id, "agent_name": "rag"}
        if model_name:
            context["model_name"] = model_name
        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id},
            "context": context,
            "recursion_limit": 300,
            # D4 观测：逐 LLM 调用计时（debug 级、只记耗时/token）；make_lead_agent
            # 把 langfuse 追加进同一列表。
            "callbacks": [EvalCallTimingHandler()],
            # langfuse_session_id ← run_id groups all questions of one eval run
            # into one Langfuse session; trace name carries the question id.
            "metadata": build_langfuse_trace_metadata(
                thread_id=run_id,
                user_id=user_id,
                assistant_id=f"ragas-eval[{question.id}]",
                environment="eval",
            ),
        }
        graph = make_lead_agent(config)
        # Direct-invocation context rule (verified 2026-08-24): on a plain
        # ``graph.ainvoke`` the ``config["context"]`` mapping does NOT reach
        # ``ToolRuntime.context`` — only the top-level ``context=`` argument
        # does (the gateway path works because langgraph-runtime maps
        # ``config["context"]`` onto it). kb_id/user_id are read by the
        # retrieval tools from ``runtime.context``, so they MUST go here.
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": question.query}]},
            config,
            context={"kb_id": kb_id, "user_id": user_id},
        )
        messages = result.get("messages", []) if isinstance(result, Mapping) else []
        return TraceOutcome(
            question_id=question.id,
            answer=extract_answer(messages),
            retrieval_tools=extract_retrieval_tools(messages),
            citation_map=extract_citation_map(messages),
            seed_entities=extract_seed_entities(messages),
            thread_id=thread_id,
            trace_id=_langfuse_trace_id_from_callbacks(config),
        )

    return runner


def _langfuse_trace_id_from_callbacks(config: Mapping[str, Any]) -> str | None:
    """Best-effort: read the trace id off the langfuse callback handler that
    ``make_lead_agent`` attached to this config (``None`` when not enabled)."""

    for callback in config.get("callbacks") or []:
        getter = getattr(callback, "get_trace_id", None)
        if callable(getter):
            try:
                trace_id = getter()
            except Exception:  # noqa: BLE001 — observability must never break a run
                continue
            if trace_id:
                return str(trace_id)
    return None


# ---------------------------------------------------------------------------
# Report serialization
# ---------------------------------------------------------------------------


def report_to_dict(report: Layer2Report) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "kb_id": report.kb_id,
        "generated_at": report.generated_at,
        "ragas_available": report.ragas_available,
        "ragas_skip_reason": report.ragas_skip_reason,
        "langfuse": dict(report.langfuse),
        "calibration": dict(report.calibration),
        "aggregate": dict(report.aggregate),
        "results": [
            {
                "question_id": r.question_id,
                "category": r.category,
                "expected_paths": list(r.expected_paths),
                "path_hit": r.path_hit,
                "first_tool": r.first_tool,
                "retrieval_tools": list(r.retrieval_tools),
                "citation": None
                if r.citation is None
                else {
                    "precision": r.citation.precision,
                    "recall": r.citation.recall,
                    "claims_judged": r.citation.claims_judged,
                    "unsupported": list(r.citation.unsupported),
                    "missing": list(r.citation.missing),
                },
                "graph_entity_hit_rate": r.graph_entity_hit_rate,
                "ragas": dict(r.ragas),
                "thread_id": r.thread_id,
                "trace_id": r.trace_id,
                "failure": r.failure,
            }
            for r in report.results
        ],
    }


def report_from_dict(data: Mapping[str, Any]) -> Layer2Report:
    results = []
    for raw in data["results"]:
        citation = raw.get("citation")
        results.append(
            QuestionEvalResult(
                question_id=raw["question_id"],
                category=raw["category"],
                # 双键兼容（§9）：旧报告存单值 ``expected_path``，新报告存列表。
                expected_paths=tuple(raw.get("expected_paths") or ([raw["expected_path"]] if raw.get("expected_path") else [])),
                path_hit=raw.get("path_hit"),
                first_tool=raw.get("first_tool"),
                retrieval_tools=tuple(raw.get("retrieval_tools") or ()),
                citation=None
                if citation is None
                else CitationScore(
                    precision=citation.get("precision"),
                    recall=citation.get("recall"),
                    claims_judged=citation.get("claims_judged", 0),
                    unsupported=tuple(citation.get("unsupported") or ()),
                    missing=tuple(citation.get("missing") or ()),
                ),
                graph_entity_hit_rate=raw.get("graph_entity_hit_rate"),
                ragas=dict(raw.get("ragas") or {}),
                thread_id=raw.get("thread_id"),
                trace_id=raw.get("trace_id"),
                failure=raw.get("failure"),
            )
        )
    return Layer2Report(
        run_id=data["run_id"],
        kb_id=data["kb_id"],
        generated_at=data["generated_at"],
        results=tuple(results),
        aggregate=dict(data["aggregate"]),
        ragas_available=bool(data["ragas_available"]),
        ragas_skip_reason=data.get("ragas_skip_reason"),
        langfuse=dict(data.get("langfuse") or {}),
        calibration=dict(data.get("calibration") or {}),
    )


def _fmt(value: float | None, *, pct: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}" if pct else f"{value:.3f}"


def render_markdown(report: Layer2Report) -> str:
    aggregate = report.aggregate
    lines = [
        "# RAG 检索质量评估报告（Layer 2 · 端到端 / RAGAS）",
        "",
        f"- run_id：`{report.run_id}`",
        f"- kb_id：`{report.kb_id}`",
        f"- 生成时间：{report.generated_at}",
        f"- 题目数：{aggregate['questions']}（失败 {aggregate['failures']}）",
        "",
        "## 人工校准",
        "",
        f"- human_sample_ratio：{report.calibration.get('human_sample_ratio') or '未回填'}",
        f"- cohens_kappa：{report.calibration.get('cohens_kappa') or '未回填'}",
        f"- 约定：{report.calibration.get('notes', '每月抽样 ≥10% 人工评分后回填。')}",
        "",
        "## 执行状态",
        "",
        f"- ragas：{'可用' if report.ragas_available else f'skipped（{report.ragas_skip_reason}）'}",
        f"- langfuse：{'已推送 ' + str(report.langfuse.get('scores_written', 0)) + ' 条 score' if report.langfuse.get('pushed') else '未推送（' + str(report.langfuse.get('skip_reason') or '无 trace') + '）'}",
        "",
        "## 汇总（不含失败题）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 路径选择准确率 | {_fmt(aggregate['path_accuracy'])} |",
        f"| 引用 precision | {_fmt(aggregate['citation_precision'])} |",
        f"| 引用 recall | {_fmt(aggregate['citation_recall'])} |",
        f"| 图谱落点命中率 | {_fmt(aggregate['graph_entity_hit_rate'])} |",
    ]
    for name in RAGAS_METRIC_NAMES:
        lines.append(f"| ragas {name} | {_fmt(aggregate['ragas'].get(name))} |")

    lines += ["", "## 按类别", "", "| 类别 | 题数 | 路径选择准确率 |", "|---|---|---|"]
    for category, bucket in aggregate.get("by_category", {}).items():
        lines.append(f"| {category} | {bucket['questions']} | {_fmt(bucket['path_accuracy'])} |")

    def _render_rows(rows: list[QuestionEvalResult]) -> None:
        lines.extend(["", "| 题目 | 预期路径 | 实际工具序列 | 路径命中 | 引用 P/R | 图谱落点 | 备注 |", "|---|---|---|---|---|---|---|"])
        for r in rows:
            citation = r.citation
            pr = "-" if citation is None else f"{_fmt(citation.precision)}/{_fmt(citation.recall)}"
            note = r.failure or ""
            if citation and citation.missing:
                note = (note + " " if note else "") + f"幻觉引用 {list(citation.missing)}"
            tools = ", ".join(r.retrieval_tools) or "（未检索）"
            lines.append(f"| {r.question_id} | {'/'.join(r.expected_paths)} | {tools} | {'✅' if r.path_hit else '❌'} | {pr} | {_fmt(r.graph_entity_hit_rate)} | {note} |")

    regular = [r for r in report.results if r.category != "global"]
    global_rows = [r for r in report.results if r.category == "global"]
    lines += ["", "## 逐题明细"]
    _render_rows(regular)
    if global_rows:
        lines += ["", "## Global 类题目（单独分区，结果不计入门禁解读）"]
        _render_rows(global_rows)

    failures = [r for r in report.results if r.failure]
    if failures:
        lines += ["", "## 失败题目", ""]
        for r in failures:
            lines.append(f"- `{r.question_id}`：{r.failure}")
    return "\n".join(lines) + "\n"


def write_reports(report: Layer2Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ragas-report.json"
    md_path = out_dir / "ragas-report.md"
    json_path.write_text(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
