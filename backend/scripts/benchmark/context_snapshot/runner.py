"""Explicit live execution; no runtime patching, configuration or I/O on import."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import logging
import math
import os
import random
import subprocess
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from .cases import CASES
from .grading import passed, score
from .prompts import DISPATCH_POLICIES, LEAD_SYSTEM, WORKER_SYSTEM
from .report import clean_success, summarize, usage

CURRENT_MODEL = ContextVar("snapshot_benchmark_model")
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    expected = {"protocol", "temperature", "reasoning_effort", "max_tokens", "context_window", "http_timeout_seconds", "worker_timeout_seconds", "max_graph_steps", "max_retries", "seed", "order_seed", "concurrency"}
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError("Unsupported config fields; use the committed config schema, with provider settings only in environment variables")
    for name in ("max_tokens", "context_window", "http_timeout_seconds", "worker_timeout_seconds", "max_graph_steps", "concurrency"):
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name in ("seed", "order_seed"):
        if type(config[name]) is not int:
            raise ValueError(f"{name} must be an integer")
    if not isinstance(config["temperature"], (int, float)) or not math.isfinite(config["temperature"]) or not 0 <= config["temperature"] <= 2:
        raise ValueError("temperature must be finite and between 0 and 2")
    if config["reasoning_effort"] not in (None, "none", "minimal", "low", "medium", "high", "xhigh"):
        raise ValueError("Unsupported reasoning_effort")
    if config["max_retries"] != 0:
        raise ValueError("This protocol does not retry provider calls")
    return config


def parent_state(case):
    messages = [SystemMessage(content="Parent-only role: coordinate the synthetic project.")]
    for index, (role, content) in enumerate(case.history):
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            call_id = f"historical-{case.name}-{index}"
            name = "run_public_checks" if case.name == "fresh_evidence" else "read_reference"
            args = {"document": "archived-note"} if name == "read_reference" else {}
            messages.append(AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}]))
            messages.append(ToolMessage(content=content, name=name, tool_call_id=call_id))
    messages.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {"prompt": case.brief}, "id": "current-dispatch"}]))
    return {"messages": messages, "summary_text": case.summary}


class Transport:
    """Retain only usage/status/timing. Never retain headers or full payloads."""

    def __init__(self, base_url, api_key, model, config, seed):
        self.calls = []
        self.stage = "lead_dispatch"
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=config["http_timeout_seconds"], trust_env=False, event_hooks={"request": [self.on_request], "response": [self.on_response]})
        self.model = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key or "unused",
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            max_retries=config["max_retries"],
            timeout=config["http_timeout_seconds"],
            reasoning_effort=config["reasoning_effort"],
            seed=seed,
            streaming=False,
            disable_streaming=True,
            http_async_client=self.client,
        )

    async def on_request(self, request):
        if not self.api_key:
            request.headers.pop("authorization", None)
        entry = {"stage": self.stage, "usage": None, "http_status": None}
        self.calls.append(entry)
        request.extensions["benchmark_call"] = (entry, time.perf_counter())

    async def on_response(self, response):
        await response.aread()
        entry, start = response.request.extensions["benchmark_call"]
        entry.update(http_status=response.status_code, seconds=time.perf_counter() - start)
        try:
            body = response.json()
            raw = body.get("usage") or {}
            entry["usage"] = {key: raw[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(raw.get(key), int)}
            cached = (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
            if isinstance(cached, int):
                entry["usage"]["prompt_tokens_details"] = {"cached_tokens": cached}
        except (ValueError, AttributeError, TypeError):
            pass  # Missing/unparseable usage remains explicitly incomplete.


async def run_one(case, arm, repetition, output, config, provider):
    from deerflow.config.app_config import AppConfig
    from deerflow.extensions.registry import ExtensionRegistry
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.context_snapshot import ParentContextSnapshot
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools.builtins.task_tool import task_tool

    job_id = f"{case.name}__{repetition}__{arm}"
    directory = output / job_id
    directory.mkdir()
    artifact = directory / ("artifact.json" if case.kind == "json" else "artifact.py")
    contents, events = [], []
    checked_revision, public_ok = None, False

    @tool
    async def write_artifact(content: str) -> str:
        """Save the complete task artifact. Supply raw JSON or Python, without markdown fences."""
        await asyncio.to_thread(artifact.write_text, content, encoding="utf-8")
        contents.append(content)
        await asyncio.to_thread(artifact.with_stem(f"revision-{len(contents)}").write_text, content, encoding="utf-8")
        events.append({"tool": "write_artifact", "revision": len(contents)})
        return f"Saved revision {len(contents)} to {artifact.name}"

    @tool
    async def read_reference(document: str) -> str:
        """Read a bundled reference by the exact document name given in the task."""
        events.append({"tool": "read_reference"})
        return case.references.get(document, "No such bundled document. Use only the requirements already supplied in the task and conversation.")

    @tool
    async def run_public_checks() -> str:
        """Check the saved artifact's public shape/basic example. Checks do not replace the full task requirements."""
        nonlocal checked_revision, public_ok
        grade = await asyncio.to_thread(score, case, contents[-1] if contents else None, public=True)
        checked_revision, public_ok = len(contents), passed(grade)
        events.append({"tool": "run_public_checks", "revision": checked_revision, "passed": public_ok})
        return json.dumps({"public_checks_passed": public_ok, "revision": checked_revision, "details": grade})

    transport = Transport(*provider, config, config["seed"] + repetition)
    start, lead_seconds = time.perf_counter(), 0
    result, dispatch, error_type = None, None, None
    snapshot = ParentContextSnapshot.from_state(parent_state(case))
    try:
        response = await transport.model.bind_tools([task_tool], tool_choice="task").ainvoke(
            [
                SystemMessage(content=LEAD_SYSTEM + DISPATCH_POLICIES[arm]),
                snapshot.to_message(),
                HumanMessage(content="Current task:\n" + case.brief),
            ]
        )
        lead_seconds = time.perf_counter() - start
        if len(response.tool_calls) != 1 or response.tool_calls[0]["name"] != "task":
            raise ValueError("Expected one task call")
        dispatch = response.tool_calls[0]["args"]
        task_tool.tool_call_schema.model_validate(dispatch)
        expected_mode = "snapshot" if arm == "snapshot" else "isolated"
        if dispatch.get("context_mode", "isolated") != expected_mode or dispatch.get("subagent_type") != "general-purpose":
            raise ValueError("Dispatch mode mismatch")
        transport.stage = "worker"
        app_config = AppConfig.model_validate(
            {
                "models": [{"name": "eval", "use": "langchain_openai:ChatOpenAI", "model": provider[2], "context_window": config["context_window"]}],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "authorization": {"enabled": False},
                "skills": {"deferred_discovery": False},
                "tool_search": {"enabled": False},
                "summarization": {"enabled": False},
                "memory": {"enabled": False},
            }
        )
        executor = SubagentExecutor(
            config=SubagentConfig(
                name="live-eval",
                description="Synthetic implementation worker",
                system_prompt=WORKER_SYSTEM,
                tools=["write_artifact", "read_reference", "run_public_checks"],
                skills=[],
                model="eval",
                max_turns=config["max_graph_steps"],
                timeout_seconds=config["worker_timeout_seconds"],
            ),
            tools=[write_artifact, read_reference, run_public_checks],
            app_config=app_config,
            context_snapshot=snapshot if arm == "snapshot" else None,
            acceptance_criteria=dispatch.get("acceptance_criteria"),
            thread_id=job_id,
            run_id=job_id,
            user_id="synthetic-eval",
            extensions=ExtensionRegistry().build(),
        )
        token = CURRENT_MODEL.set(transport.model)
        try:
            result = await asyncio.wait_for(executor._aexecute(dispatch["prompt"]), timeout=config["worker_timeout_seconds"])
        finally:
            CURRENT_MODEL.reset(token)
    except Exception as exc:
        error_type = type(exc).__name__  # Provider exceptions may contain endpoint/key values.
    finally:
        elapsed = time.perf_counter() - start
        if transport.stage == "lead_dispatch":
            lead_seconds = elapsed
        await transport.client.aclose()
    grade = await asyncio.to_thread(score, case, contents[-1] if contents else None)
    first_grade = await asyncio.to_thread(score, case, contents[0] if contents else None)
    row = {
        "case": case.name,
        "arm": arm,
        "repetition": repetition,
        "artifact_correct": passed(grade),
        "first_artifact_correct": passed(first_grade),
        "fresh_public_check": bool(contents) and checked_revision == len(contents) and public_ok,
        "executor_status": result.status.value if result else None,
        "stop_reason": result.stop_reason if result else None,
        "error_type": error_type,
        "seconds": elapsed,
        "lead_seconds": lead_seconds,
        "usage": usage(transport.calls),
        "lead_usage": usage([call for call in transport.calls if call["stage"] == "lead_dispatch"]),
        "worker_usage": usage([call for call in transport.calls if call["stage"] == "worker"]),
        "brief_policy_adhered": dispatch["prompt"].strip() == case.brief.strip() if dispatch and arm == "snapshot" else None,
        "acceptance_criteria_added": bool(dispatch and dispatch.get("acceptance_criteria")),
    }
    row["clean_success"] = clean_success(row)
    # Full dispatch / grades stay in the ignored local output, outside public rows.
    (directory / "details.json").write_text(json.dumps({"dispatch": dispatch, "grade": grade, "first_grade": first_grade, "events": events}, indent=2), encoding="utf-8")
    (directory / "calls.json").write_text(json.dumps(transport.calls, indent=2), encoding="utf-8")
    (directory / "result.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    print(f"{job_id}: artifact={row['artifact_correct']} completed={row['clean_success']}", flush=True)
    return row


async def run_live(args):
    provider = tuple(os.environ.get(name, "").strip() for name in ("CONTEXT_SNAPSHOT_BASE_URL", "CONTEXT_SNAPSHOT_API_KEY", "CONTEXT_SNAPSHOT_MODEL"))
    if not provider[0] or not provider[2]:
        raise ValueError("Set CONTEXT_SNAPSHOT_BASE_URL and CONTEXT_SNAPSHOT_MODEL; API key is optional for keyless endpoints")
    config = load_config(args.config)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never mix runs or overwrite failures.
    (output / ".gitignore").write_text("*\n", encoding="utf-8")
    selected = [case for case in CASES if not args.cases or case.name in args.cases]
    jobs = [(case, arm, rep) for rep in range(args.repetitions) for case in selected for arm in DISPATCH_POLICIES]
    random.Random(config["order_seed"]).shuffle(jobs)
    source_paths = list(ROOT.glob("*.py")) + [
        args.config.resolve(),
        REPO / "backend/packages/harness/deerflow/subagents/context_snapshot.py",
        REPO / "backend/packages/harness/deerflow/subagents/executor.py",
        REPO / "backend/packages/harness/deerflow/tools/builtins/task_tool.py",
    ]
    metadata = {
        "config": config,
        "model": provider[2],
        "provider_env": ["CONTEXT_SNAPSHOT_BASE_URL", "CONTEXT_SNAPSHOT_API_KEY", "CONTEXT_SNAPSHOT_MODEL"],
        "started_at": datetime.now(UTC).isoformat(),
        "clock": "perf_counter; queue wait excluded",
        "synthetic": True,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True)),
        "sha256": {str(path.relative_to(REPO)) if path.is_relative_to(REPO) else "external-config": hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
        "versions": {name: importlib.metadata.version(name) for name in ("deerflow-harness", "langchain", "langgraph", "langchain-openai", "httpx")},
        "jobs": [f"{case.name}__{rep}__{arm}" for case, arm, rep in jobs],
    }
    (output / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    env = {"DEER_FLOW_HOME": str(output / "runtime"), "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}
    with patch.dict(os.environ, env):
        import deerflow.subagents.executor as executor_module

        # Scope instrumentation to this standalone run and restore it afterward.
        with patch.object(executor_module, "create_chat_model", side_effect=lambda *a, **kw: CURRENT_MODEL.get()), patch.object(executor_module, "build_tracing_callbacks", return_value=[]):
            semaphore = asyncio.Semaphore(config["concurrency"])

            async def run(job):
                async with semaphore:
                    row = await run_one(*job, output, config, provider)
                    with (output / "rows.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps(row, sort_keys=True) + "\n")
                    return row

            rows = await asyncio.gather(*(run(job) for job in jobs))
    (output / "summary.json").write_text(json.dumps(summarize(rows), indent=2), encoding="utf-8")
