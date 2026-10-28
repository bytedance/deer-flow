"""HarnessGuard tool-loop interceptor middleware.

Implements Route C / RFC-003:
1. Write-Verify Gate: Pre-execution syntax validation on .py (ast.parse) and .json writes
   for write_file (non-append) and str_replace (spliced verification).
2. Error Signature Classifier: Detects classic failure patterns and injects actionable Targeted Hints.
3. Anti-Doom-Loop: Detects consecutive identical error signatures and A -> B -> A -> B alternating failure loops,
   scoped cleanly by (thread_id, run_id) with bounded LRU tracking.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import threading
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_result
from deerflow.config.harness_guard_config import HarnessGuardConfig
from deerflow.sandbox.tools import read_current_file_content

logger = logging.getLogger(__name__)

HARNESS_GUARD_KEY = "deerflow_harness_guard"
_WRITE_TOOLS = frozenset({"write_file", "str_replace"})

type _ScopeKey = tuple[str, str | None]


@dataclass(frozen=True)
class ErrorSignature:
    """Classified error pattern with actionable remediation hint."""

    category: str
    entity: str
    signature: str
    targeted_hint: str


def classify_tool_error(content: str) -> ErrorSignature | None:
    """Analyze tool output content for classic failure patterns and produce targeted hints."""
    if not content or not isinstance(content, str):
        return None

    # 1. ModuleNotFoundError / ImportError
    match_import_from = re.search(
        r"ImportError:\s+cannot import name\s+['\"][^'\"]+['\"]\s+from\s+['\"]([^'\"]+)['\"]",
        content,
    )
    if match_import_from:
        pkg = match_import_from.group(1).split(".")[0]
        return ErrorSignature(
            category="MODULE_NOT_FOUND",
            entity=pkg,
            signature=f"MODULE_NOT_FOUND:{pkg}",
            targeted_hint=(f"[HARNESS GUARD] Missing Python dependency or symbol '{pkg}'. Action: Execute 'pip install {pkg}' or check your package version/virtualenv."),
        )

    match = re.search(
        r"(?:ModuleNotFoundError|ImportError):\s+(?:No module named)\s+['\"]([^'\"]+)['\"]",
        content,
    )
    if match:
        pkg = match.group(1).split(".")[0]
        return ErrorSignature(
            category="MODULE_NOT_FOUND",
            entity=pkg,
            signature=f"MODULE_NOT_FOUND:{pkg}",
            targeted_hint=(f"[HARNESS GUARD] Missing Python dependency '{pkg}'. Action: Execute 'pip install {pkg}' or verify your virtual environment before re-running the script."),
        )

    # 2. Command not found
    match = re.search(
        r"(?:/bin/sh:\s+|bash:\s+)?(\b[\w\-.]+\b):\s+command not found|"
        r"['\"]?(\b[\w\-.]+\b)['\"]?\s+(?:is not recognized as an internal or external command|不是内部或外部命令)",
        content,
    )
    if match:
        cmd = match.group(1) or match.group(2)
        return ErrorSignature(
            category="COMMAND_NOT_FOUND",
            entity=cmd,
            signature=f"COMMAND_NOT_FOUND:{cmd}",
            targeted_hint=(f"[HARNESS GUARD] Command '{cmd}' was not found in environment. Action: Check command spelling or install the required executable before retrying."),
        )

    # 3. FileNotFoundError / No such file
    match = re.search(
        r"(?:FileNotFoundError:\s+\[Errno 2\]\s+No such file or directory:\s+['\"]([^'\"]+)['\"]|"
        r"(?:cat|ls|head|tail):\s+['\"]?([^:'\"]+)['\"]?:\s+No such file or directory)",
        content,
    )
    if match:
        path = match.group(1) or match.group(2)
        return ErrorSignature(
            category="FILE_NOT_FOUND",
            entity=path,
            signature=f"FILE_NOT_FOUND:{path}",
            targeted_hint=(f"[HARNESS GUARD] File '{path}' does not exist. Action: Run 'ls' or check directory layout to confirm file paths before retrying."),
        )

    # 4. SyntaxError in execution output
    if "SyntaxError:" in content:
        line_match = re.search(r"line\s+(\d+)", content)
        line = line_match.group(1) if line_match else "?"
        msg_match = re.search(r"SyntaxError:\s*([^\n\r]+)", content)
        msg = msg_match.group(1).strip() if msg_match else "invalid syntax"
        return ErrorSignature(
            category="SYNTAX_ERROR",
            entity=line,
            signature=f"SYNTAX_ERROR:line_{line}",
            targeted_hint=(f"[HARNESS GUARD] Python SyntaxError detected at line {line}: '{msg}'. Action: Correct the script syntax before executing again."),
        )

    # 5. PermissionError
    match = re.search(
        r"(?:PermissionError:\s+\[Errno 13\]\s+Permission denied:\s+['\"]([^'\"]+)['\"]|"
        r"bash:\s+([^:]+):\s+Permission denied)",
        content,
    )
    if match:
        path = match.group(1) or match.group(2)
        return ErrorSignature(
            category="PERMISSION_DENIED",
            entity=path,
            signature=f"PERMISSION_DENIED:{path}",
            targeted_hint=(f"[HARNESS GUARD] Permission denied on '{path}'. Action: Check file permissions (e.g. chmod +x) or user privileges."),
        )

    # 6. Address / Port already in use
    if re.search(r"(?:Address already in use|port\s+\d+\s+already in use|Errno 98)", content):
        return ErrorSignature(
            category="PORT_IN_USE",
            entity="port",
            signature="PORT_IN_USE",
            targeted_hint=("[HARNESS GUARD] Network port is already in use. Action: Specify an alternative port or stop the listening process."),
        )

    return None


def verify_content_syntax(file_path: str, content: str) -> str | None:
    """Validate content syntax for known formats. Returns error message if invalid."""
    if not file_path or not content:
        return None

    if file_path.endswith(".py"):
        try:
            ast.parse(content, filename=file_path)
        except SyntaxError as e:
            return f"Python syntax error at line {e.lineno}, col {e.offset}: {e.msg}"

    elif file_path.endswith(".json"):
        try:
            json.loads(content)
        except Exception as e:
            return f"Invalid JSON format: {e}"

    return None


def _extract_text_content(content: Any) -> str:
    """Extract plain text from string or structured content block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts)
    return str(content) if content is not None else ""


