"""DeerFlowClient — Embedded Python client for DeerFlow agent system.

Provides direct programmatic access to DeerFlow's agent capabilities
without requiring LangGraph Server or Gateway API processes.

Usage:
    from src.client import DeerFlowClient

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
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from src.agents.lead_agent.agent import _build_middlewares
from src.agents.lead_agent.prompt import apply_prompt_template
from src.agents.thread_state import ThreadState
from src.config.app_config import get_app_config, reload_app_config
from src.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from src.config.paths import get_paths
from src.models import create_chat_model

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

        from src.client import DeerFlowClient

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
        """
        if config_path is not None:
            reload_app_config(config_path)
        self._app_config = get_app_config()

        self._checkpointer = checkpointer
        self._model_name = model_name
        self._thinking_enabled = thinking_enabled
        self._subagent_enabled = subagent_enabled
        self._plan_mode = plan_mode

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
            "middleware": _build_middlewares(config, model_name=model_name),
            "system_prompt": apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
            ),
            "state_schema": ThreadState,
        }
        checkpointer = self._checkpointer
        if checkpointer is None:
            from src.agents.checkpointer import get_checkpointer

            checkpointer = get_checkpointer()
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

        self._agent = create_agent(**kwargs)
        self._agent_config_key = key
        logger.info("Agent created: model=%s, thinking=%s", model_name, thinking_enabled)

    @staticmethod
    def _get_tools(*, model_name: str | None, subagent_enabled: bool):
        """Lazy import to avoid circular dependency at module level."""
        from src.tools import get_available_tools

        return get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    @staticmethod
    def _serialize_message(msg) -> dict:
        """Serialize a LangChain message to a plain dict for values events."""
        if isinstance(msg, AIMessage):
            d: dict[str, Any] = {"type": "ai", "content": msg.content, "id": getattr(msg, "id", None)}
            if msg.tool_calls:
                d["tool_calls"] = [{"name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in msg.tool_calls]
            return d
        if isinstance(msg, ToolMessage):
            return {
                "type": "tool",
                "content": msg.content if isinstance(msg.content, str) else str(msg.content),
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
        """Extract plain text from AIMessage content (str or list of blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block["text"])
            return "\n".join(parts) if parts else ""
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
            - type="messages-tuple"  data={"type": "ai", "content": "", "id": str, "tool_calls": [...]}
            - type="messages-tuple"  data={"type": "tool", "content": str, "name": str, "tool_call_id": str, "id": str}
            - type="end"             data={}
        """
        if thread_id is None:
            thread_id = str(uuid.uuid4())

        config = self._get_runnable_config(thread_id, **kwargs)
        self._ensure_agent(config)

        state: dict[str, Any] = {"messages": [HumanMessage(content=message)]}
        context = {"thread_id": thread_id}

        seen_ids: set[str] = set()

        for chunk in self._agent.stream(state, config=config, context=context, stream_mode="values"):
            messages = chunk.get("messages", [])

            for msg in messages:
                msg_id = getattr(msg, "id", None)
                if msg_id and msg_id in seen_ids:
                    continue
                if msg_id:
                    seen_ids.add(msg_id)

                if isinstance(msg, AIMessage):
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
                        yield StreamEvent(
                            type="messages-tuple",
                            data={"type": "ai", "content": text, "id": msg_id},
                        )

                elif isinstance(msg, ToolMessage):
                    yield StreamEvent(
                        type="messages-tuple",
                        data={
                            "type": "tool",
                            "content": msg.content if isinstance(msg.content, str) else str(msg.content),
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

        yield StreamEvent(type="end", data={})

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
        from src.skills.loader import load_skills

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
        from src.agents.memory.updater import get_memory_data

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
        from src.skills.loader import load_skills

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
        from src.skills.loader import load_skills

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
        from src.gateway.routers.skills import _validate_skill_frontmatter
        from src.skills.loader import get_skills_root_path

        path = Path(skill_path)
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {skill_path}")
        if path.suffix != ".skill":
            raise ValueError("File must have .skill extension")
        if not zipfile.is_zipfile(path):
            raise ValueError("File is not a valid ZIP archive")

        skills_root = get_skills_root_path()
        custom_dir = skills_root / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(path, "r") as zf:
                total_size = sum(info.file_size for info in zf.infolist())
                if total_size > 100 * 1024 * 1024:
                    raise ValueError("Skill archive too large when extracted (>100MB)")
                for info in zf.infolist():
                    if Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                        raise ValueError(f"Unsafe path in archive: {info.filename}")
                zf.extractall(tmp_path)
            for p in tmp_path.rglob("*"):
                if p.is_symlink():
                    p.unlink()

            items = list(tmp_path.iterdir())
            if not items:
                raise ValueError("Skill archive is empty")

            skill_dir = items[0] if len(items) == 1 and items[0].is_dir() else tmp_path

            is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
            if not is_valid:
                raise ValueError(f"Invalid skill: {message}")
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", skill_name):
                raise ValueError(f"Invalid skill name: {skill_name}")

            target = custom_dir / skill_name
            if target.exists():
                raise ValueError(f"Skill '{skill_name}' already exists")

            shutil.copytree(skill_dir, target)

        return {"success": True, "skill_name": skill_name, "message": f"Skill '{skill_name}' installed successfully"}

    # ------------------------------------------------------------------
    # Public API — memory management
    # ------------------------------------------------------------------

    def reload_memory(self) -> dict:
        """Reload memory data from file, forcing cache invalidation.

        Returns:
            The reloaded memory data dict.
        """
        from src.agents.memory.updater import reload_memory_data

        return reload_memory_data()

    def get_memory_config(self) -> dict:
        """Get memory system configuration.

        Returns:
            Memory config dict.
        """
        from src.config.memory_config import get_memory_config

        config = get_memory_config()
        return {
            "enabled": getattr(config, "enabled", True),
            "storage_path": getattr(config, "storage_path", ""),
            "debounce_seconds": getattr(config, "debounce_seconds", 30),
            "max_facts": getattr(config, "max_facts", 100),
            "fact_confidence_threshold": getattr(config, "fact_confidence_threshold", 0.7),
            "injection_enabled": getattr(config, "injection_enabled", True),
            "max_injection_tokens": getattr(config, "max_injection_tokens", 2000),
            "long_horizon_enabled": getattr(config, "long_horizon_enabled", True),
            "long_horizon_storage_path": getattr(config, "long_horizon_storage_path", ""),
            "long_horizon_max_entries": getattr(config, "long_horizon_max_entries", 500),
            "long_horizon_summary_chars": getattr(config, "long_horizon_summary_chars", 900),
            "long_horizon_injection_enabled": getattr(config, "long_horizon_injection_enabled", True),
            "long_horizon_top_k": getattr(config, "long_horizon_top_k", 5),
            "long_horizon_min_similarity": getattr(config, "long_horizon_min_similarity", 0.12),
            "long_horizon_injection_max_chars": getattr(config, "long_horizon_injection_max_chars", 2400),
            "long_horizon_embedding_dim": getattr(config, "long_horizon_embedding_dim", 256),
            "long_horizon_cross_thread_enabled": getattr(config, "long_horizon_cross_thread_enabled", True),
            "long_horizon_topic_memory_enabled": getattr(config, "long_horizon_topic_memory_enabled", True),
            "long_horizon_topic_top_k": getattr(config, "long_horizon_topic_top_k", 2),
            "long_horizon_project_memory_enabled": getattr(config, "long_horizon_project_memory_enabled", True),
            "long_horizon_project_top_k": getattr(config, "long_horizon_project_top_k", 2),
            "long_horizon_current_thread_boost": getattr(config, "long_horizon_current_thread_boost", 0.08),
            "long_horizon_project_boost": getattr(config, "long_horizon_project_boost", 0.12),
            "long_horizon_topic_overlap_boost": getattr(config, "long_horizon_topic_overlap_boost", 0.03),
            "long_horizon_hypothesis_memory_enabled": getattr(config, "long_horizon_hypothesis_memory_enabled", True),
            "long_horizon_hypothesis_top_k": getattr(config, "long_horizon_hypothesis_top_k", 2),
            "long_horizon_hypothesis_max_entries": getattr(config, "long_horizon_hypothesis_max_entries", 400),
            "long_horizon_hypothesis_failure_boost": getattr(config, "long_horizon_hypothesis_failure_boost", 0.08),
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

    @staticmethod
    def _get_uploads_dir(thread_id: str) -> Path:
        """Get (and create) the uploads directory for a thread."""
        base = get_paths().sandbox_uploads_dir(thread_id)
        base.mkdir(parents=True, exist_ok=True)
        return base

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
        """
        from src.gateway.routers.uploads import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

        # Validate all files upfront to avoid partial uploads.
        resolved_files = []
        for f in files:
            p = Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {f}")
            resolved_files.append(p)

        uploads_dir = self._get_uploads_dir(thread_id)
        uploaded_files: list[dict] = []

        for src_path in resolved_files:
            dest = uploads_dir / src_path.name
            shutil.copy2(src_path, dest)

            info: dict[str, Any] = {
                "filename": src_path.name,
                "size": str(dest.stat().st_size),
                "path": str(dest),
                "virtual_path": f"/mnt/user-data/uploads/{src_path.name}",
                "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{src_path.name}",
            }

            if src_path.suffix.lower() in CONVERTIBLE_EXTENSIONS:
                try:
                    try:
                        asyncio.get_running_loop()
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            md_path = pool.submit(lambda: asyncio.run(convert_file_to_markdown(dest))).result()
                    except RuntimeError:
                        md_path = asyncio.run(convert_file_to_markdown(dest))
                except Exception:
                    logger.warning("Failed to convert %s to markdown", src_path.name, exc_info=True)
                    md_path = None

                if md_path is not None:
                    info["markdown_file"] = md_path.name
                    info["markdown_virtual_path"] = f"/mnt/user-data/uploads/{md_path.name}"
                    info["markdown_artifact_url"] = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_path.name}"

            uploaded_files.append(info)

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
        uploads_dir = self._get_uploads_dir(thread_id)
        if not uploads_dir.exists():
            return {"files": [], "count": 0}

        files = []
        for fp in sorted(uploads_dir.iterdir()):
            if fp.is_file():
                stat = fp.stat()
                files.append(
                    {
                        "filename": fp.name,
                        "size": str(stat.st_size),
                        "path": str(fp),
                        "virtual_path": f"/mnt/user-data/uploads/{fp.name}",
                        "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{fp.name}",
                        "extension": fp.suffix,
                        "modified": stat.st_mtime,
                    }
                )
        return {"files": files, "count": len(files)}

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
        uploads_dir = self._get_uploads_dir(thread_id)
        file_path = (uploads_dir / filename).resolve()

        try:
            file_path.relative_to(uploads_dir.resolve())
        except ValueError as exc:
            raise PermissionError("Access denied: path traversal detected") from exc

        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {filename}")

        file_path.unlink()
        return {"success": True, "message": f"Deleted {filename}"}

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
        virtual_prefix = "mnt/user-data"
        clean_path = path.lstrip("/")
        if not clean_path.startswith(virtual_prefix):
            raise ValueError(f"Path must start with /{virtual_prefix}")

        relative = clean_path[len(virtual_prefix) :].lstrip("/")
        base_dir = get_paths().sandbox_user_data_dir(thread_id)
        actual = (base_dir / relative).resolve()

        try:
            actual.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise PermissionError("Access denied: path traversal detected") from exc
        if not actual.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        if not actual.is_file():
            raise ValueError(f"Path is not a file: {path}")

        mime_type, _ = mimetypes.guess_type(actual)
        return actual.read_bytes(), mime_type or "application/octet-stream"

    def export_image_report_pdf(
        self,
        thread_id: str,
        *,
        index_path: str | None = None,
        index_payload: dict[str, Any] | None = None,
        output_filename: str | None = None,
    ) -> dict:
        """Export ImageReport artifacts to an audit-friendly PDF.

        Args:
            thread_id: Thread ID.
            index_path: Optional virtual path to ImageReport index artifact.
            index_payload: Optional inline index payload when index_path is unavailable.
            output_filename: Optional filename for the generated PDF.

        Returns:
            Dict with ``pdf_path`` key, matching Gateway ``ImageReportPdfResponse``.

        Raises:
            ValueError: If input payload/path is invalid.
            FileNotFoundError: If ``index_path`` does not exist.
        """
        from src.config.scientific_vision_config import get_scientific_vision_config
        from src.gateway.path_utils import resolve_thread_virtual_path
        from src.utils.image_report_pdf import generate_image_report_pdf

        resolved_index_payload: dict[str, Any] | None = None
        if index_path:
            physical = resolve_thread_virtual_path(thread_id, index_path)
            resolved_index_payload = json.loads(physical.read_text(encoding="utf-8"))
            if not isinstance(resolved_index_payload, dict):
                raise ValueError("index payload must be an object")

        if resolved_index_payload is None:
            if index_payload is None:
                raise ValueError("Either index_path or index_payload must be provided")
            if not isinstance(index_payload, dict):
                raise ValueError("index_payload must be an object")
            resolved_index_payload = index_payload

        cfg = get_scientific_vision_config()
        pdf_path = generate_image_report_pdf(
            thread_id=thread_id,
            index_payload=resolved_index_payload,
            artifact_subdir=cfg.artifact_subdir,
            output_filename=output_filename,
            index_virtual_path=index_path,
        )
        return {"pdf_path": pdf_path}

    def export_latex_diagnostics_markdown(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        project_id: str | None = None,
        section_id: str | None = None,
        source_path: str | None = None,
        compile_status: str | None = None,
        compiler: str | None = None,
        engine_requested: str | None = None,
        compile_log_path: str | None = None,
        failure_reason: str | None = None,
        issue_clusters: list[dict[str, Any]] | None = None,
        error_preview: list[str] | None = None,
        warning_preview: list[str] | None = None,
        raw_key_log: str | None = None,
        output_filename: str | None = None,
    ) -> dict:
        """Persist LaTeX troubleshooting diagnostics as a markdown artifact."""
        from src.gateway.routers.reports import (
            LatexDiagnosticsMarkdownRequest,
            _build_latex_diagnostics_markdown,
            _markdown_outputs_virtual_path,
        )

        request = LatexDiagnosticsMarkdownRequest(
            title=title,
            project_id=project_id,
            section_id=section_id,
            source_path=source_path,
            compile_status=compile_status,
            compiler=compiler,
            engine_requested=engine_requested,
            compile_log_path=compile_log_path,
            failure_reason=failure_reason,
            issue_clusters=issue_clusters or [],
            error_preview=error_preview or [],
            warning_preview=warning_preview or [],
            raw_key_log=raw_key_log,
            output_filename=output_filename,
        )

        outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        reports_rel_dir = Path("research-writing") / "latex" / "reports"
        reports_physical_dir = outputs_dir / reports_rel_dir
        reports_physical_dir.mkdir(parents=True, exist_ok=True)
        if request.output_filename:
            filename = request.output_filename
        else:
            filename = f"latex-diagnostics-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.md"

        target = reports_physical_dir / filename
        markdown = _build_latex_diagnostics_markdown(request, thread_id=thread_id)
        target.write_text(markdown, encoding="utf-8")

        report_path = _markdown_outputs_virtual_path(reports_rel_dir / filename)
        return {"report_path": report_path}

    # ------------------------------------------------------------------
    # Public API — research writing / academic eval
    # ------------------------------------------------------------------

    def research_upsert_project(self, thread_id: str, project: dict[str, Any]) -> dict:
        """Upsert a structured research project."""
        from src.research_writing.project_state import ResearchProject
        from src.research_writing.runtime_service import upsert_project

        parsed = ResearchProject.model_validate(project)
        saved = upsert_project(thread_id, parsed)
        return {"project": saved.model_dump()}

    def research_get_project(self, thread_id: str, project_id: str) -> dict | None:
        """Get one structured research project by id."""
        from src.research_writing.runtime_service import get_project

        project = get_project(thread_id, project_id)
        if project is None:
            return None
        return {"project": project.model_dump()}

    def research_list_projects(self, thread_id: str) -> dict:
        """List structured research projects for a thread."""
        from src.research_writing.runtime_service import list_projects

        projects = list_projects(thread_id)
        return {"projects": [p.model_dump() for p in projects]}

    def research_ingest_fulltext(self, thread_id: str, *, source: str, external_id: str, persist: bool = True) -> dict:
        """Ingest literature and extract structured evidence units."""
        from src.research_writing.runtime_service import ingest_fulltext_evidence

        return ingest_fulltext_evidence(thread_id, source=source, external_id=external_id, persist=persist)

    def research_compile_section(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
        mode: str = "strict",
        auto_peer_review: bool = True,
        auto_hypothesis: bool = True,
        peer_review_max_rounds: int = 3,
        max_hypotheses: int = 5,
        narrative_style: str = "auto",
        narrative_max_templates: int | None = None,
        narrative_evidence_density: str | None = None,
        narrative_auto_by_section_type: bool = True,
        narrative_paragraph_tones: list[str] | None = None,
        narrative_paragraph_evidence_densities: list[str] | None = None,
        journal_style_enabled: bool | None = None,
        journal_style_force_refresh: bool = False,
        journal_style_sample_size: int | None = None,
        journal_style_recent_year_window: int | None = None,
        policy_snapshot_auto_adjust_narrative: bool = True,
        narrative_self_question_rounds: int = 3,
        narrative_include_storyboard: bool = True,
        reviewer2_styles: list[str] | None = None,
        peer_review_ab_variant: str | None = None,
    ) -> dict:
        """Compile a section with grounding constraints and optional auto-debate."""
        from src.research_writing.runtime_service import compile_project_section

        return compile_project_section(
            thread_id,
            project_id=project_id,
            section_id=section_id,
            mode=mode,
            auto_peer_review=auto_peer_review,
            auto_hypothesis=auto_hypothesis,
            peer_review_max_rounds=peer_review_max_rounds,
            max_hypotheses=max_hypotheses,
            narrative_style=narrative_style,
            narrative_max_templates=narrative_max_templates,
            narrative_evidence_density=narrative_evidence_density,
            narrative_auto_by_section_type=narrative_auto_by_section_type,
            narrative_paragraph_tones=narrative_paragraph_tones,
            narrative_paragraph_evidence_densities=narrative_paragraph_evidence_densities,
            journal_style_enabled=journal_style_enabled,
            journal_style_force_refresh=journal_style_force_refresh,
            journal_style_sample_size=journal_style_sample_size,
            journal_style_recent_year_window=journal_style_recent_year_window,
            policy_snapshot_auto_adjust_narrative=policy_snapshot_auto_adjust_narrative,
            narrative_self_question_rounds=narrative_self_question_rounds,
            narrative_include_storyboard=narrative_include_storyboard,
            reviewer2_styles=reviewer2_styles,
            peer_review_ab_variant=peer_review_ab_variant,
        )

    def research_plan_narrative(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
        self_question_rounds: int = 3,
        include_storyboard: bool = True,
    ) -> dict:
        """Generate pre-writing narrative plan for one section."""
        from src.research_writing.runtime_service import plan_project_section_narrative

        return plan_project_section_narrative(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            self_question_rounds=self_question_rounds,
            include_storyboard=include_storyboard,
        )

    def research_run_agentic_graph(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str | None = None,
        seed_idea: str | None = None,
        max_rounds: int = 3,
    ) -> dict:
        """Run non-linear blackboard orchestration among specialist research agents."""
        from src.research_writing.runtime_service import run_agentic_research_graph

        return run_agentic_research_graph(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            seed_idea=seed_idea,
            max_rounds=max_rounds,
        )

    def research_list_section_versions(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
        limit: int = 20,
    ) -> dict:
        """List audit history of section versions."""
        from src.research_writing.runtime_service import list_section_versions

        return list_section_versions(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            limit=limit,
        )

    def research_rollback_section_to_version(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
        version_id: str,
    ) -> dict:
        """Rollback section content to one historical version id."""
        from src.research_writing.runtime_service import rollback_section_to_version

        return rollback_section_to_version(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            version_id=version_id,
        )

    def research_get_section_traceability(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
    ) -> dict:
        """Get sentence-level claim/evidence/figure traceability index."""
        from src.research_writing.runtime_service import get_section_traceability

        return get_section_traceability(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )

    def research_get_capability_catalog(self, thread_id: str) -> dict:
        """Get capability catalog (capability list -> metrics -> failure modes)."""
        from src.research_writing.runtime_service import get_capability_catalog

        return get_capability_catalog(thread_id)

    def research_assess_capabilities(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str | None = None,
    ) -> dict:
        """Assess capability scorecards for one project or project section."""
        from src.research_writing.runtime_service import assess_project_capabilities

        return assess_project_capabilities(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )

    def research_compile_latex(
        self,
        thread_id: str,
        *,
        project_id: str | None = None,
        section_ids: list[str] | None = None,
        markdown_text: str | None = None,
        title: str | None = None,
        abstract_text: str | None = None,
        authors: list[str] | None = None,
        compile_pdf: bool | None = None,
        engine: str | None = None,
        output_name: str | None = None,
    ) -> dict:
        """Build native `.tex` manuscript and optional PDF from project or markdown."""
        from src.research_writing.runtime_service import build_latex_manuscript

        return build_latex_manuscript(
            thread_id=thread_id,
            project_id=project_id,
            section_ids=section_ids,
            markdown_text=markdown_text,
            title=title,
            abstract_text=abstract_text,
            authors=authors,
            compile_pdf=compile_pdf,
            engine=engine,
            output_name=output_name,
        )

    def research_simulate_review(
        self,
        thread_id: str,
        *,
        venue_name: str,
        manuscript_text: str,
        evidence_map: dict[str, list[str]] | None = None,
        section_map: dict[str, list[str]] | None = None,
    ) -> dict:
        """Run venue-calibrated reviewer simulation and rebuttal planning."""
        from src.research_writing.runtime_service import simulate_review_and_plan

        return simulate_review_and_plan(
            thread_id=thread_id,
            venue_name=venue_name,
            manuscript_text=manuscript_text,
            evidence_map=evidence_map,
            section_map=section_map,
        )

    def research_simulate_peer_review_loop(
        self,
        thread_id: str,
        *,
        venue_name: str,
        manuscript_text: str,
        section_id: str | None = None,
        max_rounds: int = 3,
        reviewer2_styles: list[str] | None = None,
        peer_review_ab_variant: str | None = None,
    ) -> dict:
        """Run multi-agent peer-review loop (Reviewer/Author/Area Chair)."""
        from src.research_writing.runtime_service import simulate_peer_review_cycle

        return simulate_peer_review_cycle(
            thread_id=thread_id,
            venue_name=venue_name,
            manuscript_text=manuscript_text,
            section_id=section_id,
            max_rounds=max_rounds,
            reviewer2_styles=reviewer2_styles,
            peer_review_ab_variant=peer_review_ab_variant,
        )

    def research_get_peer_review_ab_metrics(self, thread_id: str) -> dict:
        """Get thread-level peer-review A/B aggregation metrics and strategy snapshot."""
        from src.research_writing.runtime_service import get_peer_review_ab_metrics

        return get_peer_review_ab_metrics(thread_id=thread_id)

    def research_get_engineering_gates_metrics(
        self,
        thread_id: str,
        *,
        project_id: str | None = None,
        run_limit: int = 60,
        max_constraint_violation_rate: float = 0.2,
        max_safety_valve_trigger_rate: float = 0.4,
        max_hitl_block_rate: float = 0.35,
        min_traceability_coverage_rate: float = 0.8,
        min_delivery_completeness_rate: float = 1.0,
        min_latex_success_rate: float = 0.75,
    ) -> dict:
        """Get engineering gates trends and threshold alerts for thread/project."""
        from src.research_writing.runtime_service import get_engineering_gates_metrics

        return get_engineering_gates_metrics(
            thread_id=thread_id,
            project_id=project_id,
            run_limit=run_limit,
            max_constraint_violation_rate=max_constraint_violation_rate,
            max_safety_valve_trigger_rate=max_safety_valve_trigger_rate,
            max_hitl_block_rate=max_hitl_block_rate,
            min_traceability_coverage_rate=min_traceability_coverage_rate,
            min_delivery_completeness_rate=min_delivery_completeness_rate,
            min_latex_success_rate=min_latex_success_rate,
        )

    def research_run_self_play_training(
        self,
        thread_id: str,
        *,
        episodes: list[dict[str, Any]],
        max_rounds: int = 3,
        default_venue_name: str = "NeurIPS",
        default_section_id: str | None = "discussion",
        run_name: str = "peer-self-play",
    ) -> dict:
        """Run multi-agent self-play and mine hard negatives."""
        from src.research_writing.runtime_service import run_peer_self_play_training

        return run_peer_self_play_training(
            thread_id=thread_id,
            episodes=episodes,
            max_rounds=max_rounds,
            default_venue_name=default_venue_name,
            default_section_id=default_section_id,
            run_name=run_name,
        )

    def research_generate_hypotheses(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str | None = None,
        max_hypotheses: int = 5,
    ) -> dict:
        """Generate ranked hypotheses from structured evidence/literature/facts."""
        from src.research_writing.runtime_service import generate_project_hypotheses

        return generate_project_hypotheses(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            max_hypotheses=max_hypotheses,
        )

    def research_get_hitl_decisions(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str | None = None,
    ) -> dict:
        """Get HITL approve/reject decisions persisted in project metadata."""
        from src.research_writing.runtime_service import get_project_hitl_decisions

        return get_project_hitl_decisions(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )

    def research_upsert_hitl_decisions(
        self,
        thread_id: str,
        *,
        project_id: str,
        decisions: list[dict[str, Any]],
        section_id: str | None = None,
    ) -> dict:
        """Upsert HITL approve/reject decisions into project metadata."""
        from src.research_writing.project_state import HitlDecision
        from src.research_writing.runtime_service import upsert_project_hitl_decisions

        parsed_decisions = [HitlDecision.model_validate(item) for item in decisions]
        return upsert_project_hitl_decisions(
            thread_id=thread_id,
            project_id=project_id,
            decisions=parsed_decisions,
            section_id=section_id,
        )

    def research_get_policy_snapshot(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str | None = None,
    ) -> dict:
        """Get policy-learning snapshot derived from HITL decisions."""
        from src.research_writing.runtime_service import get_project_policy_snapshot

        return get_project_policy_snapshot(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )

    def research_audit_compliance(
        self,
        thread_id: str,
        *,
        project_id: str,
        section_id: str,
        manuscript_text: str | None = None,
    ) -> dict:
        """Run ethics/compliance audit for one project section."""
        from src.research_writing.runtime_service import audit_project_section_compliance

        return audit_project_section_compliance(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            manuscript_text=manuscript_text,
        )

    def research_get_academic_leaderboard(self, thread_id: str) -> dict:
        """Get weekly discipline/venue leaderboard."""
        from src.research_writing.runtime_service import get_weekly_academic_leaderboard

        return get_weekly_academic_leaderboard(thread_id)

    def research_evaluate_academic(
        self,
        thread_id: str,
        *,
        cases: list[dict[str, Any]] | None = None,
        dataset_name: str | None = None,
        artifact_name: str = "academic-eval",
        model_label: str = "deerflow-runtime",
    ) -> dict:
        """Evaluate academic quality metrics for provided eval cases."""
        from src.evals.academic.loader import load_builtin_eval_cases
        from src.evals.academic.schemas import AcademicEvalCase
        from src.research_writing.runtime_service import evaluate_academic_and_persist

        if cases is not None:
            parsed = [AcademicEvalCase.model_validate(c) for c in cases]
        elif dataset_name:
            parsed = load_builtin_eval_cases(dataset_name)
        else:
            raise ValueError("Either cases or dataset_name must be provided")
        return evaluate_academic_and_persist(
            thread_id,
            cases=parsed,
            name=artifact_name,
            model_label=model_label,
            dataset_name=dataset_name,
        )

    def research_import_academic_dataset(
        self,
        thread_id: str,
        *,
        source_dataset_path: str,
        dataset_name: str,
        dataset_version: str = "v1",
        benchmark_split: str | None = None,
        source_name: str | None = None,
        anonymize: bool = True,
        strict: bool = False,
        autofix: bool = False,
        autofix_level: str = "balanced",
    ) -> dict:
        """Import raw accept/reject dataset into normalized, versioned eval dataset."""
        from src.research_writing.runtime_service import import_academic_eval_dataset

        source_file = get_paths().resolve_virtual_path(thread_id, source_dataset_path)
        return import_academic_eval_dataset(
            thread_id=thread_id,
            source_dataset_file=source_file,
            source_dataset_virtual_path=source_dataset_path,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            benchmark_split=benchmark_split,
            source_name=source_name,
            anonymize=anonymize,
            strict=strict,
            autofix=autofix,
            autofix_level=autofix_level,
        )
