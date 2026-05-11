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

from deerflow.agents.lead_agent.agent import _build_middlewares
from deerflow.config import get_app_config
from deerflow.sandbox.middleware import SandboxMiddleware

from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

HANDSHAKE_ERROR = "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)"
logging.getLogger("deerflow.agents.middlewares.tool_error_handling_middleware").setLevel(logging.CRITICAL)


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


def _build_sub_middlewares():
    try:
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    except Exception:
        return [
            ThreadDataMiddleware(lazy_init=True),
            SandboxMiddleware(lazy_init=True),
        ]
    return build_subagent_runtime_middlewares()


def _run_sync_sequence(executor):
    outputs = []
    try:
        for call in TOOL_CALLS:
            req = SimpleNamespace(tool_call=call)
            outputs.append(executor(req))
    except Exception as exc:
        return outputs, exc
    return outputs, None


async def _run_async_sequence(executor):
    outputs = []
    try:
        for call in TOOL_CALLS:
            req = SimpleNamespace(tool_call=call)
            outputs.append(await executor(req))
    except Exception as exc:
        return outputs, exc
    return outputs, None


print("[STEP 2] Load current branch middleware chains.")
app_cfg = get_app_config()
model_name = app_cfg.models[0].name if app_cfg.models else None
if not model_name:
    print("[FAIL] No model configured; cannot evaluate lead middleware chain.")
    raise SystemExit(8)

lead_middlewares = _build_middlewares({"configurable": {}}, model_name=model_name)
sub_middlewares = _build_sub_middlewares()

print("[STEP 3] Simulate two sequential tool calls and check whether conversation flow aborts.")
any_crash = False
for label, middlewares in [("lead", lead_middlewares), ("subagent", sub_middlewares)]:
    sync_exec = _compose_sync(_collect_sync_wrappers(middlewares))
    sync_outputs, sync_exc = _run_sync_sequence(sync_exec)
    if sync_exc is not None:
        any_crash = True
        print(f"[INFO] {label}/sync: conversation aborted after tool error ({sync_exc.__class__.__name__}: {sync_exc}).")
    else:
        _validate_outputs(f"{label}/sync", sync_outputs)

    async_exec = _compose_async(_collect_async_wrappers(middlewares))
    async_outputs, async_exc = asyncio.run(_run_async_sequence(async_exec))
    if async_exc is not None:
        any_crash = True
        print(f"[INFO] {label}/async: conversation aborted after tool error ({async_exc.__class__.__name__}: {async_exc}).")
    else:
        _validate_outputs(f"{label}/async", async_outputs)

if any_crash:
    print("[FAIL] Tool exception caused conversation flow to abort (no effective downgrade).")
    raise SystemExit(9)

print("[PASS] Tool exceptions were downgraded; conversation flow continued with remaining tool results.")
PY
