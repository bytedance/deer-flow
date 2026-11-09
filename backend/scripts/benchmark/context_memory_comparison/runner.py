from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig, DeerMemModelConfig
from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _count_tokens, format_memory_for_injection
from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory, create_storage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.projects.context import build_project_context_message, render_documents_block, render_project_block

from .contract import Protocol, ScopeIsolationCase, TokenOverheadCase, TurnInvalidationCase

ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = ROOT.parents[2]
ROW_SCHEMA_VERSION = 1
MARKER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunReport:
    reused: int
    executed: int


class _StaticModel:
    def __init__(self, output: dict[str, Any]):
        self.output = output
        self.prompt_sha256: str | None = None

    def invoke(self, prompt: Any, config: dict[str, Any] | None = None) -> Any:
        self.prompt_sha256 = _sha256_json(_prompt_projection(prompt))
        return SimpleNamespace(content=json.dumps(self.output), usage_metadata={})


def _prompt_projection(prompt: Any) -> list[dict[str, str]]:
    if not isinstance(prompt, (list, tuple)):
        return [{"type": "raw", "content": str(prompt)}]
    return [
        {"type": str(getattr(message, "type", "unknown")), "content": str(getattr(message, "content", message))}
        for message in prompt
    ]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git_revision() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def protocol_artifacts(manifest_path: Path) -> dict[str, str | None]:
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "source_revision": _git_revision(),
    }


def _marker(mode: str, protocol: Protocol, manifest_path: Path) -> dict[str, Any]:
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "protocol_id": protocol.protocol_id,
        "mode": mode,
        "artifacts": protocol_artifacts(manifest_path),
        "model": {"provider": "deterministic-static", "model": "offline-fixture", "temperature": 0.0},
    }


def ensure_run_identity(
    output_dir: Path,
    *,
    mode: str,
    protocol: Protocol,
    manifest_path: Path,
) -> dict[str, Any]:
    expected = _marker(mode, protocol, manifest_path)
    marker_path = output_dir / "run.json"
    if marker_path.exists():
        actual = json.loads(marker_path.read_text(encoding="utf-8"))
        comparable = {key: actual.get(key) for key in expected}
        if comparable != expected:
            raise ValueError(f"{marker_path} belongs to a different protocol, source revision, or mode")
        return actual
    marker = dict(expected)
    marker["created_at"] = datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"
    _atomic_write_json(marker_path, marker)
    return marker


def _case_fingerprint(suite: str, case_data: dict[str, Any], marker: dict[str, Any]) -> str:
    return _sha256_json(
        {
            "protocol_id": marker["protocol_id"],
            "mode": marker["mode"],
            "artifacts": marker["artifacts"],
            "suite": suite,
            "case": case_data,
        }
    )


def _row_path(output_dir: Path, suite: str, row_id: str) -> Path:
    return output_dir / "rows" / suite / f"{row_id}.json"


def row_result_sha256(row: dict[str, Any]) -> str:
    return _sha256_json({key: value for key, value in row.items() if key != "result_sha256"})


