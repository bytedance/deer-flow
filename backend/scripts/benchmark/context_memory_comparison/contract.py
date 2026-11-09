from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class ThreadConfig:
    thread_id: str
    user_id: str
    agent_name: str
    project_context: dict[str, Any] | None


@dataclass(frozen=True)
class ScopeIsolationCase:
    case_id: str
    description: str
    thread_a: ThreadConfig
    thread_b: ThreadConfig
    seed_facts: tuple[dict[str, Any], ...]
    contamination_turn: dict[str, Any] | None
    expected_thread_a_canaries: tuple[str, ...]
    expected_thread_b_canaries: tuple[str, ...]
    expected_rejected_canaries: tuple[str, ...]


@dataclass(frozen=True)
class TurnInvalidationCase:
    case_id: str
    description: str
    user_id: str
    agent_name: str
    seed_facts: tuple[dict[str, Any], ...]
    expected_turn_1_canaries: tuple[str, ...]
    update_messages: tuple[dict[str, str], ...]
    offline_output: dict[str, Any]
    expected_turn_2_present_canaries: tuple[str, ...]
    expected_turn_2_absent_canaries: tuple[str, ...]


@dataclass(frozen=True)
class TokenOverheadCase:
    case_id: str
    description: str
    user_id: str
    agent_name: str
    user_facts: tuple[dict[str, Any], ...]
    agent_facts: tuple[dict[str, Any], ...]
    project_context: dict[str, Any] | None


@dataclass(frozen=True)
class Protocol:
    schema_version: int
    protocol_id: str
    scope_isolation_cases: tuple[ScopeIsolationCase, ...]
    turn_invalidation_cases: tuple[TurnInvalidationCase, ...]
    token_overhead_cases: tuple[TokenOverheadCase, ...]


