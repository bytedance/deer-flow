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

# Executables whose output is dangerous to *execute*. Used by the command
# substitution rules below; ``\b`` prevents matching unrelated names that merely
# start with one of these words (``shellcheck``, ``shasum``, ``pythonic-tool``).
_RISKY_SUBSTITUTION_EXECUTABLES = r"(?:curl|wget|bash|sh|python[\d.]*|ruby|perl|base64)\b"

# A substitution opening one of those executables, in any of its spellings:
# ``$(cmd``, ``<(cmd``, or the backtick form, which has no parenthesis. Sharing
# one opener is what keeps ``eval `curl u` `` from slipping past a rule written
# only for ``eval $(curl u)``.
_RISKY_SUBSTITUTION = rf"(?:[$<]\(\s*|`\s*){_RISKY_SUBSTITUTION_EXECUTABLES}"

# Interpreters that execute a *code string* handed to them as an argument, and
# the flags that receive it: ``-c`` (shells, python), ``-e`` (perl/ruby/node),
# ``-p`` (perl/node print loop), ``-r`` (php). Whatever the flag receives is
# executed, so a risky substitution there is executed too -- the same class as
# ``eval``/``source``, spelled with a flag instead. A here-string (``<<<``)
# reaches the same place through stdin.
#
# These are position-blind on purpose: ``bash -c`` is an execution context
# wherever it appears, including as an argument to something else
# (``xargs sh -c "$(curl url)"``). The leading-flag repetition is bounded so the
# alternation cannot backtrack on long input.
_CODE_STRING_INTERPRETERS = r"(?:(?:ba|da|k|z)?sh|python[\d.]*|perl|ruby|node|php)"
_LEADING_FLAGS = r"(?:-\w+\s+){0,4}"

# Each pattern is compiled once at import time.
_HIGH_RISK_PATTERNS: list[re.Pattern[str]] = [
    # --- original rules (retained) ---
    re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|/home\b|/root\b)\s*$"),
    re.compile(r"dd\s+if="),
    re.compile(r"mkfs"),
    re.compile(r"cat\s+/etc/shadow"),
    re.compile(r">+\s*/etc/"),
    # --- pipe to sh/bash (generalised, replaces old curl|sh rule) ---
    re.compile(r"\|\s*(ba)?sh\b"),
    # --- eval/source execute a substitution regardless of its position ---
    re.compile(rf"\b(eval|source)\s+[\"']?{_RISKY_SUBSTITUTION}"),
    # --- an interpreter's code-string flag is an execution context too ---
    re.compile(rf"\b{_CODE_STRING_INTERPRETERS}\s+{_LEADING_FLAGS}-[cepr]\s+[\"']?{_RISKY_SUBSTITUTION}"),
    re.compile(rf"\b{_CODE_STRING_INTERPRETERS}\s+{_LEADING_FLAGS}<<<\s*[\"']?{_RISKY_SUBSTITUTION}"),
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

# Command substitution in *command position*: the substitution result becomes the
# command that runs, so fetched or interpreted content is executed.
#
# These are matched anchored against a single sub-command, never against the whole
# compound string, because position is what distinguishes the two shapes:
#
#   $(curl url)          → executes what was downloaded          → block
#   x=$(curl url)        → captures the output into a variable   → pass
#   echo $(curl url)     → passes the output as an argument      → pass
#
# The previous unanchored rule could not tell them apart and refused everyday
# output capture (issue #4611).
#
# A command position is not always the first character: POSIX shell allows leading
# variable assignments, and exec wrappers keep what follows in command position
# (``FOO=1 $(curl url)``, ``env FOO=1 $(curl url)``, ``nohup $(curl url)``). The
# assignment branch cannot match ``x=$(curl url)`` because it requires whitespace
# between the assignment and the substitution, so value position stays allowed.
# The repetition is bounded to keep the alternation from backtracking on long input.
_COMMAND_POSITION_PREFIX = r"(?:(?:env|command|builtin|exec|nohup|time|sudo|doas)\s+|\w+=\S*\s+){0,8}"

_HIGH_RISK_COMMAND_POSITION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"^{_COMMAND_POSITION_PREFIX}[\"']?\$\(\s*{_RISKY_SUBSTITUTION_EXECUTABLES}"),
    re.compile(rf"^{_COMMAND_POSITION_PREFIX}[\"']?`\s*{_RISKY_SUBSTITUTION_EXECUTABLES}"),
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


# A heredoc header and its delimiter: ``<<EOF``, ``<< EOF``, ``<<-EOF``,
# ``<<\EOF``, ``<<'EOF'``, ``<<"EOF"``. Both guards are needed to keep ``<<<``
# (a here-string, which has no body) from opening one: the lookahead rejects it
# at its first ``<``, and the lookbehind stops its trailing ``<<`` from matching
# one character later, where ``<<< "text"`` would otherwise read as a heredoc
# with delimiter ``text``.
_HEREDOC_HEADER = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(?:\\?([A-Za-z_][\w.-]*)|'([^'\n]*)'|\"([^\"\n]*)\")")


