"""SandboxAuditMiddleware - bash command security auditing."""

import json
import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Command classification rules
# ---------------------------------------------------------------------------

# Each pattern is compiled once at import time.
_HIGH_RISK_PATTERNS: list[re.Pattern[str]] = [
    # --- original rules (retained) ---
    re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|/home\b|/root\b)\s*$"),
    re.compile(r"dd\s+if="),
    re.compile(r"mkfs"),
    re.compile(r"cat\s+/etc/shadow"),
    re.compile(r">\s*/etc/"),
    # --- pipe to sh/bash (generalised, replaces old curl|sh rule) ---
    re.compile(r"\|\s*(ba)?sh\b"),
    # --- command substitution (targeted – only dangerous executables) ---
    re.compile(r"[`$]\(?\s*(curl|wget|bash|sh|python|ruby|perl|base64)"),
    # --- base64 decode piped to execution ---
    re.compile(r"base64\s+.*-d.*\|"),
    # --- overwrite system binaries ---
    re.compile(r">+\s*(/usr/bin/|/bin/|/sbin/)"),
    # --- overwrite shell startup files ---
    re.compile(r">+\s*~/?\.(bashrc|profile|zshrc|bash_profile)"),
    # --- process environment leakage ---
    re.compile(r"/proc/[^/]+/environ"),
    # --- dynamic linker hijack (one-step escalation) ---
    re.compile(r"\b(LD_PRELOAD|LD_LIBRARY_PATH)\s*="),
    # --- bash built-in networking (bypasses tool allowlists) ---
    re.compile(r"/dev/tcp/"),
    # --- fork bomb ---
    re.compile(r"\S+\(\)\s*\{[^}]*\|\s*\S+\s*&"),  # :(){ :|:& };:
    re.compile(r"while\s+true.*&\s*done"),  # while true; do bash & done
]

_MEDIUM_RISK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"chmod\s+777"),
    re.compile(r"pip3?\s+install"),
    re.compile(r"apt(-get)?\s+install"),
    # sudo/su: no-op under Docker root; warn so LLM is aware
    re.compile(r"\b(sudo|su)\b"),
    # PATH modification: long attack chain, warn rather than block
    re.compile(r"\bPATH\s*="),
]


