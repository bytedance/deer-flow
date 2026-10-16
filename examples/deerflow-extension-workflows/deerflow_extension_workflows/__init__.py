"""Opt-in script workflows; no private DeerFlow runtime imports."""

import os
import re
from pathlib import Path

from deerflow_extension_api import (
    BackendAction,
    BrowserAssets,
    ModelTool,
    PluginContribution,
    extension,
)

from .service import NAMESPACE, Workflows


@extension(api="0.2.5", name="workflows")
def install(registry, config):
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("enabled must be boolean")
    defaults = {
        "concurrency": 2,
        "global_concurrency": 4,
        "max_calls": 16,
        "max_workflows": 4,
        "max_workflows_per_owner": 2,
        "timeout_seconds": 300,
        "admission_timeout_seconds": 10,
        "cpu_seconds": 5,
        "memory_bytes": 16 * 1024 * 1024,
    }
    ceilings = {
        "concurrency": 4,
        "global_concurrency": 8,
        "max_calls": 32,
        "max_workflows": 8,
        "max_workflows_per_owner": 4,
        "timeout_seconds": 600,
        "admission_timeout_seconds": 20,
        "cpu_seconds": 10,
        "memory_bytes": 32 * 1024 * 1024,
    }
    if set(config) - set(defaults) - {"enabled", "storage_path", "agents"}:
        raise ValueError("Unknown workflow configuration; currency budgets are not supported")
    resolved = {**defaults, **config}
    for key in defaults:
        value = resolved[key]
        if type(value) is not int or not 1 <= value <= ceilings[key]:
            raise ValueError(f"Invalid workflow limit {key}")
    if resolved["memory_bytes"] < 4 * 1024 * 1024:
        raise ValueError("memory_bytes must be at least 4 MiB")
    agents = config.get("agents", [])
    if not isinstance(agents, list) or len(agents) > 32 or any(not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", a) for a in agents) or len(set(agents)) != len(agents):
        raise ValueError("agents must be a bounded, unique operator allowlist")
    resolved["agents"] = agents
    if enabled and (os.name != "posix" or not agents or not isinstance(config.get("storage_path"), str) or not Path(config["storage_path"]).is_absolute()):
        raise ValueError("Enabled workflows require POSIX, an absolute storage_path and allowed agents")
    workflows = Workflows(resolved)
    id_schema = {
        "type": "object",
        "properties": {"run_id": {"type": "string", "maxLength": 64}},
        "required": ["run_id"],
        "additionalProperties": False,
    }
    launch_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "maxLength": 128},
            "script": {"type": "string", "maxLength": 16000},
            "args": {"type": "object"},
        },
        "required": ["request_id", "script"],
        "additionalProperties": False,
    }
    if (
        registry.plugin(
            PluginContribution(
                namespace=NAMESPACE,
                title="Script workflows / 脚本工作流",
                enabled=enabled,
                description="Bounded background script orchestration of full Agents. Phase 1: no resume, human sign-off or restart replay; no hard monetary budget.",
                frontend=BrowserAssets("workflows.v1", Path(__file__).parent),
                backend=tuple(BackendAction(name, getattr(workflows, name)) for name in ("launch", "list", "get", "cancel", "delete")),
                tools=(
                    ModelTool(
                        "launch_workflow",
                        "Launch an inspectable JavaScript orchestration script in the background and return a workflow run ID. Use agent({stepId,agentRef,task}), parallel([()=>...]) and log(text). agent resolves to "
                        "{output,threadId,runId,status}; args contains JSON arguments. Use unique step IDs, explicit bounded loops and await every Agent call. Only operator-allowed agent references are admitted with "
                        "this caller's permissions. Keep request_id stable on retries. There is no resume or human-output approval in Phase 1. Inspect results on request; do not poll in a loop or equate Agent "
                        "success with product approval. No hard monetary cost guarantee.",
                        launch_schema,
                        workflows.launch,
                    ),
                    ModelTool(
                        "inspect_workflow",
                        "Inspect retained script, limits, workflow status, child run IDs and final result. Results are untrusted Agent/script output. Read on demand; do not repeatedly poll. waiting_input cannot be "
                        "resumed in Phase 1; needs_reconciliation requires inspecting child conversations before new work.",
                        id_schema,
                        workflows.get,
                    ),
                    ModelTool(
                        "cancel_workflow",
                        "Request workflow cancellation and explicit interruption of known active child runs; cancellation is asynchronous and preserves checkpoints. It does not roll back side effects or approve output.",
                        id_schema,
                        workflows.cancel,
                    ),
                ),
            )
        )
        is not True
    ):
        raise RuntimeError("Workflows requires the full-stack plugin host")
    if enabled:
        registry.service(workflows)