def _consume_heredoc_bodies(command: str, pos: int, delimiters: list[str]) -> int:
    """Return the index just past the bodies of the *delimiters* opened so far.

    Bodies are consumed in the order their headers appeared, each running until a
    line whose stripped content equals its delimiter (``<<-`` strips leading tabs,
    which ``strip()`` covers). An unterminated body consumes the rest of the
    string: everything after the header genuinely is body, and there is no later
    statement to find.
    """
    for delimiter in delimiters:
        while pos < len(command):
            newline = command.find("\n", pos)
            if newline == -1:
                return len(command)
            line = command[pos:newline]
            pos = newline + 1
            if line.strip() == delimiter:
                break
        else:
            return len(command)
    return pos


def _split_compound_command(command: str, *, split_pipes: bool = False) -> list[str]:
    """Split a compound command into sub-commands (quote-aware).

    Scans the raw command string so unquoted shell control operators are
    recognised even when they are not surrounded by whitespace
    (e.g. ``safe;rm -rf /`` or ``rm -rf /&&echo ok``). Operators inside
    quotes are ignored. If the command ends with an unclosed quote or a
    dangling escape, return the whole command unchanged (fail-closed —
    safer to classify the unsplit string than silently drop parts).

    Sequencing operators (``&&``, ``||``, ``;``) split, and so does an unquoted
    newline — it separates statements exactly like ``;``, so leaving it joined let
    ``echo hi\\n$(curl url)`` evade the anchored command-position rules that
    ``echo hi; $(curl url)`` triggers, despite identical shell semantics.

    A heredoc body is data, not statements: its newlines and operators are file
    content. Headers (``<<EOF``, ``<<-EOF``, ``<<'EOF'``) are therefore recorded
    as they are read and their bodies consumed verbatim at the newline that
    starts them, so a body line beginning with ``$(curl url)`` is not promoted to
    command position. ``<<<`` is a here-string, not a heredoc, and does not open
    one; neither does a ``<<`` inside ``$(( ... ))`` or ``(( ... ))``, where it is
    a bit shift whose right operand would otherwise read as a delimiter that never
    appears — swallowing the rest of the command. This is a heuristic, not shell
    parsing — the goal is only to avoid manufacturing command positions that the
    shell would never create, and to avoid destroying real ones.

    Pipes do not split by default, because a pipeline is one logical command.
    Pass ``split_pipes=True`` to also split on ``|``, which is what
    command-position detection needs — the word after a pipe starts a new
    command. Rules that span a pipe (``| sh``, ``base64 -d | ...``) are matched by
    the whole-command scan in :func:`_classify_command`, so they are unaffected by
    the extra split.
    """
    parts: list[str] = []
    current: list[str] = []
    pending_heredocs: list[str] = []
    in_single_quote = False
    in_double_quote = False
    arithmetic_depth = 0
    escaping = False
    index = 0

    while index < len(command):
        char = command[index]

        if escaping:
            current.append(char)
            escaping = False
            index += 1
            continue

        if char == "\\" and not in_single_quote:
            current.append(char)
            escaping = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            # ``<<`` inside arithmetic is a bit shift, not a redirection, and a
            # phantom header whose delimiter never appears would swallow the rest
            # of the command. Both ``$(( ... ))`` and the bare arithmetic command
            # ``(( ... ))`` are tracked. An unclosed ``((`` leaves the depth
            # positive, which only disables heredoc detection — newlines keep
            # splitting, so the failure direction stays towards seeing more
            # command positions rather than fewer.
            if char == "(" and command.startswith("((", index):
                arithmetic_depth += 1
                current.append("((")
                index += 2
                continue
            if arithmetic_depth and char == ")" and command.startswith("))", index):
                arithmetic_depth -= 1
                current.append("))")
                index += 2
                continue
            # A header can only start at ``<``; checking that first keeps the
            # regex off every other character of a long command.
            if char == "<" and not arithmetic_depth:
                heredoc = _HEREDOC_HEADER.match(command, index)
                if heredoc:
                    pending_heredocs.append(next(group for group in heredoc.groups() if group is not None))
                    current.append(heredoc.group(0))
                    index = heredoc.end()
                    continue
            if char == "\n":
                # The newline that follows a heredoc header is the statement
                # separator, and its body belongs to the statement being closed.
                if pending_heredocs:
                    body_end = _consume_heredoc_bodies(command, index + 1, pending_heredocs)
                    pending_heredocs = []
                    current.append(command[index:body_end])
                    index = body_end
                else:
                    index += 1
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                continue
            if command.startswith("&&", index) or command.startswith("||", index):
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += 2
                continue
            # Checked after "||" so a single "|" cannot steal that operator.
            if split_pipes and char == "|":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += 1
                continue
            if char == ";":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += 1
                continue

        current.append(char)
        index += 1

    # Unclosed quote or dangling escape → fail-closed, return whole command
    if in_single_quote or in_double_quote or escaping:
        return [command]

    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts if parts else [command]


