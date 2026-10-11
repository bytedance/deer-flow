"""Offline protocol checks, independently graded artifacts and spend accounting."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from app.gateway.routers.console import _ModelPricing, _run_cost
from deerflow.config.database_config import DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY

ROOT = Path(__file__).resolve().parent
PROTOCOL = "scheduled-tasks-synthetic-v1"


def load_fixtures() -> dict[str, Any]:
    value = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    if value.get("protocol") != PROTOCOL or value.get("synthetic") is not True:
        raise ValueError("Only the committed, identified synthetic fixture is supported")
    return value


def fixture(case_id: str) -> dict[str, Any]:
    for case in load_fixtures()["cases"]:
        if case["id"] == case_id:
            return case
    raise ValueError("Unknown synthetic fixture case ID")


def task_prompt(case_id: str, filename: str) -> str:
    case = fixture(case_id)
    return (
        f"This is an operator-authorized synthetic benchmark. Read read_scheduled_fixture(case_id='{case_id}'). "
        f"{case['instruction']} Use write_file to create /mnt/user-data/outputs/{filename}, "
        "then present_files so the user can open it. Do not use external network sources or subagents. "
        "Report the computed values in your final answer."
    )


def grade_artifact(text: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Grade the opened file independently of agent/evaluator self-reports."""
    try:
        observed = json.loads(text)
    except (ValueError, TypeError):
        return {"passed": False, "reason": "artifact_not_json"}
    passed = isinstance(observed, dict) and all(key in observed and observed[key] == value and type(observed[key]) is type(value) for key, value in expected.items())
    return {"passed": passed, "reason": "expected_fields_match" if passed else "artifact_values_wrong", "artifact_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def require_loopback(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Use a disposable Gateway's explicit loopback HTTP origin")
    return base_url.rstrip("/")


def load_pilot_config(path: Path, model_alias: str) -> dict[str, Any]:
    """Inspect named fields only; secrets never enter the returned provenance."""
    raw_bytes = path.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    models = raw.get("models") or []
    if not models or models[0].get("name") != model_alias:
        raise ValueError("The pilot model must be the Gateway's configured default model")
    model = models[0]
    if not isinstance(model.get("model"), str) or not model["model"]:
        raise ValueError("The configured provider model ID is required")
    pricing = model.get("pricing") or {}
    if pricing.get("currency") != "USD":
        raise ValueError("Explicit USD pricing is required for the pilot spend guard")
    for field in ("input_per_million", "output_per_million"):
        if not isinstance(pricing.get(field), (int, float)) or not math.isfinite(pricing[field]) or pricing[field] < 0:
            raise ValueError("Explicit finite input/output model prices are required")
    if not raw.get("scheduler", {}).get("enabled") or not raw["scheduler"].get("tool_enabled"):
        raise ValueError("Both scheduler flags must be enabled in the disposable Gateway")
    if raw.get("database", {}).get("backend") != "sqlite":
        raise ValueError("The pilot requires the disposable Gateway's local SQLite database")
    budget = raw.get("token_budget") or {}
    if not budget.get("enabled") or not isinstance(budget.get("max_tokens"), int):
        raise ValueError("An explicit enabled per-run token budget is required")
    if model.get("max_retries") != 0:
        raise ValueError("Set the pilot provider model's max_retries to zero")
    tools = {entry.get("use") for entry in raw.get("tools", [])}
    required = {"scripts.benchmark.scheduled_tasks.fixture_tools:read_scheduled_fixture", "deerflow.sandbox.tools:write_file_tool"}
    if not required <= tools:
        raise ValueError("Configure the synthetic fixture reader and production write_file")
    if raw.get("channels", {}).get("enabled"):
        raise ValueError("Disable IM channels for the disposable pilot")
    if raw.get("plugins") or (raw.get("extensions") or {}).get("middlewares"):
        raise ValueError("The native budget reader is scoped to the default lead schema without plugin/custom middleware")
    return {
        "protocol": PROTOCOL,
        "config_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "fixture_sha256": hashlib.sha256((ROOT / "fixtures.json").read_bytes()).hexdigest(),
        "model_alias": model_alias,
        "provider_model": model["model"],
        "temperature": model.get("temperature"),
        "model_max_tokens": model.get("max_tokens"),
        "max_retries": model["max_retries"],
        "thinking_type": ((model.get("extra_body") or {}).get("thinking") or {}).get("type"),
        "request_timeout_seconds": model.get("timeout", model.get("request_timeout")),
        "recursion_limit": raw.get("recursion_limit"),
        "case_order": ["inventory", "corrected-ledger", "missing-reviewer"],
        "provider_seed": None,
        "token_budget": budget,
        "normal_pilot_budget_reference": 60000,
        "completion_rule": "correct_artifact_source_host_delivery_successful_run",
        "checkpoint_channel_mode": raw["database"].get("checkpoint_channel_mode", "full"),
        "checkpoint_snapshot_frequency": (raw["database"].get("checkpoint_delta") or {}).get("snapshot_frequency", DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY),
        "pricing": {field: pricing[field] for field in ("currency", "input_per_million", "output_per_million")},
        "sqlite_dir": raw["database"]["sqlite_dir"],
        "scheduler_min_delay": raw["scheduler"].get("min_once_delay_seconds", 60),
        "conversation_reader_enabled": "deerflow.tools.conversation:read_conversation" in tools,
    }


