"""Deterministic boundaries around model-assisted approval decisions."""

from __future__ import annotations

import hashlib
import json
import marshal
import sys
from types import CodeType
from typing import Any

from deerflow.config.hitl_approval_config import HitlApprovalConfig


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def resolve_mode(policy: HitlApprovalConfig, context: dict) -> str:
    mode = context.get("tool_approval_mode", policy.default_mode)
    if mode not in policy.allowed_modes:
        raise ValueError("Tool approval mode is not allowed by the deployment policy")
    return mode


def effective_outcome(verdict: dict) -> str:
    """A bare model 'allow' never substitutes for risk and authorization evidence."""
    if verdict.get("risk") == "critical" or verdict.get("outcome") == "deny":
        return "deny"
    if verdict.get("outcome") == "allow" and verdict.get("risk") in ("low", "medium") and verdict.get("authorization") in ("explicit", "implied"):
        return "allow"
    return "ask"


def tool_descriptor(tool: Any) -> dict:
    from deerflow.tools.tool_provenance import tool_provenance_context

    schema = tool.tool_call_schema
    schema = schema if isinstance(schema, dict) else schema.model_json_schema()
    function = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    code = getattr(function, "__code__", None)
    return {
        "name": tool.name,
        "source": tool_provenance_context(tool),
        "implementation": f"{getattr(function, '__module__', '')}:{getattr(function, '__qualname__', type(tool).__qualname__)}",
        "implementation_digest": hashlib.sha256(marshal.dumps(code)).hexdigest() if isinstance(code, CodeType) else None,
        "schema": schema,
        "binding": (getattr(tool, "metadata", None) or {}).get("deerflow_approval_binding"),
    }


def action_fingerprint(descriptor: dict, arguments: dict, policy_digest: str) -> str:
    return digest({"tool": descriptor, "arguments": arguments, "policy": policy_digest})


def is_routine_tool(descriptor: dict, tool: Any) -> bool:
    """Only concrete host implementations qualify; remote read-only hints do not."""
    if descriptor["source"].get("mcp_server") or descriptor["source"].get("namespace"):
        return False
    implementation = descriptor["implementation"]
    trusted = {
        "deerflow.sandbox.tools:ls_tool",
        "deerflow.sandbox.tools:glob_tool",
        "deerflow.sandbox.tools:grep_tool",
        "deerflow.sandbox.tools:read_file_tool",
        "deerflow.tools.builtins.clarification_tool:ask_clarification_tool",
        "deerflow.tools.builtins.task_tool:task_tool",
        "deerflow.tools.builtins.view_image_tool:_view_image",
        "deerflow.tools.builtins.present_file_tool:present_file_tool",
    }
    function = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    if implementation in trusted:
        module_name, symbol = implementation.split(":")
        # The defining module is already loaded when its tool is bound. Compare
        # the actual callable, never a claimed name/module/provenance label.
        original = getattr(sys.modules.get(module_name), symbol, None)
        original = getattr(original, "func", None) or original
        return original is not None and function is original
    if implementation == "deerflow.tools.builtins.tool_search:build_tool_search_tool.<locals>.tool_search":
        builder = getattr(sys.modules.get("deerflow.tools.builtins.tool_search"), "build_tool_search_tool", None)
        code = getattr(builder, "__code__", None)
        return code is not None and any(isinstance(inner, CodeType) and inner is getattr(function, "__code__", None) for inner in code.co_consts)
    return False


def permits_thread_grant(descriptor: dict) -> bool:
    # A logical MCP server name alone cannot bind a grant to a connection.
    return not descriptor["source"].get("mcp_server") or isinstance(descriptor.get("binding"), str)