def _matches_high_risk(candidate: str) -> bool:
    """Return True if *candidate* (one sub-command) matches any high-risk rule."""
    if any(pattern.search(candidate) for pattern in _HIGH_RISK_PATTERNS):
        return True
    # Anchored: only meaningful for a single sub-command, not a compound string.
    return any(pattern.match(candidate) for pattern in _HIGH_RISK_COMMAND_POSITION_PATTERNS)


def _classify_single_command(command: str) -> str:
    """Classify a single (non-compound) command. Return 'block', 'warn', or 'pass'."""
    normalized = " ".join(command.split())

    if _matches_high_risk(normalized):
        return "block"

    # Also try shlex-parsed tokens for high-risk detection
    try:
        tokens = shlex.split(command)
        joined = " ".join(tokens)
        if _matches_high_risk(joined):
            return "block"
    except ValueError:
        # Heredocs and other multiline shell forms may be valid bash but
        # unparseable by shlex. Raw high-risk patterns were already checked.
        pass

    for pattern in _MEDIUM_RISK_PATTERNS:
        if pattern.search(normalized):
            return "warn"

    return "pass"


def _classify_command(command: str) -> str:
    """Return 'block', 'warn', or 'pass'.

    Strategy:
    1. First scan the *whole* raw command against high-risk patterns. This
       catches structural attacks like ``while true; do bash & done`` or
       ``:(){ :|:& };:`` that span multiple shell statements — splitting them
       on ``;`` would destroy the pattern context.
    2. Then split compound commands (e.g. ``cmd1 && cmd2 ; cmd3``) and
       classify each sub-command independently. The most severe verdict wins.
    """
    # Pass 1: whole-command high-risk scan (catches multi-statement patterns)
    normalized = " ".join(command.split())
    for pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(normalized):
            return "block"

    # Pass 2: per-sub-command classification. Pipes split here too, because the
    # word after a pipe starts a new command position (``echo hi | $(curl ...)``).
    sub_commands = _split_compound_command(command, split_pipes=True)
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
       via the standard logger (visible in gateway.log).

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

    _AUDIT_COMMAND_LIMIT = 200

    def _write_audit(self, thread_id: str | None, command: str, verdict: str, *, truncate: bool = False) -> None:
        audited_command = command
        if truncate and len(command) > self._AUDIT_COMMAND_LIMIT:
            audited_command = f"{command[: self._AUDIT_COMMAND_LIMIT]}... ({len(command)} chars)"
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "thread_id": thread_id or "unknown",
            "command": audited_command,
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
    # Input sanitisation
    # ------------------------------------------------------------------

    # Normal bash commands rarely exceed a few hundred characters.  10 000 is
    # well above any legitimate use case yet a tiny fraction of Linux ARG_MAX.
    # Anything longer is almost certainly a payload injection or base64-encoded
    # attack string.
    _MAX_COMMAND_LENGTH = 10_000

    def _validate_input(self, command: str) -> str | None:
        """Return ``None`` if *command* is acceptable, else a rejection reason."""
        if not command.strip():
            return "empty command"
        if len(command) > self._MAX_COMMAND_LENGTH:
            return "command too long"
        if "\x00" in command:
            return "null byte detected"
        return None

    # ------------------------------------------------------------------
    # Core logic (shared between sync and async paths)
    # ------------------------------------------------------------------

    def _pre_process(self, request: ToolCallRequest) -> tuple[str, str | None, str, str | None]:
        """
        Returns (command, thread_id, verdict, reject_reason).
        verdict is 'block', 'warn', or 'pass'.
        reject_reason is non-None only for input sanitisation rejections.
        """
        args = request.tool_call.get("args", {})
        raw_command = args.get("command")
        command = raw_command if isinstance(raw_command, str) else ""
        thread_id = self._get_thread_id(request)

        # ① input sanitisation — reject malformed input before regex analysis
        reject_reason = self._validate_input(command)
        if reject_reason:
            self._write_audit(thread_id, command, "block", truncate=True)
            logger.warning("[SandboxAudit] INVALID INPUT thread=%s reason=%s", thread_id, reject_reason)
            return command, thread_id, "block", reject_reason

        # ② classify command
        verdict = _classify_command(command)

        # ③ audit log
        self._write_audit(thread_id, command, verdict)

        if verdict == "block":
            logger.warning("[SandboxAudit] BLOCKED thread=%s cmd=%r", thread_id, command)
        elif verdict == "warn":
            logger.warning("[SandboxAudit] WARN (medium-risk) thread=%s cmd=%r", thread_id, command)

        return command, thread_id, verdict, None

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

        command, _, verdict, reject_reason = self._pre_process(request)
        if verdict == "block":
            reason = reject_reason or "security violation detected"
            return self._build_block_message(request, reason)
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

        command, _, verdict, reject_reason = self._pre_process(request)
        if verdict == "block":
            reason = reject_reason or "security violation detected"
            return self._build_block_message(request, reason)
        result = await handler(request)
        if verdict == "warn":
            result = self._append_warn_to_result(result, command)
        return result