def run_cost(row: dict[str, Any], plan: dict[str, Any]) -> float | None:
    accepted = {plan["model_alias"], plan["provider_model"]}
    if row.get("model_name") and row["model_name"] not in accepted:
        raise ValueError("Run used an unexpected model; stop the pilot")
    usage = row.get("token_usage_by_model") or {}
    if set(usage) - accepted:
        raise ValueError("Unpriced or unexpected model bucket; stop the pilot")
    prices = plan["pricing"]
    price = _ModelPricing(input_per_million=prices["input_per_million"], output_per_million=prices["output_per_million"], currency="USD")
    return _run_cost(
        {model: price for model in accepted}, model_name=row.get("model_name") or plan["model_alias"], total_input_tokens=row.get("total_input_tokens"), total_output_tokens=row.get("total_output_tokens"), token_usage_by_model=usage
    )


def require_spend_reserve(spent: float, reserve: float, ceiling: float) -> None:
    if not all(math.isfinite(value) and value >= 0 for value in (spent, reserve, ceiling)) or reserve == 0 or not 0 < ceiling <= 1:
        raise ValueError("Use finite positive per-run reserve and a pilot ceiling no greater than USD 1")
    if spent + reserve > ceiling:
        raise ValueError("Pilot spend guard refuses another paid run")


def assert_arm_installed(arm: str, row: dict[str, Any]) -> None:
    if arm == "goal":
        if not row.get("scheduled_goal_metadata_present") or not row.get("scheduled_goal_objective") or not isinstance(row.get("goal_verdict"), dict):
            raise AssertionError("The goal arm lacks its installed goal metadata or durable verdict; the comparison is invalid")
    elif row.get("scheduled_goal_metadata_present") or row.get("goal_verdict") is not None:
        raise AssertionError("The plain arm unexpectedly carried a goal; the comparison is invalid")


def comparison_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {}
    for arm in ("plain", "goal"):
        selected = [result for result in results if result.get("arm") == arm and "run" in result]
        if selected:
            arms[arm] = {
                "occurrences": len(selected),
                "independent_passes": sum(bool(result.get("independent_pass")) for result in selected),
                "completion_rate": sum(bool(result.get("independent_pass")) for result in selected) / len(selected),
                "mean_lead_model_turns": sum(result["evidence"]["lead_model_turns"] for result in selected) / len(selected),
                "mean_llm_calls": sum(result["run"]["llm_call_count"] for result in selected) / len(selected),
                "total_tokens": sum(result["run"]["total_tokens"] for result in selected),
                "estimated_cost_usd": None if any(result.get("estimated_cost_usd") is None for result in selected) else sum(result["estimated_cost_usd"] for result in selected),
            }
    return {"arms": arms, "interpretation": "Small synthetic pilot; descriptive evidence only, without statistical or general completion-rate claims"}


def goal_history_evidence(entries: list[dict[str, Any]], objective: str) -> dict[str, Any]:
    snapshots = [(entry.get("values") or {}).get("goal") for entry in entries]
    goals = [goal for goal in snapshots if isinstance(goal, dict) and goal.get("objective") == objective]
    return {
        "goal_snapshots_observed": len(goals),
        "maximum_observed_continuation_count": max((goal["continuation_count"] for goal in goals), default=None),
        "continuation_limits_observed": sorted({goal["max_continuations"] for goal in goals}),
        "within_observed_limits": bool(goals) and all(goal["continuation_count"] <= goal["max_continuations"] for goal in goals),
    }


def host_delivery_evidence(events: list[dict[str, Any]], filepath: str) -> dict[str, Any]:
    from deerflow.runtime.runs.worker import _presented_path_covers_output

    receipts = [event["content"] for event in events if event.get("event_type") == "run.delivery" and isinstance(event.get("content"), dict)]
    delivered = any(receipt.get("satisfied") is True and any(isinstance(path, str) and _presented_path_covers_output(path, filepath) for path in (receipt.get("by_tool") or {}).get("present_files", [])) for receipt in receipts)
    return {"delivered": delivered, "host_delivery_receipts": receipts}


def independent_completion(*, artifact_passed: bool, fixture_read: bool, delivered: bool, run_status: str, stop_reason: str | None) -> bool:
    # A cap is a separate process observation; it does not erase a verified
    # artifact that was already delivered successfully.
    return bool(artifact_passed and fixture_read and delivered and run_status == "success")
