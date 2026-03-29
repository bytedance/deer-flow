"""DeerFlowClient — Embedded Python client for DeerFlow agent system.

Provides direct programmatic access to DeerFlow's agent capabilities
without requiring LangGraph Server or Gateway API processes.

Usage:
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient()
    response = client.chat("Analyze this paper for me", thread_id="my-thread")
    print(response)

    # Streaming
    for event in client.stream("hello"):
        print(event)
"""

import asyncio
import json
import logging
import mimetypes
import shutil
import tempfile
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.agent import _build_middlewares
from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.agents.thread_state import ThreadState
from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.app_config import get_app_config, reload_app_config
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from deerflow.config.paths import get_paths
from deerflow.models import create_chat_model
from deerflow.skills.installer import install_skill_from_archive
from deerflow.uploads.manager import (
    claim_unique_filename,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    upload_artifact_url,
    upload_virtual_path,
)

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """A single event from the streaming agent response.

    Event types align with the LangGraph SSE protocol:
        - ``"values"``: Full state snapshot (title, messages, artifacts).
        - ``"messages-tuple"``: Per-message update (AI text, tool calls, tool results).
        - ``"end"``: Stream finished.

    Attributes:
        type: Event type.
        data: Event payload. Contents vary by type.
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


class DeerFlowClient:
    """Embedded Python client for DeerFlow agent system.

    Provides direct programmatic access to DeerFlow's agent capabilities
    without requiring LangGraph Server or Gateway API processes.

    Note:
        Multi-turn conversations require a ``checkpointer``. Without one,
        each ``stream()`` / ``chat()`` call is stateless — ``thread_id``
        is only used for file isolation (uploads / artifacts).

        The system prompt (including date, memory, and skills context) is
        generated when the internal agent is first created and cached until
        the configuration key changes. Call :meth:`reset_agent` to force
        a refresh in long-running processes.

    Example::

        from deerflow.client import DeerFlowClient

        client = DeerFlowClient()

        # Simple one-shot
        print(client.chat("hello"))

        # Streaming
        for event in client.stream("hello"):
            print(event.type, event.data)

        # Configuration queries
        print(client.list_models())
        print(client.list_skills())
    """

    def __init__(
        self,
        config_path: str | None = None,
        checkpointer=None,
        *,
        model_name: str | None = None,
        thinking_enabled: bool = True,
        subagent_enabled: bool = False,
        plan_mode: bool = False,
        agent_name: str | None = None,
        middlewares: Sequence[AgentMiddleware] | None = None,
    ):
        """Initialize the client.

        Loads configuration but defers agent creation to first use.

        Args:
            config_path: Path to config.yaml. Uses default resolution if None.
            checkpointer: LangGraph checkpointer instance for state persistence.
                Required for multi-turn conversations on the same thread_id.
                Without a checkpointer, each call is stateless.
            model_name: Override the default model name from config.
            thinking_enabled: Enable model's extended thinking.
            subagent_enabled: Enable subagent delegation.
            plan_mode: Enable TodoList middleware for plan mode.
            agent_name: Name of the agent to use.
            middlewares: Optional list of custom middlewares to inject into the agent.
        """
        if config_path is not None:
            reload_app_config(config_path)
        self._app_config = get_app_config()

        if agent_name is not None and not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name '{agent_name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")

        self._checkpointer = checkpointer
        self._model_name = model_name
        self._thinking_enabled = thinking_enabled
        self._subagent_enabled = subagent_enabled
        self._plan_mode = plan_mode
        self._agent_name = agent_name
        self._middlewares = list(middlewares) if middlewares else []

        # Lazy agent — created on first call, recreated when config changes.
        self._agent = None
        self._agent_config_key: tuple | None = None

    def reset_agent(self) -> None:
        """Force the internal agent to be recreated on the next call.

        Use this after external changes (e.g. memory updates, skill
        installations) that should be reflected in the system prompt
        or tool set.
        """
        self._agent = None
        self._agent_config_key = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        """Write JSON to *path* atomically (temp file + replace)."""
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    def _get_runnable_config(self, thread_id: str, **overrides) -> RunnableConfig:
        """Build a RunnableConfig for agent invocation."""
        configurable = {
            "thread_id": thread_id,
            "model_name": overrides.get("model_name", self._model_name),
            "thinking_enabled": overrides.get("thinking_enabled", self._thinking_enabled),
            "is_plan_mode": overrides.get("plan_mode", self._plan_mode),
            "subagent_enabled": overrides.get("subagent_enabled", self._subagent_enabled),
        }
        return RunnableConfig(
            configurable=configurable,
            recursion_limit=overrides.get("recursion_limit", 100),
        )

    def _ensure_agent(self, config: RunnableConfig):
        """Create (or recreate) the agent when config-dependent params change."""
        cfg = config.get("configurable", {})
        key = (
            cfg.get("model_name"),
            cfg.get("thinking_enabled"),
            cfg.get("is_plan_mode"),
            cfg.get("subagent_enabled"),
        )

        if self._agent is not None and self._agent_config_key == key:
            return

        thinking_enabled = cfg.get("thinking_enabled", True)
        model_name = cfg.get("model_name")
        subagent_enabled = cfg.get("subagent_enabled", False)
        max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)

        kwargs: dict[str, Any] = {
            "model": create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            "tools": self._get_tools(model_name=model_name, subagent_enabled=subagent_enabled),
            "middleware": _build_middlewares(config, model_name=model_name, agent_name=self._agent_name, custom_middlewares=self._middlewares),
            "system_prompt": apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
                agent_name=self._agent_name,
            ),
            "state_schema": ThreadState,
        }
        checkpointer = self._checkpointer
        if checkpointer is None:
            from deerflow.agents.checkpointer import get_checkpointer

            checkpointer = get_checkpointer()
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

        self._agent = create_agent(**kwargs)
        self._agent_config_key = key
        logger.info("Agent created: agent_name=%s, model=%s, thinking=%s", self._agent_name, model_name, thinking_enabled)

    @staticmethod
    def _get_tools(*, model_name: str | None, subagent_enabled: bool):
        """Lazy import to avoid circular dependency at module level."""
        from deerflow.tools import get_available_tools

        return get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    @staticmethod
    def _serialize_message(msg) -> dict:
        """Serialize a LangChain message to a plain dict for values events."""
        if isinstance(msg, AIMessage):
            d: dict[str, Any] = {"type": "ai", "content": msg.content, "id": getattr(msg, "id", None)}
            if msg.tool_calls:
                d["tool_calls"] = [{"name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in msg.tool_calls]
            if getattr(msg, "usage_metadata", None):
                d["usage_metadata"] = msg.usage_metadata
            return d
        if isinstance(msg, ToolMessage):
            return {
                "type": "tool",
                "content": DeerFlowClient._extract_text(msg.content),
                "name": getattr(msg, "name", None),
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "id": getattr(msg, "id", None),
            }
        if isinstance(msg, HumanMessage):
            return {"type": "human", "content": msg.content, "id": getattr(msg, "id", None)}
        if isinstance(msg, SystemMessage):
            return {"type": "system", "content": msg.content, "id": getattr(msg, "id", None)}
        return {"type": "unknown", "content": str(msg), "id": getattr(msg, "id", None)}

    @staticmethod
    def _extract_text(content) -> str:
        """Extract plain text from AIMessage content (str or list of blocks).

        String chunks are concatenated without separators to avoid corrupting
        token/character deltas or chunked JSON payloads. Dict-based text blocks
        are treated as full text blocks and joined with newlines to preserve
        readability.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            if content and all(isinstance(block, str) for block in content):
                chunk_like = len(content) > 1 and all(isinstance(block, str) and len(block) <= 20 and any(ch in block for ch in '{}[]":,') for block in content)
                return "".join(content) if chunk_like else "\n".join(content)

            pieces: list[str] = []
            pending_str_parts: list[str] = []

            def flush_pending_str_parts() -> None:
                if pending_str_parts:
                    pieces.append("".join(pending_str_parts))
                    pending_str_parts.clear()

            for block in content:
                if isinstance(block, str):
                    pending_str_parts.append(block)
                elif isinstance(block, dict):
                    flush_pending_str_parts()
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        pieces.append(text_val)

            flush_pending_str_parts()
            return "\n".join(pieces) if pieces else ""
        return str(content)

    # ------------------------------------------------------------------
    # Public API — conversation
    # ------------------------------------------------------------------

    def stream(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        **kwargs,
    ) -> Generator[StreamEvent, None, None]:
        """Stream a conversation turn, yielding events incrementally.

        Each call sends one user message and yields events until the agent
        finishes its turn. A ``checkpointer`` must be provided at init time
        for multi-turn context to be preserved across calls.

        Event types align with the LangGraph SSE protocol so that
        consumers can switch between HTTP streaming and embedded mode
        without changing their event-handling logic.

        Args:
            message: User message text.
            thread_id: Thread ID for conversation context. Auto-generated if None.
            **kwargs: Override client defaults (model_name, thinking_enabled,
                plan_mode, subagent_enabled, recursion_limit).

        Yields:
            StreamEvent with one of:
            - type="values"          data={"title": str|None, "messages": [...], "artifacts": [...]}
            - type="messages-tuple"  data={"type": "ai", "content": str, "id": str}
            - type="messages-tuple"  data={"type": "ai", "content": str, "id": str, "usage_metadata": {...}}
            - type="messages-tuple"  data={"type": "ai", "content": "", "id": str, "tool_calls": [...]}
            - type="messages-tuple"  data={"type": "tool", "content": str, "name": str, "tool_call_id": str, "id": str}
            - type="end"             data={"usage": {"input_tokens": int, "output_tokens": int, "total_tokens": int}}
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config = self._get_runnable_config(thread_id, **kwargs)
        self._ensure_agent(config)

        state: dict[str, Any] = {"messages": [HumanMessage(content=message)]}
        context = {"thread_id": thread_id}
        if self._agent_name:
            context["agent_name"] = self._agent_name

        seen_ids: set[str] = set()
        cumulative_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        for chunk in self._agent.stream(state, config=config, context=context, stream_mode="values"):
            messages = chunk.get("messages", [])

            for msg in messages:
                msg_id = getattr(msg, "id", None)
                if msg_id and msg_id in seen_ids:
                    continue
                if msg_id:
                    seen_ids.add(msg_id)

                if isinstance(msg, AIMessage):
                    # Track token usage from AI messages
                    usage = getattr(msg, "usage_metadata", None)
                    if usage:
                        cumulative_usage["input_tokens"] += usage.get("input_tokens", 0) or 0
                        cumulative_usage["output_tokens"] += usage.get("output_tokens", 0) or 0
                        cumulative_usage["total_tokens"] += usage.get("total_tokens", 0) or 0

                    if msg.tool_calls:
                        yield StreamEvent(
                            type="messages-tuple",
                            data={
                                "type": "ai",
                                "content": "",
                                "id": msg_id,
                                "tool_calls": [{"name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in msg.tool_calls],
                            },
                        )

                    text = self._extract_text(msg.content)
                    if text:
                        event_data: dict[str, Any] = {"type": "ai", "content": text, "id": msg_id}
                        if usage:
                            event_data["usage_metadata"] = {
                                "input_tokens": usage.get("input_tokens", 0) or 0,
                                "output_tokens": usage.get("output_tokens", 0) or 0,
                                "total_tokens": usage.get("total_tokens", 0) or 0,
                            }
                        yield StreamEvent(type="messages-tuple", data=event_data)

                elif isinstance(msg, ToolMessage):
                    yield StreamEvent(
                        type="messages-tuple",
                        data={
                            "type": "tool",
                            "content": self._extract_text(msg.content),
                            "name": getattr(msg, "name", None),
                            "tool_call_id": getattr(msg, "tool_call_id", None),
                            "id": msg_id,
                        },
                    )

            # Emit a values event for each state snapshot
            yield StreamEvent(
                type="values",
                data={
                    "title": chunk.get("title"),
                    "messages": [self._serialize_message(m) for m in messages],
                    "artifacts": chunk.get("artifacts", []),
                },
            )

        yield StreamEvent(type="end", data={"usage": cumulative_usage})

    def chat(self, message: str, *, thread_id: str | None = None, **kwargs) -> str:
        """Send a message and return the final text response.

        Convenience wrapper around :meth:`stream` that returns only the
        **last** AI text from ``messages-tuple`` events. If the agent emits
        multiple text segments in one turn, intermediate segments are
        discarded. Use :meth:`stream` directly to capture all events.

        Args:
            message: User message text.
            thread_id: Thread ID for conversation context. Auto-generated if None.
            **kwargs: Override client defaults (same as stream()).

        Returns:
            The last AI message text, or empty string if no response.
        """
        last_text = ""
        for event in self.stream(message, thread_id=thread_id, **kwargs):
            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                content = event.data.get("content", "")
                if content:
                    last_text = content
        return last_text

    # ------------------------------------------------------------------
    # Public API — configuration queries
    # ------------------------------------------------------------------

    def list_models(self) -> dict:
        """List available models from configuration.

        Returns:
            Dict with "models" key containing list of model info dicts,
            matching the Gateway API ``ModelsListResponse`` schema.
        """
        return {
            "models": [
                {
                    "name": model.name,
                    "model": getattr(model, "model", None),
                    "display_name": getattr(model, "display_name", None),
                    "description": getattr(model, "description", None),
                    "supports_thinking": getattr(model, "supports_thinking", False),
                    "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
                }
                for model in self._app_config.models
            ]
        }

    def list_skills(self, enabled_only: bool = False) -> dict:
        """List available skills.

        Args:
            enabled_only: If True, only return enabled skills.

        Returns:
            Dict with "skills" key containing list of skill info dicts,
            matching the Gateway API ``SkillsListResponse`` schema.
        """
        from deerflow.skills.loader import load_skills

        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "license": s.license,
                    "category": s.category,
                    "enabled": s.enabled,
                }
                for s in load_skills(enabled_only=enabled_only)
            ]
        }

    def get_memory(self) -> dict:
        """Get current memory data.

        Returns:
            Memory data dict (see src/agents/memory/updater.py for structure).
        """
        from deerflow.agents.memory.updater import get_memory_data

        return get_memory_data()

    def get_model(self, name: str) -> dict | None:
        """Get a specific model's configuration by name.

        Args:
            name: Model name.

        Returns:
            Model info dict matching the Gateway API ``ModelResponse``
            schema, or None if not found.
        """
        model = self._app_config.get_model_config(name)
        if model is None:
            return None
        return {
            "name": model.name,
            "model": getattr(model, "model", None),
            "display_name": getattr(model, "display_name", None),
            "description": getattr(model, "description", None),
            "supports_thinking": getattr(model, "supports_thinking", False),
            "supports_reasoning_effort": getattr(model, "supports_reasoning_effort", False),
        }

    # ------------------------------------------------------------------
    # Public API — MCP configuration
    # ------------------------------------------------------------------

    def get_mcp_config(self) -> dict:
        """Get MCP server configurations.

        Returns:
            Dict with "mcp_servers" key mapping server name to config,
            matching the Gateway API ``McpConfigResponse`` schema.
        """
        config = get_extensions_config()
        return {"mcp_servers": {name: server.model_dump() for name, server in config.mcp_servers.items()}}

    def update_mcp_config(self, mcp_servers: dict[str, dict]) -> dict:
        """Update MCP server configurations.

        Writes to extensions_config.json and reloads the cache.

        Args:
            mcp_servers: Dict mapping server name to config dict.
                Each value should contain keys like enabled, type, command, args, env, url, etc.

        Returns:
            Dict with "mcp_servers" key, matching the Gateway API
            ``McpConfigResponse`` schema.

        Raises:
            OSError: If the config file cannot be written.
        """
        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

        current_config = get_extensions_config()

        config_data = {
            "mcpServers": mcp_servers,
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        self._atomic_write_json(config_path, config_data)

        self._agent = None
        self._agent_config_key = None
        reloaded = reload_extensions_config()
        return {"mcp_servers": {name: server.model_dump() for name, server in reloaded.mcp_servers.items()}}

    # ------------------------------------------------------------------
    # Public API — skills management
    # ------------------------------------------------------------------

    def get_skill(self, name: str) -> dict | None:
        """Get a specific skill by name.

        Args:
            name: Skill name.

        Returns:
            Skill info dict, or None if not found.
        """
        from deerflow.skills.loader import load_skills

        skill = next((s for s in load_skills(enabled_only=False) if s.name == name), None)
        if skill is None:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "license": skill.license,
            "category": skill.category,
            "enabled": skill.enabled,
        }

    def update_skill(self, name: str, *, enabled: bool) -> dict:
        """Update a skill's enabled status.

        Args:
            name: Skill name.
            enabled: New enabled status.

        Returns:
            Updated skill info dict.

        Raises:
            ValueError: If the skill is not found.
            OSError: If the config file cannot be written.
        """
        from deerflow.skills.loader import load_skills

        skills = load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == name), None)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")

        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

        extensions_config = get_extensions_config()
        extensions_config.skills[name] = SkillStateConfig(enabled=enabled)

        config_data = {
            "mcpServers": {n: s.model_dump() for n, s in extensions_config.mcp_servers.items()},
            "skills": {n: {"enabled": sc.enabled} for n, sc in extensions_config.skills.items()},
        }

        self._atomic_write_json(config_path, config_data)

        self._agent = None
        self._agent_config_key = None
        reload_extensions_config()

        updated = next((s for s in load_skills(enabled_only=False) if s.name == name), None)
        if updated is None:
            raise RuntimeError(f"Skill '{name}' disappeared after update")
        return {
            "name": updated.name,
            "description": updated.description,
            "license": updated.license,
            "category": updated.category,
            "enabled": updated.enabled,
        }

    def install_skill(self, skill_path: str | Path) -> dict:
        """Install a skill from a .skill archive (ZIP).

        Args:
            skill_path: Path to the .skill file.

        Returns:
            Dict with success, skill_name, message.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is invalid.
        """
        return install_skill_from_archive(skill_path)

    # ------------------------------------------------------------------
    # Public API — memory management
    # ------------------------------------------------------------------

    def reload_memory(self) -> dict:
        """Reload memory data from file, forcing cache invalidation.

        Returns:
            The reloaded memory data dict.
        """
        from deerflow.agents.memory.updater import reload_memory_data

        return reload_memory_data()

    def clear_memory(self) -> dict:
        """Clear all persisted memory data."""
        from deerflow.agents.memory.updater import clear_memory_data

        return clear_memory_data()

    def create_memory_fact(self, content: str, category: str = "context", confidence: float = 0.5) -> dict:
        """Create a single fact manually."""
        from deerflow.agents.memory.updater import create_memory_fact

        return create_memory_fact(content=content, category=category, confidence=confidence)

    def delete_memory_fact(self, fact_id: str) -> dict:
        """Delete a single fact from memory by fact id."""
        from deerflow.agents.memory.updater import delete_memory_fact

        return delete_memory_fact(fact_id)

    def update_memory_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> dict:
        """Update a single fact manually, preserving omitted fields."""
        from deerflow.agents.memory.updater import update_memory_fact

        return update_memory_fact(
            fact_id=fact_id,
            content=content,
            category=category,
            confidence=confidence,
        )

    def get_memory_config(self) -> dict:
        """Get memory system configuration.

        Returns:
            Memory config dict.
        """
        from deerflow.config.memory_config import get_memory_config

        config = get_memory_config()
        return {
            "enabled": config.enabled,
            "storage_path": config.storage_path,
            "debounce_seconds": config.debounce_seconds,
            "max_facts": config.max_facts,
            "fact_confidence_threshold": config.fact_confidence_threshold,
            "injection_enabled": config.injection_enabled,
            "max_injection_tokens": config.max_injection_tokens,
        }

    def get_memory_status(self) -> dict:
        """Get memory status: config + current data.

        Returns:
            Dict with "config" and "data" keys.
        """
        return {
            "config": self.get_memory_config(),
            "data": self.get_memory(),
        }

    # ------------------------------------------------------------------
    # Public API — file uploads
    # ------------------------------------------------------------------

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict:
        """Upload local files into a thread's uploads directory.

        For PDF, PPT, Excel, and Word files, they are also converted to Markdown.

        Args:
            thread_id: Target thread ID.
            files: List of local file paths to upload.

        Returns:
            Dict with success, files, message — matching the Gateway API
            ``UploadResponse`` schema.

        Raises:
            FileNotFoundError: If any file does not exist.
            ValueError: If any supplied path exists but is not a regular file.
        """
        from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

        # Validate all files upfront to avoid partial uploads.
        resolved_files = []
        seen_names: set[str] = set()
        has_convertible_file = False
        for f in files:
            p = Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {f}")
            if not p.is_file():
                raise ValueError(f"Path is not a file: {f}")
            dest_name = claim_unique_filename(p.name, seen_names)
            resolved_files.append((p, dest_name))
            if not has_convertible_file and p.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                has_convertible_file = True

        uploads_dir = ensure_uploads_dir(thread_id)
        uploaded_files: list[dict] = []

        conversion_pool = None
        if has_convertible_file:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                conversion_pool = None
            else:
                import concurrent.futures

                # Reuse one worker when already inside an event loop to avoid
                # creating a new ThreadPoolExecutor per converted file.
                conversion_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _convert_in_thread(path: Path):
            return asyncio.run(convert_file_to_markdown(path))

        try:
            for src_path, dest_name in resolved_files:
                dest = uploads_dir / dest_name
                shutil.copy2(src_path, dest)

                info: dict[str, Any] = {
                    "filename": dest_name,
                    "size": str(dest.stat().st_size),
                    "path": str(dest),
                    "virtual_path": upload_virtual_path(dest_name),
                    "artifact_url": upload_artifact_url(thread_id, dest_name),
                }
                if dest_name != src_path.name:
                    info["original_filename"] = src_path.name

                if src_path.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                    try:
                        if conversion_pool is not None:
                            md_path = conversion_pool.submit(_convert_in_thread, dest).result()
                        else:
                            md_path = asyncio.run(convert_file_to_markdown(dest))
                    except Exception:
                        logger.warning(
                            "Failed to convert %s to markdown",
                            src_path.name,
                            exc_info=True,
                        )
                        md_path = None

                    if md_path is not None:
                        info["markdown_file"] = md_path.name
                        info["markdown_path"] = str(uploads_dir / md_path.name)
                        info["markdown_virtual_path"] = upload_virtual_path(md_path.name)
                        info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

                uploaded_files.append(info)
        finally:
            if conversion_pool is not None:
                conversion_pool.shutdown(wait=True)

        return {
            "success": True,
            "files": uploaded_files,
            "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
        }

    def list_uploads(self, thread_id: str) -> dict:
        """List files in a thread's uploads directory.

        Args:
            thread_id: Thread ID.

        Returns:
            Dict with "files" and "count" keys, matching the Gateway API
            ``list_uploaded_files`` response.
        """
        uploads_dir = get_uploads_dir(thread_id)
        result = list_files_in_dir(uploads_dir)
        return enrich_file_listing(result, thread_id)

    def delete_upload(self, thread_id: str, filename: str) -> dict:
        """Delete a file from a thread's uploads directory.

        Args:
            thread_id: Thread ID.
            filename: Filename to delete.

        Returns:
            Dict with success and message, matching the Gateway API
            ``delete_uploaded_file`` response.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If path traversal is detected.
        """
        from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS

        uploads_dir = get_uploads_dir(thread_id)
        return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)

    # ------------------------------------------------------------------
    # Public API — artifacts
    # ------------------------------------------------------------------

    def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]:
        """Read an artifact file produced by the agent.

        Args:
            thread_id: Thread ID.
            path: Virtual path (e.g. "mnt/user-data/outputs/file.txt").

        Returns:
            Tuple of (file_bytes, mime_type).

        Raises:
            FileNotFoundError: If the artifact does not exist.
            ValueError: If the path is invalid.
        """
        try:
            actual = get_paths().resolve_virtual_path(thread_id, path)
        except ValueError as exc:
            if "traversal" in str(exc):
                from deerflow.uploads.manager import PathTraversalError

                raise PathTraversalError("Path traversal detected") from exc
            raise
        if not actual.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        if not actual.is_file():
            raise ValueError(f"Path is not a file: {path}")

        mime_type, _ = mimetypes.guess_type(actual)
        return actual.read_bytes(), mime_type or "application/octet-stream"