def _parse_thread_config(raw: Any, field_name: str) -> ThreadConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} must be a dict")
    for key in ("thread_id", "user_id", "agent_name"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ValueError(f"{field_name}.{key} must be a non-empty string")
    proj = raw.get("project_context")
    if proj is not None and not isinstance(proj, dict):
        raise ValueError(f"{field_name}.project_context must be a dict or null")
    return ThreadConfig(
        thread_id=raw["thread_id"],
        user_id=raw["user_id"],
        agent_name=raw["agent_name"],
        project_context=dict(proj) if proj is not None else None,
    )


def load_protocol(path: Path) -> Protocol:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema version; expected 1")
    expected_fields = {
        "schema_version",
        "protocol_id",
        "scope_isolation_cases",
        "turn_invalidation_cases",
        "token_overhead_cases",
    }
    if set(raw) != expected_fields:
        raise ValueError(f"manifest has unexpected fields: {set(raw) ^ expected_fields}")

    protocol_id = raw.get("protocol_id")
    if not isinstance(protocol_id, str) or not protocol_id:
        raise ValueError("protocol_id must be a non-empty string")

    seen_case_ids: set[str] = set()
    seen_canaries: set[str] = set()

    def _check_case_id(cid: str) -> None:
        if not isinstance(cid, str) or not CASE_ID_PATTERN.fullmatch(cid) or cid in seen_case_ids:
            raise ValueError(f"invalid or duplicate case id: {cid!r}")
        seen_case_ids.add(cid)

    def _check_canary(canary: str, context: str) -> None:
        if not isinstance(canary, str) or not canary:
            raise ValueError(f"canary in {context} must be a non-empty string")
        if canary in seen_canaries:
            raise ValueError(f"canary {canary!r} in {context} is reused across cases")
        seen_canaries.add(canary)

    # 1. Parse scope_isolation_cases
    raw_iso = raw.get("scope_isolation_cases")
    if not isinstance(raw_iso, list) or not raw_iso:
        raise ValueError("scope_isolation_cases must be a non-empty list")
    scope_isolation_cases: list[ScopeIsolationCase] = []
    for item in raw_iso:
        _check_case_id(item.get("id"))
        th_a = _parse_thread_config(item.get("thread_a"), f"case {item['id']}.thread_a")
        th_b = _parse_thread_config(item.get("thread_b"), f"case {item['id']}.thread_b")
        seed_facts = item.get("seed_facts", [])
        if not isinstance(seed_facts, list):
            raise ValueError(f"case {item['id']}.seed_facts must be a list")

        contam = item.get("contamination_turn")
        if contam is not None and not isinstance(contam, dict):
            raise ValueError(f"case {item['id']}.contamination_turn must be a dict or null")

        exp_a = item.get("expected_thread_a_canaries", [])
        exp_b = item.get("expected_thread_b_canaries", [])
        exp_rej = item.get("expected_rejected_canaries", [])

        case_canaries = set(exp_a) | set(exp_b) | set(exp_rej)
        for c in case_canaries:
            _check_canary(c, f"scope_isolation_case {item['id']}")

        scope_isolation_cases.append(
            ScopeIsolationCase(
                case_id=item["id"],
                description=str(item.get("description", "")),
                thread_a=th_a,
                thread_b=th_b,
                seed_facts=tuple(dict(f) for f in seed_facts),
                contamination_turn=dict(contam) if contam is not None else None,
                expected_thread_a_canaries=tuple(exp_a),
                expected_thread_b_canaries=tuple(exp_b),
                expected_rejected_canaries=tuple(exp_rej),
            )
        )

    # 2. Parse turn_invalidation_cases
    raw_inv = raw.get("turn_invalidation_cases")
    if not isinstance(raw_inv, list) or not raw_inv:
        raise ValueError("turn_invalidation_cases must be a non-empty list")
    turn_invalidation_cases: list[TurnInvalidationCase] = []
    for item in raw_inv:
        _check_case_id(item.get("id"))
        for k in ("user_id", "agent_name"):
            if not isinstance(item.get(k), str) or not item[k]:
                raise ValueError(f"case {item['id']}.{k} must be a non-empty string")
        seed_facts = item.get("seed_facts", [])
        exp_t1 = item.get("expected_turn_1_canaries", [])
        exp_t2_pres = item.get("expected_turn_2_present_canaries", [])
        exp_t2_abs = item.get("expected_turn_2_absent_canaries", [])

        case_canaries = set(exp_t1) | set(exp_t2_pres) | set(exp_t2_abs)
        for c in case_canaries:
            _check_canary(c, f"turn_invalidation_case {item['id']}")

        msgs = item.get("update_messages", [])
        if not isinstance(msgs, list) or not msgs:
            raise ValueError(f"case {item['id']} must have update_messages")
        offline_output = item.get("offline_output", {})
        if not isinstance(offline_output, dict):
            raise ValueError(f"case {item['id']} has invalid offline_output")

        turn_invalidation_cases.append(
            TurnInvalidationCase(
                case_id=item["id"],
                description=str(item.get("description", "")),
                user_id=item["user_id"],
                agent_name=item["agent_name"],
                seed_facts=tuple(dict(f) for f in seed_facts),
                expected_turn_1_canaries=tuple(exp_t1),
                update_messages=tuple(dict(m) for m in msgs),
                offline_output=dict(offline_output),
                expected_turn_2_present_canaries=tuple(exp_t2_pres),
                expected_turn_2_absent_canaries=tuple(exp_t2_abs),
            )
        )

    # 3. Parse token_overhead_cases
    raw_tok = raw.get("token_overhead_cases")
    if not isinstance(raw_tok, list) or not raw_tok:
        raise ValueError("token_overhead_cases must be a non-empty list")
    token_overhead_cases: list[TokenOverheadCase] = []
    for item in raw_tok:
        _check_case_id(item.get("id"))
        for k in ("user_id", "agent_name"):
            if not isinstance(item.get(k), str) or not item[k]:
                raise ValueError(f"case {item['id']}.{k} must be a non-empty string")
        user_facts = item.get("user_facts", [])
        agent_facts = item.get("agent_facts", [])
        proj = item.get("project_context")
        token_overhead_cases.append(
            TokenOverheadCase(
                case_id=item["id"],
                description=str(item.get("description", "")),
                user_id=item["user_id"],
                agent_name=item["agent_name"],
                user_facts=tuple(dict(f) for f in user_facts),
                agent_facts=tuple(dict(f) for f in agent_facts),
                project_context=dict(proj) if proj is not None else None,
            )
        )

    return Protocol(
        schema_version=1,
        protocol_id=protocol_id,
        scope_isolation_cases=tuple(scope_isolation_cases),
        turn_invalidation_cases=tuple(turn_invalidation_cases),
        token_overhead_cases=tuple(token_overhead_cases),
    )