@dataclass
class _ToolRecord:
    tool_name: str
    is_error: bool
    error_signature: str | None


class HarnessGuardMiddleware(AgentMiddleware):
    """Tool-loop interceptor for write syntax verification, error hints, and anti-doom-loop."""

    def __init__(self, config: HarnessGuardConfig | None = None) -> None:
        self.config = config if config is not None else HarnessGuardConfig()
        self._lock = threading.Lock()
        self._fallback_run_ids: OrderedDict[int, tuple[object, str]] = OrderedDict()
        self._max_fallback_run_ids = max(1, self.config.max_tracked_scopes * 2)
        # Bounded LRU history: _ScopeKey -> deque of _ToolRecord
        self._history: BoundedDict[_ScopeKey, deque[_ToolRecord]] = BoundedDict(maxsize=self.config.max_tracked_scopes)

    def _get_history(self, scope_key: _ScopeKey) -> deque[_ToolRecord]:
        with self._lock:
            if scope_key not in self._history:
                self._history[scope_key] = deque(maxlen=self.config.max_loop_history)
            return self._history[scope_key]

    def _get_thread_id(self, runtime: Any) -> str:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict):
            thread_id = ctx.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        return "default"

    def _get_run_id(self, runtime: Any) -> str | None:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx:
            return ctx["run_id"]

        execution_info = getattr(runtime, "execution_info", None)
        execution_run_id = getattr(execution_info, "run_id", None)
        if execution_run_id is not None:
            return str(execution_run_id)

        # Standalone context-less run: anchor to Runtime.control
        control = getattr(runtime, "control", None)
        anchor = control if control is not None else runtime
        anchor_id = id(anchor)
        with self._lock:
            existing = self._fallback_run_ids.get(anchor_id)
            if existing is not None and existing[0] is anchor:
                self._fallback_run_ids.move_to_end(anchor_id)
                return existing[1]

            fallback_run_id = f"__invocation__:{uuid.uuid4().hex}"
            self._fallback_run_ids[anchor_id] = (anchor, fallback_run_id)
            self._fallback_run_ids.move_to_end(anchor_id)
            while len(self._fallback_run_ids) > self._max_fallback_run_ids:
                self._fallback_run_ids.popitem(last=False)
            return fallback_run_id

    def _scope_key(self, request: ToolCallRequest) -> _ScopeKey:
        return self._get_thread_id(request.runtime), self._get_run_id(request.runtime)

    def _check_write_syntax_block(self, request: ToolCallRequest) -> ToolMessage | None:
        """Perform pre-execution syntax validation on write operations."""
        if not self.config.write_verify_syntax:
            return None

        tool_name = str(request.tool_call.get("name") or "")
        if tool_name not in _WRITE_TOOLS:
            return None

        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None

        file_path = args.get("path") or args.get("file_path") or args.get("filename")
        if not isinstance(file_path, str) or not file_path:
            return None

        err: str | None = None

        if tool_name == "write_file":
            # Skip validation for append writes: append chunks are often not standalone-parseable
            if bool(args.get("append", False)):
                return None

            content = args.get("content") or args.get("text")
            if not isinstance(content, str):
                return None

            err = verify_content_syntax(file_path, content)

        elif tool_name == "str_replace":
            old_str = args.get("old_str")
            new_str = args.get("new_str")
            if isinstance(old_str, str) and isinstance(new_str, str) and (file_path.endswith(".py") or file_path.endswith(".json")):
                try:
                    current = read_current_file_content(request.runtime, file_path)
                    if old_str in current:
                        replace_all = bool(args.get("replace_all", False))
                        spliced = current.replace(old_str, new_str) if replace_all else current.replace(old_str, new_str, 1)
                        err = verify_content_syntax(file_path, spliced)
                except Exception:
                    # Fail open on sandbox read errors and let str_replace handle execution
                    err = None

        if err and self.config.block_on_syntax_error:
            tool_call_id = str(request.tool_call.get("id") or "missing-id")
            logger.warning("HarnessGuard blocked syntax-invalid write to %s: %s", file_path, err)
            msg = ToolMessage(
                content=(f"[HARNESS GUARD: WRITE BLOCKED] Syntax validation failed for '{file_path}':\n{err}\nThe file was NOT written to prevent execution failures. Fix the syntax and retry."),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
                additional_kwargs={
                    HARNESS_GUARD_KEY: {
                        "blocked": True,
                        "reason": "syntax_error",
                        "detail": err,
                        "path": file_path,
                    },
                    TOOL_META_KEY: {
                        "status": "error",
                        "error_type": "SyntaxError",
                        "recoverable_by_model": True,
                        "recommended_next_action": "correct_syntax_and_retry",
                        "source": "harness_guard",
                    },
                },
            )
            return normalize_tool_result(msg)

        return None

    def _post_process_result(
        self,
        request: ToolCallRequest,
        result: ToolMessage | Command,
    ) -> ToolMessage | Command:
        """Analyze tool result, classify error signatures, inject hints, and detect loops."""
        if not isinstance(result, ToolMessage):
            return result

        tool_name = str(request.tool_call.get("name") or result.name or "unknown")
        raw_text = _extract_text_content(result.content)
        is_error = result.status == "error"

        error_sig: ErrorSignature | None = None
        if self.config.targeted_hints_enabled:
            error_sig = classify_tool_error(raw_text)

        if error_sig is not None:
            is_error = True

        # Update sliding history
        scope = self._scope_key(request)
        history = self._get_history(scope)

        sig_str = error_sig.signature if error_sig else None
        record = _ToolRecord(tool_name=tool_name, is_error=is_error, error_signature=sig_str)

        repetition_warning: str | None = None
        oscillation_warning: str | None = None

        with self._lock:
            # Check consecutive identical error signatures
            if sig_str:
                matching_streak = 0
                for r in reversed(history):
                    if r.error_signature == sig_str:
                        matching_streak += 1
                    else:
                        break
                # Current call adds 1
                if matching_streak + 1 >= self.config.max_repeated_error_signatures:
                    repetition_warning = f"[HARNESS GUARD: CRITICAL REPETITION] Error '{sig_str}' has occurred {matching_streak + 1} times consecutively. Do NOT repeat this action without addressing the root cause."

            # Check alternating oscillation pattern (A -> B -> A -> B)
            if self.config.detect_alternating_loops and len(history) >= 3:
                h = list(history)
                r0, r1, r2, r3 = h[-3], h[-2], h[-1], record
                if r0.tool_name == r2.tool_name and r1.tool_name == r3.tool_name and r0.tool_name != r1.tool_name and sum(1 for r in (r0, r1, r2, r3) if r.is_error) >= 3:
                    oscillation_warning = f"[HARNESS GUARD: OSCILLATION DETECTED] Alternating failing tool loop detected between '{r0.tool_name}' and '{r1.tool_name}'. Pause and re-evaluate your strategy."

            history.append(record)

        # Inject hints into ToolMessage content while preserving structured content blocks
        injected_parts: list[str] = []
        if error_sig:
            injected_parts.append(error_sig.targeted_hint)
        if repetition_warning:
            injected_parts.append(repetition_warning)
        if oscillation_warning:
            injected_parts.append(oscillation_warning)

        if injected_parts:
            hint_block_text = "\n\n" + "\n".join(injected_parts)
            if isinstance(result.content, list):
                # Multimodal or content blocks: append hint as a new text block
                new_blocks = list(result.content)
                new_blocks.append({"type": "text", "text": hint_block_text})
                result.content = new_blocks
            elif isinstance(result.content, str):
                separator = "\n\n" if result.content else ""
                result.content = f"{result.content}{separator}{chr(10).join(injected_parts)}"
            else:
                result.content = f"{result.content}{hint_block_text}"

            if HARNESS_GUARD_KEY not in result.additional_kwargs:
                result.additional_kwargs[HARNESS_GUARD_KEY] = {}
            result.additional_kwargs[HARNESS_GUARD_KEY].update(
                {
                    "hints_injected": len(injected_parts),
                    "error_signature": sig_str,
                    "repetition_warning": repetition_warning is not None,
                    "oscillation_warning": oscillation_warning is not None,
                }
            )

        return result

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not self.config.enabled:
            return handler(request)

        blocked = self._check_write_syntax_block(request)
        if blocked is not None:
            return blocked

        result = handler(request)
        return self._post_process_result(request, result)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self.config.enabled:
            return await handler(request)

        blocked = self._check_write_syntax_block(request)
        if blocked is not None:
            return blocked

        result = await handler(request)
        return self._post_process_result(request, result)
