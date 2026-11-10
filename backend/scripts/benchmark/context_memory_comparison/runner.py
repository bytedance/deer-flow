"""Run synthetic prompt checks through the local Gateway and real SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from contextlib import chdir
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"
REPLY = "Offline benchmark response."
DAY = "2026-11-09, Monday"
_PROJECT_SCOPE_TRACE = "benchmark-project-scope"
_EMPTY_UPDATE = {"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}
_SCRIPTED_UPDATE: ContextVar[dict[str, Any] | None] = ContextVar("offline_memory_update", default=None)


class OfflineModel(BaseChatModel):
    """Capture agent requests and return fixed replies for both model roles."""

    model: str
    temperature: float = 0.0
    requests: ClassVar[list[list[BaseMessage]]] = []

    @property
    def _llm_type(self) -> str:
        return "context-memory-offline"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.model == "extract":
            content = json.dumps(_SCRIPTED_UPDATE.get() or _EMPTY_UPDATE)
        else:
            self.requests.append(list(messages))
            content = REPLY
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def _request(client: TestClient, method: str, path: str, **kwargs) -> dict:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def _thread(client: TestClient, project_id: str | None = None) -> str:
    return _request(client, "POST", "/api/threads", json={"project_id": project_id})["thread_id"]


def _prompt(client: TestClient, thread_id: str, question: str, assistant_id: str = "lead_agent") -> list[BaseMessage]:
    OfflineModel.requests.clear()
    result = _request(
        client,
        "POST",
        f"/api/threads/{thread_id}/runs/wait",
        json={
            "assistant_id": assistant_id,
            "input": {"messages": [{"role": "user", "content": question}]},
            "config": {"configurable": {"model_name": "record", "thinking_enabled": False}},
        },
    )
    messages = result.get("messages") or []
    if len(OfflineModel.requests) != 1 or not messages or messages[-1].get("content") != REPLY:
        raise RuntimeError("Gateway run did not complete with exactly one recorded model request")
    return OfflineModel.requests.pop()


def _present(text: str, canaries: set[str]) -> list[str]:
    return sorted(canary for canary in canaries if canary in text)


def _observe(messages: list[BaseMessage], canaries: set[str], expected: set[str]) -> dict:
    from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _count_tokens
    from deerflow.projects.context import is_project_context_message

    present = _present("\n".join(str(message.content) for message in messages), canaries)
    blocks = {"memory": [], "project": [], "documents": []}
    for message in messages:
        if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
            continue
        if message.content.startswith("<memory>"):
            blocks["memory"].append(message.content)
        if is_project_context_message(message):
            for tag in ("project", "documents"):
                blocks[tag].extend(re.findall(rf"<{tag}(?:\s[^>]*)?>.*?</{tag}>", message.content, flags=re.DOTALL))
    return {
        "passed": set(present) == expected,
        "present": present,
        "context_token_estimate": {name: sum(_count_tokens(block, use_tiktoken=False) for block in values) for name, values in blocks.items()},
    }


def _extract(thread_id: str, instruction: str, *, new_facts: list[dict], removals: list[dict], trace_id: str | None = None) -> bool:
    from deerflow.agents.memory import get_memory_manager
    from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    token = _SCRIPTED_UPDATE.set({**_EMPTY_UPDATE, "newFacts": new_facts, "factsToRemove": removals})
    try:
        # Execute the production write synchronously so its outcome precedes
        # the next Gateway run. Ordinary background extractions are no-ops.
        return get_memory_manager()._updater.update_memory(
            [HumanMessage(content=instruction), AIMessage(content="Understood.")],
            thread_id=thread_id,
            user_id=DEFAULT_USER_ID,
            agent_name=DEFAULT_AGENT_BUCKET,
            trace_id=trace_id,
            bypass_watermark=True,
        )
    finally:
        _SCRIPTED_UPDATE.reset(token)


def _fact(content: str) -> dict:
    return {"content": content, "category": "preference", "confidence": 0.99}


def _extracted_fact(content: str, scope: str) -> dict:
    return {**_fact(content), "scope": scope, "durability": "durable", "authority": "descriptive"}


def _scope_isolation(client: TestClient, fixture: dict, project_extraction_metrics: dict) -> dict:
    default_fact = fixture["default_fact"]
    agent = fixture["agent"]
    agent_fact = fixture["agent_fact"]
    rejected = fixture["project_only_fact"]
    _request(client, "POST", "/api/memory/facts", json=_fact(default_fact))
    _request(client, "POST", "/api/agents", json={"name": agent, "model": "record", "soul": "Synthetic benchmark agent."})
    _request(client, "POST", "/api/memory/facts", params={"agent_name": agent}, json=_fact(agent_fact))

    threads = {}
    project_canaries = {}
    for label, project in fixture["projects"].items():
        project_id = _request(client, "POST", "/api/projects", json={"name": label, "instructions": project["instructions"]})["id"]
        document = project["document"]
        _request(client, "POST", f"/api/projects/{project_id}/documents", files={"file": (document, document.encode("utf-8"), "text/plain")})
        threads[label] = _thread(client, project_id)
        project_canaries[label] = {project["instructions"], document}

    canaries = {default_fact, agent_fact, rejected}.union(*project_canaries.values())
    question = fixture["question"]
    observations = {label: _observe(_prompt(client, thread, question), canaries, {default_fact, *project_canaries[label]}) for label, thread in threads.items()}
    observations["unassigned"] = _observe(_prompt(client, _thread(client), question), canaries, {default_fact})
    observations["custom_agent"] = _observe(_prompt(client, _thread(client), question, agent), canaries, {agent_fact})

    updated = _extract(
        threads["alpha"],
        "Apply this preference only in the current project.",
        new_facts=[_extracted_fact(rejected, "project")],
        removals=[],
        trace_id=_PROJECT_SCOPE_TRACE,
    )
    project_fact = {"update_succeeded": updated, "passed": False}
    if updated:
        scope_rejections = project_extraction_metrics.get("scope_gate_rejections", {}).get("facts", {}).get("scope", 0)
        stored = bool(_present(json.dumps(_request(client, "GET", "/api/memory")), {rejected}))
        beta = _observe(_prompt(client, threads["beta"], question), canaries, {default_fact, *project_canaries["beta"]})
        project_fact.update({"scope_rejections": scope_rejections, "stored": stored, "other_thread": beta, "passed": scope_rejections == 1 and not stored and beta["passed"]})

    return {
        "passed": all(turn["passed"] for turn in observations.values()) and project_fact["passed"],
        "threads": observations,
        "project_only_fact": project_fact,
    }


def _invalidation(client: TestClient, fixture: dict, case: dict) -> dict:
    from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory

    old = case["old"]
    new = case.get("new")
    control = fixture["default_fact"]
    history = fixture["thread_history_control"]
    canaries = {old, control, history}
    after = {control}
    removal = {"id": "superseded-fact", "scope": "user", "reason": "The user invalidated the old preference."}
    new_facts = []
    if new is not None:
        canaries.add(new)
        after.add(new)
        removal["replacementFactIndex"] = 0
        new_facts.append(_extracted_fact(new, "user"))

    seed = create_empty_memory()
    seed["facts"] = [
        {**_fact(old), "id": removal["id"], "source": "synthetic"},
        {**_fact(control), "id": "control-fact", "source": "synthetic"},
    ]
    _request(client, "POST", "/api/memory/import", json=seed)
    original = _thread(client)
    question = fixture["question"]
    before = _observe(_prompt(client, original, f"{question} {history}"), canaries, {old, control, history})
    updated = _extract(original, "Forget the old preference.", new_facts=new_facts, removals=[removal])
    if not updated:
        return {"passed": False, "update_succeeded": False, "before": before}

    stored = _present(json.dumps(_request(client, "GET", "/api/memory")), canaries)
    same = _observe(_prompt(client, original, question), canaries, after | {history})
    fresh = _observe(_prompt(client, _thread(client), question), canaries, after)
    return {
        "passed": before["passed"] and set(stored) == after and same["passed"] and fresh["passed"],
        "update_succeeded": True,
        "before": before,
        "stored": stored,
        "same_thread": same,
        "new_thread": fresh,
    }


def _config() -> dict:
    return {
        # DeerMem uses the first configured model for extraction. Runs
        # explicitly select the recording model so these calls stay separate.
        "models": [{"name": name, "use": f"{__name__}:OfflineModel", "model": name, "temperature": 0, "supports_tool_calling": True} for name in ("extract", "record")],
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "database": {"backend": "sqlite", "sqlite_dir": "db"},
        "run_events": {"backend": "db"},
        "log_level": "WARNING",
        "title": {"enabled": False},
        "summarization": {"enabled": False},
        "agents_api": {"enabled": True},
        "memory": {
            "backend_config": {
                "token_counting": "char",
                "retrieval_adapter": "",
                "staleness_review_enabled": False,
                "consolidation_enabled": False,
            },
        },
        "skills": {"path": "skills"},
    }


def run_offline() -> dict:
    """Use a disposable Gateway config and data directory in a standalone process."""
    fixture_bytes = MANIFEST.read_bytes()
    fixture = json.loads(fixture_bytes)
    canaries = [fixture[key] for key in ("default_fact", "agent_fact", "project_only_fact", "thread_history_control")]
    canaries.extend(value for project in fixture["projects"].values() for value in project.values())
    canaries.extend(value for case in fixture["invalidation"].values() for value in case.values())
    if len(set(canaries)) != len(canaries):
        raise ValueError("Synthetic canaries must be distinct")

    config_bytes = json.dumps(_config(), sort_keys=True).encode("utf-8")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    project_extraction_metrics: dict[str, Any] = {}

    def record_project_extraction(payload: dict[str, Any]) -> None:
        # The explicit project update has its own trace. Ignore background extractions.
        if payload.get("trace_id") == _PROJECT_SCOPE_TRACE:
            project_extraction_metrics.update(payload)

    with TemporaryDirectory(prefix="deerflow-context-memory-", ignore_cleanup_errors=True) as directory:
        root = Path(directory).resolve()
        (root / "config.yaml").write_bytes(config_bytes)
        (root / "extensions.json").write_text("{}", encoding="utf-8")
        (root / "empty.env").touch()
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
        env.update(
            DEER_FLOW_AUTH_DISABLED="1",
            DEER_FLOW_HOME=str(root / "home"),
            DEER_FLOW_PROJECT_ROOT=str(root),
            DEER_FLOW_CONFIG_PATH=str(root / "config.yaml"),
            DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(root / "extensions.json"),
            DEER_FLOW_ENV_FILE=str(root / "empty.env"),
        )
        with patch.dict(os.environ, env, clear=True), chdir(root):
            from app.gateway.app import app

            with (
                patch("deerflow.agents.memory.manager._host_default_extraction_callback", new=record_project_extraction),
                patch("deerflow.agents.middlewares.dynamic_context_middleware._format_current_date", return_value=DAY),
                TestClient(app) as client,
            ):
                scope = _scope_isolation(client, fixture, project_extraction_metrics)
                invalidation = {name: _invalidation(client, fixture, case) for name, case in fixture["invalidation"].items()}

    return {
        "source_revision": revision,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "dataset": fixture["dataset"],
        "prompt_path": "Gateway runs/wait to recording model",
        "checkpoint_backend": "sqlite",
        "token_estimate_method": "character estimate of injected blocks",
        "date": DAY,
        "passed": scope["passed"] and all(case["passed"] for case in invalidation.values()),
        "scope_isolation": scope,
        "invalidation": invalidation,
    }
