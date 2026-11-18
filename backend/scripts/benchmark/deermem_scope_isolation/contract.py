from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


@dataclass(frozen=True)
class SemanticCase:
    case_id: str
    category: str
    messages: tuple[dict[str, str], ...]
    offline_output: dict[str, Any]
    expected_persisted_canaries: tuple[str, ...]
    expected_rejected_canaries: tuple[str, ...]
    expected_removed_canaries: tuple[str, ...]
    seed_facts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    canary: str
    selected: dict[str, str]
    other_agent: dict[str, str]
    other_user: dict[str, str]


@dataclass(frozen=True)
class Protocol:
    schema_version: int
    protocol_id: str
    semantic_cases: tuple[SemanticCase, ...]
    routing_case: RoutingCase


def _scope(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"user_id", "agent_name"}:
        raise ValueError(f"{field} must contain user_id and agent_name")
    if not all(isinstance(item, str) and item for item in value.values()):
        raise ValueError(f"{field} values must be non-empty strings")
    if not AGENT_NAME_PATTERN.fullmatch(value["agent_name"]):
        raise ValueError(f"{field}.agent_name has an invalid public agent name")
    return dict(value)


def load_protocol(path: Path) -> Protocol:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("unsupported scope-isolation manifest schema")
    if set(raw) != {"schema_version", "protocol_id", "semantic_cases", "routing_case"}:
        raise ValueError("manifest has unsupported fields")
    protocol_id = raw.get("protocol_id")
    if not isinstance(protocol_id, str) or not protocol_id:
        raise ValueError("protocol_id must be a non-empty string")
    raw_cases = raw.get("semantic_cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("semantic_cases must be a non-empty list")
    cases: list[SemanticCase] = []
    seen_case_ids: set[str] = set()
    seen_canaries: set[str] = set()
    required = {
        "id",
        "category",
        "messages",
        "offline_output",
        "expected_persisted_canaries",
        "expected_rejected_canaries",
        "expected_removed_canaries",
        "seed_facts",
    }
    for value in raw_cases:
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("semantic case has unsupported fields")
        case_id = value["id"]
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id) or case_id in seen_case_ids:
            raise ValueError("semantic case IDs must be unique non-empty strings")
        seen_case_ids.add(case_id)
        category = value["category"]
        if not isinstance(category, str) or not category:
            raise ValueError(f"case {case_id} category must be a non-empty string")
        messages = value["messages"]
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"case {case_id} must have messages")
        if any(not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in {"user", "assistant"} or not isinstance(message["content"], str) for message in messages):
            raise ValueError(f"case {case_id} has invalid messages")
        output = value["offline_output"]
        if not isinstance(output, dict) or not {"user", "history", "newFacts"}.issubset(output):
            raise ValueError(f"case {case_id} has an invalid offline output")
        persisted = value["expected_persisted_canaries"]
        rejected = value["expected_rejected_canaries"]
        removed = value["expected_removed_canaries"]
        if not all(isinstance(items, list) and all(isinstance(item, str) and item for item in items) for items in (persisted, rejected, removed)):
            raise ValueError(f"case {case_id} has invalid canary lists")
        if set(persisted) & set(rejected) or set(persisted) & set(removed) or set(rejected) & set(removed):
            raise ValueError(f"case {case_id} expects the same canary in multiple outcomes")
        if not persisted and not rejected and not removed:
            raise ValueError(f"case {case_id} must define at least one expected canary outcome")
        conversation_text = json.dumps(messages, ensure_ascii=False)
        output_text = json.dumps(output, ensure_ascii=False)
        seed_text = json.dumps(value["seed_facts"], ensure_ascii=False)
        for canary in [*persisted, *rejected]:
            if canary not in conversation_text or canary not in output_text:
                raise ValueError(f"case {case_id} canary {canary!r} must appear in its conversation and offline output")
        for canary in removed:
            if canary not in seed_text:
                raise ValueError(f"case {case_id} removed canary {canary!r} must appear in its seed facts")
        for canary in [*persisted, *rejected, *removed]:
            if canary in seen_canaries:
                raise ValueError(f"canary {canary!r} is reused")
            seen_canaries.add(canary)
        seed_facts = value["seed_facts"]
        if not isinstance(seed_facts, list) or any(not isinstance(fact, dict) for fact in seed_facts):
            raise ValueError(f"case {case_id} has invalid seed facts")
        cases.append(
            SemanticCase(
                case_id=case_id,
                category=category,
                messages=tuple(dict(message) for message in messages),
                offline_output=dict(output),
                expected_persisted_canaries=tuple(persisted),
                expected_rejected_canaries=tuple(rejected),
                expected_removed_canaries=tuple(removed),
                seed_facts=tuple(dict(fact) for fact in seed_facts),
            )
        )
    raw_routing = raw.get("routing_case")
    if not isinstance(raw_routing, dict) or set(raw_routing) != {"id", "canary", "selected", "other_agent", "other_user"}:
        raise ValueError("routing_case has unsupported fields")
    canary = raw_routing["canary"]
    if not isinstance(canary, str) or not canary or canary in seen_canaries:
        raise ValueError("routing canary must be unique and non-empty")
    routing_id = raw_routing["id"]
    if not isinstance(routing_id, str) or not CASE_ID_PATTERN.fullmatch(routing_id) or routing_id in seen_case_ids:
        raise ValueError("routing case ID must be unique and path-safe")
    routing = RoutingCase(
        case_id=routing_id,
        canary=canary,
        selected=_scope(raw_routing["selected"], "routing_case.selected"),
        other_agent=_scope(raw_routing["other_agent"], "routing_case.other_agent"),
        other_user=_scope(raw_routing["other_user"], "routing_case.other_user"),
    )
    if routing.other_agent["user_id"] != routing.selected["user_id"] or routing.other_agent["agent_name"] == routing.selected["agent_name"]:
        raise ValueError("other_agent must change only the agent identity")
    if routing.other_user["user_id"] == routing.selected["user_id"] or routing.other_user["agent_name"] != routing.selected["agent_name"]:
        raise ValueError("other_user must change only the user identity")
    return Protocol(schema_version=1, protocol_id=protocol_id, semantic_cases=tuple(cases), routing_case=routing)