def _seal_row(row: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(row)
    sealed["result_sha256"] = row_result_sha256(sealed)
    return sealed


def row_is_intact(row: dict[str, Any]) -> bool:
    digest = row.get("result_sha256")
    return isinstance(digest, str) and digest == row_result_sha256(row)


def _load_reusable_row(path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict) or row.get("schema_version") != ROW_SCHEMA_VERSION or row.get("request_fingerprint") != fingerprint or not row_is_intact(row):
        return None
    return row


def _config(storage_path: Path) -> DeerMemConfig:
    return DeerMemConfig(
        storage_path=str(storage_path),
        retrieval_adapter="",
        token_counting="char",
        staleness_review_enabled=False,
        consolidation_enabled=False,
        model=DeerMemModelConfig(model="offline-fixture", temperature=0.0),
    )


def _assemble_thread_prompt(
    updater: MemoryUpdater,
    *,
    thread_id: str,
    user_id: str,
    agent_name: str,
    project_context: dict[str, Any] | None,
    query_text: str = "Test prompt",
) -> tuple[str, list[Any]]:
    memory_data = updater.get_memory_data(agent_name=agent_name, user_id=user_id)
    memory_text = format_memory_for_injection(memory_data, use_tiktoken=False)
    memory_block = f"<memory>\n{memory_text}\n</memory>" if memory_text.strip() else None

    orig_msg = HumanMessage(content=query_text, id=f"msg-{thread_id}")
    reminder_content = "<system-reminder>\n<current_date>2026-11-06, Friday</current_date>\n</system-reminder>"
    messages = DynamicContextMiddleware._make_reminder_and_user_messages(
        orig_msg,
        reminder_content=reminder_content,
        memory_content=memory_block,
        reminder_date="2026-11-06, Friday",
    )

    if project_context is not None:
        p_blk = render_project_block(project_context)
        d_blk = render_documents_block(project_context, max_entries=10, max_bytes=4096)
        if p_blk is not None:
            combined_block = p_blk if d_blk is None else f"{p_blk}\n{d_blk}"
            proj_msg = build_project_context_message(combined_block, run_id=f"run-{thread_id}")
            user_idx = next(
                (i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and str(m.id or "").endswith("__user")),
                len(messages),
            )
            messages = [*messages[:user_idx], proj_msg, *messages[user_idx:]]

    full_text = "\n\n".join(str(getattr(m, "content", "")) for m in messages)
    return full_text, messages


def _storage_contains_canary(memory: dict[str, Any], canary: str) -> bool:
    for fact in memory.get("facts", []):
        if isinstance(fact, dict) and canary in str(fact.get("content", "")):
            return True
    for group in ("user", "history"):
        sections = memory.get(group, {})
        if not isinstance(sections, dict):
            continue
        for section in sections.values():
            if isinstance(section, dict) and canary in str(section.get("summary", "")):
                return True
    return False


def _run_scope_isolation_case(
    case: ScopeIsolationCase,
    marker: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="deerflow-bench-iso-") as td:
        storage_path = Path(td)
        config = _config(storage_path)

        contam_output = case.contamination_turn.get("offline_output", {}) if case.contamination_turn else {}
        model = _StaticModel(contam_output)
        updater = MemoryUpdater(config, create_storage(config), llm=model)

        # Seed global memory
        if case.seed_facts:
            seed_mem = create_empty_memory()
            seed_mem["facts"] = [dict(f) for f in case.seed_facts]
            updater.import_memory_data(seed_mem, user_id=case.thread_a.user_id, agent_name=case.thread_a.agent_name)
            if case.thread_b.user_id != case.thread_a.user_id:
                updater.import_memory_data(seed_mem, user_id=case.thread_b.user_id, agent_name=case.thread_b.agent_name)

        # Assemble prompt for Thread A
        prompt_a, _ = _assemble_thread_prompt(
            updater,
            thread_id=case.thread_a.thread_id,
            user_id=case.thread_a.user_id,
            agent_name=case.thread_a.agent_name,
            project_context=case.thread_a.project_context,
            query_text="Thread A question",
        )

        # Assemble prompt for Thread B
        prompt_b, _ = _assemble_thread_prompt(
            updater,
            thread_id=case.thread_b.thread_id,
            user_id=case.thread_b.user_id,
            agent_name=case.thread_b.agent_name,
            project_context=case.thread_b.project_context,
            query_text="Thread B question",
        )

        crosstalk_leaks: list[str] = []

        # Contamination turn test in Thread A
        persisted_pollutions: list[str] = []
        if case.contamination_turn is not None:
            msg_data = case.contamination_turn.get("messages", [])
            messages = [
                HumanMessage(content=m["content"]) if m.get("role") == "user" else AIMessage(content=m["content"])
                for m in msg_data
            ]
            updater.update_memory(
                messages,
                thread_id=case.thread_a.thread_id,
                user_id=case.thread_a.user_id,
                agent_name=case.thread_a.agent_name,
                bypass_watermark=True,
            )
            mem_after_a = updater.get_memory_data(agent_name=case.thread_a.agent_name, user_id=case.thread_a.user_id)
            mem_after_b = updater.get_memory_data(agent_name=case.thread_b.agent_name, user_id=case.thread_b.user_id)
            persisted_pollutions = [
                canary
                for canary in case.expected_rejected_canaries
                if _storage_contains_canary(mem_after_a, canary) or _storage_contains_canary(mem_after_b, canary)
            ]
            # Verify Thread B prompt assembly after Thread A's contamination turn
            prompt_b_after, _ = _assemble_thread_prompt(
                updater,
                thread_id=case.thread_b.thread_id,
                user_id=case.thread_b.user_id,
                agent_name=case.thread_b.agent_name,
                project_context=case.thread_b.project_context,
                query_text="Thread B follow-up question",
            )
            for canary in case.expected_rejected_canaries:
                if canary in prompt_b_after:
                    crosstalk_leaks.append(f"leak_rejected_to_thread_b:{canary}")

        # Scan canaries
        present_a = [c for c in case.expected_thread_a_canaries if c in prompt_a]
        present_b = [c for c in case.expected_thread_b_canaries if c in prompt_b]

        # Crosstalk detection: thread A must not contain thread B specific canaries, and vice-versa
        th_b_specific = [c for c in case.expected_thread_b_canaries if c not in case.expected_thread_a_canaries]
        th_a_specific = [c for c in case.expected_thread_a_canaries if c not in case.expected_thread_b_canaries]

        for c in th_b_specific:
            if c in prompt_a:
                crosstalk_leaks.append(f"leak_b_to_a:{c}")
        for c in th_a_specific:
            if c in prompt_b:
                crosstalk_leaks.append(f"leak_a_to_b:{c}")

        case_dict = {
            "id": case.case_id,
            "thread_a": case.thread_a.__dict__,
            "thread_b": case.thread_b.__dict__,
            "expected_thread_a_canaries": case.expected_thread_a_canaries,
            "expected_thread_b_canaries": case.expected_thread_b_canaries,
            "expected_rejected_canaries": case.expected_rejected_canaries,
        }

        return _seal_row(
            {
                "schema_version": ROW_SCHEMA_VERSION,
                "suite": "scope_isolation",
                "row_id": case.case_id,
                "description": case.description,
                "request_fingerprint": _case_fingerprint("scope_isolation", case_dict, marker),
                "expected_thread_a_canaries": list(case.expected_thread_a_canaries),
                "expected_thread_b_canaries": list(case.expected_thread_b_canaries),
                "expected_rejected_canaries": list(case.expected_rejected_canaries),
                "thread_a_canaries_present": present_a,
                "thread_b_canaries_present": present_b,
                "crosstalk_canaries_leaked": crosstalk_leaks,
                "persisted_rejected_canaries": persisted_pollutions,
            }
        )


def _run_turn_invalidation_case(
    case: TurnInvalidationCase,
    marker: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="deerflow-bench-inv-") as td:
        storage_path = Path(td)
        config = _config(storage_path)
        model = _StaticModel(case.offline_output)
        updater = MemoryUpdater(config, create_storage(config), llm=model)

        # Seed turn 1
        if case.seed_facts:
            seed_mem = create_empty_memory()
            seed_mem["facts"] = [dict(f) for f in case.seed_facts]
            updater.import_memory_data(seed_mem, user_id=case.user_id, agent_name=case.agent_name)

        # Turn 1 prompt assembly
        prompt_t1, _ = _assemble_thread_prompt(
            updater,
            thread_id=f"thread-{case.case_id}-t1",
            user_id=case.user_id,
            agent_name=case.agent_name,
            project_context=None,
            query_text="Turn 1 prompt",
        )
        t1_present = [c for c in case.expected_turn_1_canaries if c in prompt_t1]

        # Execute Turn 1 memory update (e.g. deletion or atomic replacement)
        update_msgs = [
            HumanMessage(content=m["content"]) if m.get("role") == "user" else AIMessage(content=m["content"])
            for m in case.update_messages
        ]
        succeeded = updater.update_memory(
            update_msgs,
            thread_id=f"thread-{case.case_id}-t1",
            user_id=case.user_id,
            agent_name=case.agent_name,
            bypass_watermark=True,
        )
        if not succeeded:
            raise RuntimeError(f"memory update failed for turn invalidation case {case.case_id}")

        # Turn 2 prompt assembly (next turn)
        prompt_t2, _ = _assemble_thread_prompt(
            updater,
            thread_id=f"thread-{case.case_id}-t2",
            user_id=case.user_id,
            agent_name=case.agent_name,
            project_context=None,
            query_text="Turn 2 prompt",
        )

        stale_present = [c for c in case.expected_turn_2_absent_canaries if c in prompt_t2]
        fresh_present = [c for c in case.expected_turn_2_present_canaries if c in prompt_t2]

        case_dict = {
            "id": case.case_id,
            "user_id": case.user_id,
            "agent_name": case.agent_name,
            "seed_facts": case.seed_facts,
            "expected_turn_1_canaries": case.expected_turn_1_canaries,
            "expected_turn_2_present_canaries": case.expected_turn_2_present_canaries,
            "expected_turn_2_absent_canaries": case.expected_turn_2_absent_canaries,
        }

        return _seal_row(
            {
                "schema_version": ROW_SCHEMA_VERSION,
                "suite": "turn_invalidation",
                "row_id": case.case_id,
                "description": case.description,
                "request_fingerprint": _case_fingerprint("turn_invalidation", case_dict, marker),
                "expected_turn_1_canaries": list(case.expected_turn_1_canaries),
                "expected_turn_2_present_canaries": list(case.expected_turn_2_present_canaries),
                "expected_turn_2_absent_canaries": list(case.expected_turn_2_absent_canaries),
                "turn_1_canaries_present": t1_present,
                "turn_2_fresh_canaries_present": fresh_present,
                "turn_2_stale_canaries_present": stale_present,
            }
        )


def _run_token_overhead_case(
    case: TokenOverheadCase,
    marker: dict[str, Any],
) -> dict[str, Any]:
    # Measure user facts alone
    user_mem = create_empty_memory()
    user_mem["facts"] = [dict(f) for f in case.user_facts]
    user_text = format_memory_for_injection(user_mem, use_tiktoken=False)
    user_facts_tokens = _count_tokens(user_text, use_tiktoken=False) if user_text else 0

    # Measure agent facts alone
    agent_mem = create_empty_memory()
    agent_mem["facts"] = [dict(f) for f in case.agent_facts]
    agent_text = format_memory_for_injection(agent_mem, use_tiktoken=False)
    agent_facts_tokens = _count_tokens(agent_text, use_tiktoken=False) if agent_text else 0

    # Measure combined memory data
    all_mem = create_empty_memory()
    all_mem["facts"] = [dict(f) for f in (*case.user_facts, *case.agent_facts)]
    combined_mem_text = format_memory_for_injection(all_mem, use_tiktoken=False)
    memory_total_tokens = _count_tokens(combined_mem_text, use_tiktoken=False) if combined_mem_text else 0

    # Measure project context layers
    proj_inst_tokens = 0
    proj_shelf_tokens = 0
    proj_total_tokens = 0

    if case.project_context is not None:
        p_blk = render_project_block(case.project_context)
        if p_blk is not None:
            proj_inst_tokens = _count_tokens(p_blk, use_tiktoken=False)
        d_blk = render_documents_block(case.project_context, max_entries=10, max_bytes=4096)
        if d_blk is not None:
            proj_shelf_tokens = _count_tokens(d_blk, use_tiktoken=False)
        combined_proj = "\n".join(b for b in (p_blk, d_blk) if b)
        if combined_proj:
            proj_total_tokens = _count_tokens(combined_proj, use_tiktoken=False)

    total_context_tokens = memory_total_tokens + proj_total_tokens

    case_dict = {
        "id": case.case_id,
        "user_id": case.user_id,
        "agent_name": case.agent_name,
        "user_facts": case.user_facts,
        "agent_facts": case.agent_facts,
        "project_context": case.project_context,
    }

    return _seal_row(
        {
            "schema_version": ROW_SCHEMA_VERSION,
            "suite": "token_overhead",
            "row_id": case.case_id,
            "description": case.description,
            "request_fingerprint": _case_fingerprint("token_overhead", case_dict, marker),
            "token_breakdown": {
                "user_facts_tokens": user_facts_tokens,
                "agent_facts_tokens": agent_facts_tokens,
                "memory_total_tokens": memory_total_tokens,
                "project_instructions_tokens": proj_inst_tokens,
                "project_shelf_tokens": proj_shelf_tokens,
                "project_total_tokens": proj_total_tokens,
                "total_context_tokens": total_context_tokens,
            },
        }
    )


def run(
    protocol: Protocol,
    *,
    manifest_path: Path,
    output_dir: Path,
    mode: str = "offline",
) -> RunReport:
    if mode != "offline":
        raise ValueError("only offline mode is supported for context-memory comparison benchmark")

    marker = ensure_run_identity(output_dir, mode=mode, protocol=protocol, manifest_path=manifest_path)
    reused = 0
    executed = 0

    # 1. Run Scope Isolation Cases
    for case in protocol.scope_isolation_cases:
        path = _row_path(output_dir, "scope_isolation", case.case_id)
        case_dict = {
            "id": case.case_id,
            "thread_a": case.thread_a.__dict__,
            "thread_b": case.thread_b.__dict__,
            "expected_thread_a_canaries": case.expected_thread_a_canaries,
            "expected_thread_b_canaries": case.expected_thread_b_canaries,
            "expected_rejected_canaries": case.expected_rejected_canaries,
        }
        fp = _case_fingerprint("scope_isolation", case_dict, marker)
        if _load_reusable_row(path, fp) is not None:
            reused += 1
            continue
        _atomic_write_json(path, _run_scope_isolation_case(case, marker))
        executed += 1

    # 2. Run Turn Invalidation Cases
    for case in protocol.turn_invalidation_cases:
        path = _row_path(output_dir, "turn_invalidation", case.case_id)
        case_dict = {
            "id": case.case_id,
            "user_id": case.user_id,
            "agent_name": case.agent_name,
            "seed_facts": case.seed_facts,
            "expected_turn_1_canaries": case.expected_turn_1_canaries,
            "expected_turn_2_present_canaries": case.expected_turn_2_present_canaries,
            "expected_turn_2_absent_canaries": case.expected_turn_2_absent_canaries,
        }
        fp = _case_fingerprint("turn_invalidation", case_dict, marker)
        if _load_reusable_row(path, fp) is not None:
            reused += 1
            continue
        _atomic_write_json(path, _run_turn_invalidation_case(case, marker))
        executed += 1

    # 3. Run Token Overhead Cases
    for case in protocol.token_overhead_cases:
        path = _row_path(output_dir, "token_overhead", case.case_id)
        case_dict = {
            "id": case.case_id,
            "user_id": case.user_id,
            "agent_name": case.agent_name,
            "user_facts": case.user_facts,
            "agent_facts": case.agent_facts,
            "project_context": case.project_context,
        }
        fp = _case_fingerprint("token_overhead", case_dict, marker)
        if _load_reusable_row(path, fp) is not None:
            reused += 1
            continue
        _atomic_write_json(path, _run_token_overhead_case(case, marker))
        executed += 1

    return RunReport(reused=reused, executed=executed)
