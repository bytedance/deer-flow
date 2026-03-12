#!/usr/bin/env bash
set -euo pipefail

# Detect whether the current branch has working tool-failure downgrade:
# - Lead agent middleware chain includes error-handling
# - Subagent middleware chain includes error-handling
# - Failing tool call does not abort the whole call sequence
# - Subsequent successful tool call result is still preserved

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "[FAIL] uv is required but not found in PATH."
  exit 1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

echo "[INFO] Root:    ${ROOT_DIR}"
echo "[INFO] Backend: ${BACKEND_DIR}"
echo "[INFO] UV cache: ${UV_CACHE_DIR}"
echo "[INFO] Running tool-failure downgrade detector..."

cd "${BACKEND_DIR}"

uv run python -u - <<'PY'
import asyncio
import logging
import ssl
from types import SimpleNamespace

from requests.exceptions import SSLError

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from src.agents.lead_agent.agent import _build_middlewares
from src.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
from src.config import get_app_config

HANDSHAKE_ERROR = "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)"
logging.getLogger("src.agents.middlewares.tool_error_handling_middleware").setLevel(logging.CRITICAL)


def _make_ssl_error():
    return SSLError(ssl.SSLEOFError(8, HANDSHAKE_ERROR))

print("[STEP 1] Prepare simulated Tavily SSL handshake failure.")
print(f"[INFO] Handshake error payload: {HANDSHAKE_ERROR}")

TOOL_CALLS = [
    {"name": "web_search", "id": "tc-fail", "args": {"query": "latest agent news"}},
    {"name": "web_fetch", "id": "tc-ok", "args": {"url": "https://example.com"}},
]


def _sync_handler(req):
    tool_name = req.tool_call.get("name", "unknown_tool")
    if tool_name == "web_search":
        raise _make_ssl_error()
    return ToolMessage(
        content=f"{tool_name} success",
        tool_call_id=req.tool_call.get("id", "missing-id"),
        name=tool_name,
        status="success",
    )


async def _async_handler(req):
    tool_name = req.tool_call.get("name", "unknown_tool")
    if tool_name == "web_search":
        raise _make_ssl_error()
    return ToolMessage(
        content=f"{tool_name} success",
        tool_call_id=req.tool_call.get("id", "missing-id"),
        name=tool_name,
        status="success",
    )


def _collect_sync_wrappers(middlewares):
    return [
        m.wrap_tool_call
        for m in middlewares
        if m.__class__.wrap_tool_call is not AgentMiddleware.wrap_tool_call
        or m.__class__.awrap_tool_call is not AgentMiddleware.awrap_tool_call
    ]


def _collect_async_wrappers(middlewares):
    return [
        m.awrap_tool_call
        for m in middlewares
        if m.__class__.awrap_tool_call is not AgentMiddleware.awrap_tool_call
        or m.__class__.wrap_tool_call is not AgentMiddleware.wrap_tool_call
    ]


def _compose_sync(wrappers):
    def execute(req):
        return _sync_handler(req)

    for wrapper in reversed(wrappers):
        previous = execute

        def execute(req, wrapper=wrapper, previous=previous):
            return wrapper(req, previous)

    return execute


def _compose_async(wrappers):
    async def execute(req):
        return await _async_handler(req)

    for wrapper in reversed(wrappers):
        previous = execute

        async def execute(req, wrapper=wrapper, previous=previous):
            return await wrapper(req, previous)

    return execute


def _validate_outputs(label, outputs):
    if len(outputs) != 2:
        print(f"[FAIL] {label}: expected 2 tool outputs, got {len(outputs)}")
        raise SystemExit(2)
    first, second = outputs
    if not isinstance(first, ToolMessage) or not isinstance(second, ToolMessage):
        print(f"[FAIL] {label}: outputs are not ToolMessage instances")
        raise SystemExit(3)
    if first.status != "error":
        print(f"[FAIL] {label}: first tool should be status=error, got {first.status}")
        raise SystemExit(4)
    if second.status != "success":
        print(f"[FAIL] {label}: second tool should be status=success, got {second.status}")
        raise SystemExit(5)
    if "Error: Tool 'web_search' failed" not in first.text:
        print(f"[FAIL] {label}: first tool error text missing")
        raise SystemExit(6)
    if "web_fetch success" not in second.text:
        print(f"[FAIL] {label}: second tool success text missing")
        raise SystemExit(7)
    print(f"[INFO] {label}: no crash, outputs preserved (error + success).")


def _assert_has_tool_error_mw(label, middlewares):
    names = [m.__class__.__name__ for m in middlewares]
    if "ToolErrorHandlingMiddleware" not in names:
        print(f"[FAIL] {label}: ToolErrorHandlingMiddleware not found. Chain={names}")
        raise SystemExit(8)
    print(f"[INFO] {label}: ToolErrorHandlingMiddleware detected.")


print("[STEP 2] Load current branch middleware chains.")
app_cfg = get_app_config()
model_name = app_cfg.models[0].name if app_cfg.models else None
if not model_name:
    print("[FAIL] No model configured; cannot evaluate lead middleware chain.")
    raise SystemExit(9)

lead_middlewares = _build_middlewares({"configurable": {}}, model_name=model_name)
sub_middlewares = build_subagent_runtime_middlewares()

_assert_has_tool_error_mw("lead", lead_middlewares)
_assert_has_tool_error_mw("subagent", sub_middlewares)

print("[STEP 3] Validate current branch behavior (should not crash).")
for label, middlewares in [("lead", lead_middlewares), ("subagent", sub_middlewares)]:
    sync_exec = _compose_sync(_collect_sync_wrappers(middlewares))
    sync_outputs = []
    for call in TOOL_CALLS:
        req = SimpleNamespace(tool_call=call)
        sync_outputs.append(sync_exec(req))
    _validate_outputs(f"{label}/sync", sync_outputs)

    async_exec = _compose_async(_collect_async_wrappers(middlewares))

    async def _run_async_sequence():
        outs = []
        for call in TOOL_CALLS:
            req = SimpleNamespace(tool_call=call)
            outs.append(await async_exec(req))
        return outs

    async_outputs = asyncio.run(_run_async_sequence())
    _validate_outputs(f"{label}/async", async_outputs)

print("[PASS] Current branch passes: tool exceptions are downgraded and do not abort conversation flow.")
PY