def _split_compound_command(command: str) -> list[str]:
    """Split a compound command into sub-commands (quote-aware).

    Uses shlex to correctly handle quoted strings so that operators
    inside quotes (e.g. ``echo "a && b"``) are not treated as separators.
    Falls back to returning the whole command if shlex fails (fail-closed:
    the caller will classify the unsplit command, which is safer than
    silently dropping parts).
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [command]

    parts: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token in ("&&", "||", ";"):
            if current:
                parts.append(" ".join(current))
                current = []
        else:
            current.append(token)
    if current:
        parts.append(" ".join(current))
    return parts if parts else [command]


def _classify_single_command(command: str) -> str:
    """Classify a single (non-compound) command. Return 'block', 'warn', or 'pass'."""
    normalized = " ".join(command.split())

    for pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(normalized):
            return "block"

    # Also try shlex-parsed tokens for high-risk detection
    try:
        tokens = shlex.split(command)
        joined = " ".join(tokens)
        for pattern in _HIGH_RISK_PATTERNS:
            if pattern.search(joined):
                return "block"
    except ValueError:
        # shlex.split fails on unclosed quotes — treat as suspicious
        return "block"

    for pattern in _MEDIUM_RISK_PATTERNS:
        if pattern.search(normalized):
            return "warn"

    return "pass"


def _classify_command(command: str) -> str:
    """Return 'block', 'warn', or 'pass'.

    Splits compound commands (e.g. ``cmd1 && cmd2 ; cmd3``) and classifies
    each sub-command independently. The most severe verdict wins.
    """
    sub_commands = _split_compound_command(command)
    worst = "pass"
    for sub in sub_commands:
        verdict = _classify_single_command(sub)
        if verdict == "block":
            return "block"  # short-circuit: can't get worse
        if verdict == "warn":
            worst = "warn"
    return worst


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SandboxAuditMiddleware(AgentMiddleware[ThreadState]):
    """Bash command security auditing middleware.

    For every ``bash`` tool call:
    1. **Command classification**: regex + shlex analysis grades commands as
       high-risk (block), medium-risk (warn), or safe (pass).
    2. **Audit log**: every bash call is recorded as a structured JSON entry
       via the standard logger (visible in langgraph.log).

    High-risk commands (e.g. ``rm -rf /``, ``curl url | bash``) are blocked:
    the handler is not called and an error ``ToolMessage`` is returned so the
    agent loop can continue gracefully.

    Medium-risk commands (e.g. ``pip install``, ``chmod 777``) are executed
    normally; a warning is appended to the tool result so the LLM is aware.
    """

    state_schema = ThreadState

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_thread_id(self, request: ToolCallRequest) -> str | None:
        runtime = request.runtime  # ToolRuntime; may be None-like in tests
        if runtime is None:
            return None
        ctx = getattr(runtime, "context", None) or {}
        thread_id = ctx.get("thread_id") if isinstance(ctx, dict) else None
        if thread_id is None:
            cfg = getattr(runtime, "config", None) or {}
            thread_id = cfg.get("configurable", {}).get("thread_id")
        return thread_id

    def _write_audit(self, thread_id: str | None, command: str, verdict: str) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "thread_id": thread_id or "unknown",
            "command": command,
            "verdict": verdict,
        }
        logger.info("[SandboxAudit] %s", json.dumps(record, ensure_ascii=False))

    def _build_block_message(self, request: ToolCallRequest, reason: str) -> ToolMessage:
        tool_call_id = str(request.tool_call.get("id") or "missing_id")
        return ToolMessage(
            content=f"Command blocked: {reason}. Please use a safer alternative approach.",
            tool_call_id=tool_call_id,
            name="bash",
            status="error",
        )

    def _append_warn_to_result(self, result: ToolMessage | Command, command: str) -> ToolMessage | Command:
        """Append a warning note to the tool result for medium-risk commands."""
        if not isinstance(result, ToolMessage):
            return result
        warning = f"\n\n⚠️ Warning: `{command}` is a medium-risk command that may modify the runtime environment."
        if isinstance(result.content, list):
            new_content = list(result.content) + [{"type": "text", "text": warning}]
        else:
            new_content = str(result.content) + warning
        return ToolMessage(
            content=new_content,
            tool_call_id=result.tool_call_id,
            name=result.name,
            status=result.status,
        )

    # ------------------------------------------------------------------
    # Core logic (shared between sync and async paths)
    # ------------------------------------------------------------------

    def _pre_process(self, request: ToolCallRequest) -> tuple[str, str | None, str]:
        """
        Returns (command, thread_id, verdict).
        verdict is 'block', 'warn', or 'pass'.
        """
        args = request.tool_call.get("args", {})
        command: str = args.get("command", "")
        thread_id = self._get_thread_id(request)

        # ① classify command
        verdict = _classify_command(command)

        # ② audit log
        self._write_audit(thread_id, command, verdict)

        if verdict == "block":
            logger.warning("[SandboxAudit] BLOCKED thread=%s cmd=%r", thread_id, command)
        elif verdict == "warn":
            logger.warning("[SandboxAudit] WARN (medium-risk) thread=%s cmd=%r", thread_id, command)

        return command, thread_id, verdict

    # ------------------------------------------------------------------
    # wrap_tool_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "bash":
            return handler(request)

        command, _, verdict = self._pre_process(request)
        if verdict == "block":
            return self._build_block_message(request, "security violation detected")
        result = handler(request)
        if verdict == "warn":
            result = self._append_warn_to_result(result, command)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != "bash":
            return await handler(request)

        command, _, verdict = self._pre_process(request)
        if verdict == "block":
            return self._build_block_message(request, "security violation detected")
        result = await handler(request)
        if verdict == "warn":
            result = self._append_warn_to_result(result, command)
        return result
