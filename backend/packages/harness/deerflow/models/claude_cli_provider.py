"""Claude Code CLI provider — use Pro/Max subscription as a LangChain model.

Wraps the ``claude`` CLI in ``--print`` mode, enabling DeerFlow to leverage
the user's existing Claude Pro or Max subscription at **zero additional API
cost**.  No ``ANTHROPIC_API_KEY`` required.

Authentication
--------------
Uses global auth established by ``claude /login`` (stored in macOS Keychain
or ``~/.claude/``).  The CLI handles token refresh automatically.

Usage in config.yaml::

    models:
      - name: claude-sonnet
        display_name: Claude Sonnet 4.6 (Max subscription)
        use: deerflow.models.claude_cli_provider:ClaudeCLIModel
        model: claude-sonnet-4-6
        max_tokens: 16384

Prerequisites
-------------
- Claude Code CLI installed: ``curl -fsSL https://claude.ai/install.sh | bash``
- Authenticated: ``claude /login``
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

# Environment variables that interfere with the Claude CLI subprocess.
# These are set by parent processes (VS Code, Electron, Claude Code itself)
# and must be stripped to avoid conflicts.
_FILTERED_ENV_VARS = frozenset({
    "CLAUDECODE",
    "NODE_OPTIONS",
    "VSCODE_INSPECTOR_OPTIONS",
    "ELECTRON_RUN_AS_NODE",
})

# Well-known install locations for the Claude CLI.
_CLI_SEARCH_PATHS = [
    "~/.local/bin/claude",
    "/usr/local/bin/claude",
    "~/.claude/local/claude",
]


def _find_claude_cli() -> str:
    """Locate the ``claude`` CLI binary.

    Checks ``$PATH`` first, then falls back to well-known install locations.

    Raises:
        FileNotFoundError: If the CLI cannot be found.
    """
    path = shutil.which("claude")
    if path:
        return path

    for candidate in _CLI_SEARCH_PATHS:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded

    raise FileNotFoundError(
        "Claude Code CLI not found. "
        "Install: curl -fsSL https://claude.ai/install.sh | bash  "
        "Then run: claude /login"
    )


def _build_subprocess_env() -> dict[str, str]:
    """Build a clean environment for the Claude subprocess.

    Strips variables that cause the subprocess to misbehave (debugger
    attach, Electron flags, recursive Claude detection).
    """
    return {k: v for k, v in os.environ.items() if k not in _FILTERED_ENV_VARS}


def _extract_system_prompt(messages: list[BaseMessage]) -> str | None:
    """Collect all ``SystemMessage`` contents into a single system prompt."""
    parts = [
        msg.content for msg in messages
        if isinstance(msg, SystemMessage) and isinstance(msg.content, str)
    ]
    return "\n\n".join(parts) if parts else None


def _extract_user_prompt(messages: list[BaseMessage]) -> str:
    """Convert non-system messages into a single prompt string.

    Multi-turn history is serialised as labelled blocks so the CLI
    (which only accepts a single prompt string) retains conversational
    context.
    """
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if isinstance(msg, HumanMessage):
            parts.append(content)
        elif isinstance(msg, AIMessage):
            parts.append(f"[Previous assistant response]: {content}")
    return "\n\n".join(parts)


class ClaudeCLIModel(BaseChatModel):
    """LangChain ``BaseChatModel`` backed by the Claude Code CLI.

    Each call spawns ``claude --print --output-format json`` as a subprocess,
    authenticating with the user's existing Pro/Max subscription.

    Parameters
    ----------
    model : str
        Model identifier (e.g. ``claude-sonnet-4-6``, ``claude-opus-4-6``).
    max_tokens : int
        Maximum output tokens per response.
    max_turns : int
        Maximum agentic turns the CLI may take per invocation.
    cwd : str
        Working directory for the subprocess.  Defaults to ``os.getcwd()``.
    permission_mode : str
        CLI permission mode.  One of ``default``, ``acceptEdits``,
        ``bypassPermissions``, ``plan``.
    allowed_tools : list[str] | None
        Allowlist of CLI tool names (e.g. ``["Bash(git:*)", "Read"]``).
    disallowed_tools : list[str] | None
        Denylist of CLI tool names.
    timeout_seconds : int
        Hard timeout for the subprocess (default 300s / 5 min).
    """

    model: str = "claude-sonnet-4-6"
    max_tokens: int = 16384
    max_turns: int = 3
    cwd: str = ""
    permission_mode: str = "bypassPermissions"
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    timeout_seconds: int = 300

    # Private — not included in serialisation or identifying params.
    _claude_path: str = ""
    _bound_tools: list[dict[str, Any]] = []

    model_config = {"arbitrary_types_allowed": True}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def model_post_init(self, __context: Any) -> None:
        self._claude_path = _find_claude_cli()
        if not self.cwd:
            self.cwd = os.getcwd()
        logger.info(
            "ClaudeCLIModel ready  model=%s  cli=%s",
            self.model,
            self._claude_path,
        )

    # ------------------------------------------------------------------
    # BaseChatModel interface
    # ------------------------------------------------------------------

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "max_tokens": self.max_tokens, "max_turns": self.max_turns}

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ClaudeCLIModel:
        """Bind LangChain / LangGraph tools.

        Tool schemas are serialised into the system prompt so the Claude CLI
        subprocess is aware of the available DeerFlow tools.  This satisfies
        the ``bind_tools`` contract that LangGraph's agent factory requires.
        """
        bound = copy.copy(self)
        tool_defs: list[dict[str, Any]] = []
        for tool in tools:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                entry: dict[str, Any] = {
                    "name": getattr(tool, "name", "unknown"),
                    "description": getattr(tool, "description", ""),
                }
                if hasattr(tool, "args_schema") and tool.args_schema:
                    try:
                        entry["parameters"] = tool.args_schema.model_json_schema()
                    except Exception:
                        pass
                tool_defs.append(entry)
            elif isinstance(tool, dict):
                tool_defs.append(tool)
        bound._bound_tools = tool_defs
        return bound

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system_prompt = _extract_system_prompt(messages)
        user_prompt = _extract_user_prompt(messages)

        if not user_prompt.strip():
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

        cmd = self._build_command(user_prompt, system_prompt)
        logger.debug("claude CLI cmd (first 5 tokens): %s", cmd[:5])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                env=_build_subprocess_env(),
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out after %ds", self.timeout_seconds)
            raise TimeoutError(f"Claude CLI subprocess timed out after {self.timeout_seconds}s")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Claude CLI not found at {self._claude_path}. "
                "Install: curl -fsSL https://claude.ai/install.sh | bash"
            )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            logger.error("Claude CLI exit %d: %s", proc.returncode, stderr[:500])
            raise RuntimeError(f"Claude CLI failed (exit {proc.returncode}): {stderr[:500]}")

        return self._parse_cli_output(proc.stdout.strip())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_tools_prompt(self) -> str:
        """Render bound tool schemas as a system-prompt appendix."""
        if not self._bound_tools:
            return ""

        lines = ["\n\n## Available Tools\n"]
        for tool in self._bound_tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            lines.append(f"- **{name}**: {desc}")
            for pname, pinfo in tool.get("parameters", {}).get("properties", {}).items():
                ptype = pinfo.get("type", "any")
                pdesc = pinfo.get("description", "")
                lines.append(f"  - `{pname}` ({ptype}): {pdesc}")
        return "\n".join(lines)

    def _build_command(self, prompt: str, system_prompt: str | None = None) -> list[str]:
        """Assemble the ``claude`` CLI invocation."""
        cmd = [
            self._claude_path,
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--max-turns", str(self.max_turns),
            "--permission-mode", self.permission_mode,
            "--no-session-persistence",
        ]

        # Merge system prompt with tool descriptions.
        full_system = system_prompt or ""
        tools_section = self._build_tools_prompt()
        if tools_section:
            full_system = (full_system + tools_section) if full_system else tools_section
        if full_system:
            cmd.extend(["--system-prompt", full_system])

        if self.allowed_tools:
            cmd.extend(["--allowed-tools", ",".join(self.allowed_tools)])
        if self.disallowed_tools:
            cmd.extend(["--disallowed-tools", ",".join(self.disallowed_tools)])

        cmd.append(prompt)
        return cmd

    def _parse_cli_output(self, stdout: str) -> ChatResult:
        """Parse the JSON envelope returned by ``claude --print --output-format json``."""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=stdout))])

        content = data.get("result", "")
        if data.get("is_error"):
            logger.warning("Claude CLI error result: %s", content[:200])

        usage = data.get("usage", {})
        usage_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        }

        response_metadata = {
            "model": self.model,
            "stop_reason": data.get("stop_reason", ""),
            "duration_ms": data.get("duration_ms", 0),
            "duration_api_ms": data.get("duration_api_ms", 0),
            "num_turns": data.get("num_turns", 0),
            "session_id": data.get("session_id", ""),
            "cost_usd": data.get("total_cost_usd", 0),
        }

        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=content,
                        usage_metadata=usage_metadata,
                        response_metadata=response_metadata,
                    )
                )
            ],
            llm_output={"token_usage": usage_metadata, "model_name": self.model},
        )
