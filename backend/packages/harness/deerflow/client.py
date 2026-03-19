"""DeerFlowClient — Embedded Python 客户端 for DeerFlow 代理 系统.

Provides direct programmatic access to DeerFlow's 代理 capabilities
without requiring LangGraph Server or Gateway API processes.

Usage:
    from deerflow.客户端 import DeerFlowClient

    客户端 = DeerFlowClient()
    响应 = 客户端.聊天("Analyze this paper for me", thread_id="my-线程")
    print(响应)

    #    Streaming


    for event in 客户端.stream("hello"):
        print(event)
"""

import asyncio
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from deerflow.agents.lead_agent.agent import _build_middlewares
from deerflow.agents.lead_agent.prompt import apply_prompt_template
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import get_app_config, reload_app_config
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from deerflow.config.paths import get_paths
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """A single event from the streaming 代理 响应.

    Event types align with the LangGraph SSE protocol:
        - ``"values"``: Full 状态 snapshot (title, messages, artifacts).
        - ``"messages-tuple"``: Per-消息 更新 (AI text, 工具 calls, 工具 results).
        - ``"end"``: Stream finished.

    Attributes:
        类型: Event 类型.
        数据: Event payload. Contents vary by 类型.
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


class DeerFlowClient:
    """Embedded Python 客户端 for DeerFlow 代理 系统.

    Provides direct programmatic access to DeerFlow's 代理 capabilities
    without requiring LangGraph Server or Gateway API processes.

    Note:
        Multi-turn conversations require a ``checkpointer``. Without one,
        each ``stream()`` / ``聊天()`` call is stateless — ``thread_id``
        is only used for 文件 isolation (uploads / artifacts).

        The 系统 提示词 (including date, 内存, and skills context) is
        generated when the internal 代理 is 第一 created and cached until
        the configuration 键 changes. Call :meth:`reset_agent` to force
        a refresh in long-running processes.

    Example::

        from deerflow.客户端 import DeerFlowClient

        客户端 = DeerFlowClient()

        #    Simple one-shot


        print(客户端.聊天("hello"))

        #    Streaming


        for event in 客户端.stream("hello"):
            print(event.类型, event.数据)

        #    Configuration queries


        print(客户端.list_models())
        print(客户端.list_skills())
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
        """Initialize the 客户端.

        Loads configuration but defers 代理 creation to 第一 use.

        Args:
            config_path: Path to 配置.yaml. Uses 默认 resolution if None.
            checkpointer: LangGraph checkpointer instance for 状态 persistence.
                Required for multi-turn conversations on the same thread_id.
                Without a checkpointer, each call is stateless.
            model_name: Override the 默认 模型 名称 from 配置.
            thinking_enabled: Enable 模型's extended thinking.
            subagent_enabled: Enable subagent delegation.
            plan_mode: Enable TodoList 中间件 for plan mode.
        """
        if config_path is not None:
            reload_app_config(config_path)
        self._app_config = get_app_config()

        self._checkpointer = checkpointer
        self._model_name = model_name
        self._thinking_enabled = thinking_enabled
        self._subagent_enabled = subagent_enabled
        self._plan_mode = plan_mode

        #    Lazy 代理 — created on 第一 call, recreated when 配置 changes.


        self._agent = None
        self._agent_config_key: tuple | None = None

    def reset_agent(self) -> None:
        """Force the internal 代理 to be recreated on the 下一个 call.

        Use this after external changes (e.g. 内存 updates, skill
        installations) that should be reflected in the 系统 提示词
        or 工具 集合.
        """
        self._agent = None
        self._agent_config_key = None

    #    ------------------------------------------------------------------


    #    Internal helpers


    #    ------------------------------------------------------------------



    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        """Write JSON to *路径* atomically (temp 文件 + replace)."""
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
        """Build a RunnableConfig for 代理 invocation."""
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
        """Create (or recreate) the 代理 when 配置-dependent params change."""
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
            from deerflow.agents.checkpointer import get_checkpointer

            checkpointer = get_checkpointer()
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer

        self._agent = create_agent(**kwargs)
        self._agent_config_key = key
        logger.info("Agent created: model=%s, thinking=%s", model_name, thinking_enabled)

    @staticmethod
    def _get_tools(*, model_name: str | None, subagent_enabled: bool):
        """Lazy import to avoid circular dependency at 模块 level."""
        from deerflow.tools import get_available_tools

        return get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    @staticmethod
    def _serialize_message(msg) -> dict:
        """Serialize a LangChain 消息 to a plain 字典 for values events."""
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
        """Extract plain text from AIMessage content (str or 列表 of blocks)."""
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

    #    ------------------------------------------------------------------


    #    Public API — conversation


    #    ------------------------------------------------------------------



    def stream(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        **kwargs,
    ) -> Generator[StreamEvent, None, None]:
        """Stream a conversation turn, yielding events incrementally.

        Each call sends one 用户 消息 and yields events until the 代理
        finishes its turn. A ``checkpointer`` must be provided at 初始化 time
        for multi-turn context to be preserved across calls.

        Event types align with the LangGraph SSE protocol so that
        consumers can switch between HTTP streaming and embedded mode
        without changing their event-handling logic.

        Args:
            消息: 用户 消息 text.
            thread_id: 线程 ID for conversation context. Auto-generated if None.
            **kwargs: Override 客户端 defaults (model_name, thinking_enabled,
                plan_mode, subagent_enabled, recursion_limit).

        Yields:
            StreamEvent with one of:
            - 类型="values"          数据={"title": str|None, "messages": [...], "artifacts": [...]}
            - 类型="messages-tuple"  数据={"类型": "ai", "content": str, "标识符": str}
            - 类型="messages-tuple"  数据={"类型": "ai", "content": "", "标识符": str, "tool_calls": [...]}
            - 类型="messages-tuple"  数据={"类型": "工具", "content": str, "名称": str, "tool_call_id": str, "标识符": str}
            - 类型="end"             数据={}
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

            #    Emit a values event 对于 each 状态 snapshot


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
        """Send a 消息 and 返回 the final text 响应.

        Convenience wrapper around :meth:`stream` that returns only the
        **最后** AI text from ``messages-tuple`` events. If the 代理 emits
        multiple text segments in one turn, intermediate segments are
        discarded. Use :meth:`stream` directly to capture all events.

        Args:
            消息: 用户 消息 text.
            thread_id: 线程 ID for conversation context. Auto-generated if None.
            **kwargs: Override 客户端 defaults (same as stream()).

        Returns:
            The 最后 AI 消息 text, or empty 字符串 if no 响应.
        """
        last_text = ""
        for event in self.stream(message, thread_id=thread_id, **kwargs):
            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                content = event.data.get("content", "")
                if content:
                    last_text = content
        return last_text

    #    ------------------------------------------------------------------


    #    Public API — configuration queries


    #    ------------------------------------------------------------------



    def list_models(self) -> dict:
        """List 可用的 models from configuration.

        Returns:
            Dict with "models" 键 containing 列表 of 模型 信息 dicts,
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
        """List 可用的 skills.

        Args:
            enabled_only: If True, only 返回 已启用 skills.

        Returns:
            Dict with "skills" 键 containing 列表 of skill 信息 dicts,
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
        """Get 当前 内存 数据.

        Returns:
            内存 数据 字典 (see src/agents/内存/updater.py for structure).
        """
        from deerflow.agents.memory.updater import get_memory_data

        return get_memory_data()

    def get_model(self, name: str) -> dict | None:
        """Get a specific 模型's configuration by 名称.

        Args:
            名称: 模型 名称.

        Returns:
            模型 信息 字典 matching the Gateway API ``ModelResponse``
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

    #    ------------------------------------------------------------------


    #    Public API — MCP configuration


    #    ------------------------------------------------------------------



    def get_mcp_config(self) -> dict:
        """Get MCP 服务器 configurations.

        Returns:
            Dict with "mcp_servers" 键 mapping 服务器 名称 to 配置,
            matching the Gateway API ``McpConfigResponse`` schema.
        """
        config = get_extensions_config()
        return {"mcp_servers": {name: server.model_dump() for name, server in config.mcp_servers.items()}}

    def update_mcp_config(self, mcp_servers: dict[str, dict]) -> dict:
        """Update MCP 服务器 configurations.

        Writes to extensions_config.json and reloads the 缓存.

        Args:
            mcp_servers: Dict mapping 服务器 名称 to 配置 字典.
                Each 值 should contain keys like 已启用, 类型, command, args, env, 链接, etc.

        Returns:
            Dict with "mcp_servers" 键, matching the Gateway API
            ``McpConfigResponse`` schema.

        Raises:
            OSError: If the 配置 文件 cannot be written.
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

    #    ------------------------------------------------------------------


    #    Public API — skills management


    #    ------------------------------------------------------------------



    def get_skill(self, name: str) -> dict | None:
        """Get a specific skill by 名称.

        Args:
            名称: Skill 名称.

        Returns:
            Skill 信息 字典, or None if not found.
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
        """Update a skill's 已启用 status.

        Args:
            名称: Skill 名称.
            已启用: New 已启用 status.

        Returns:
            Updated skill 信息 字典.

        Raises:
            ValueError: If the skill is not found.
            OSError: If the 配置 文件 cannot be written.
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
            skill_path: Path to the .skill 文件.

        Returns:
            Dict with 成功, skill_name, 消息.

        Raises:
            FileNotFoundError: If the 文件 does not exist.
            ValueError: If the 文件 is 无效.
        """
        from deerflow.skills.loader import get_skills_root_path
        from deerflow.skills.validation import _validate_skill_frontmatter

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

    #    ------------------------------------------------------------------


    #    Public API — 内存 management


    #    ------------------------------------------------------------------



    def reload_memory(self) -> dict:
        """Reload 内存 数据 from 文件, forcing 缓存 invalidation.

        Returns:
            The reloaded 内存 数据 字典.
        """
        from deerflow.agents.memory.updater import reload_memory_data

        return reload_memory_data()

    def get_memory_config(self) -> dict:
        """Get 内存 系统 configuration.

        Returns:
            内存 配置 字典.
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
        """Get 内存 status: 配置 + 当前 数据.

        Returns:
            Dict with "配置" and "数据" keys.
        """
        return {
            "config": self.get_memory_config(),
            "data": self.get_memory(),
        }

    #    ------------------------------------------------------------------


    #    Public API — 文件 uploads


    #    ------------------------------------------------------------------



    @staticmethod
    def _get_uploads_dir(thread_id: str) -> Path:
        """Get (and 创建) the uploads 目录 for a 线程."""
        base = get_paths().sandbox_uploads_dir(thread_id)
        base.mkdir(parents=True, exist_ok=True)
        return base

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict:
        """Upload local files into a 线程's uploads 目录.

        For PDF, PPT, Excel, and Word files, they are also converted to Markdown.

        Args:
            thread_id: Target 线程 ID.
            files: List of local 文件 paths to upload.

        Returns:
            Dict with 成功, files, 消息 — matching the Gateway API
            ``UploadResponse`` schema.

        Raises:
            FileNotFoundError: If any 文件 does not exist.
            ValueError: If any supplied 路径 exists but is not a regular 文件.
        """
        from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

        #    Validate all files upfront to avoid partial uploads.


        resolved_files = []
        convertible_extensions = {ext.lower() for ext in CONVERTIBLE_EXTENSIONS}
        has_convertible_file = False
        for f in files:
            p = Path(f)
            if not p.exists():
                raise FileNotFoundError(f"File not found: {f}")
            if not p.is_file():
                raise ValueError(f"Path is not a file: {f}")
            resolved_files.append(p)
            if not has_convertible_file and p.suffix.lower() in convertible_extensions:
                has_convertible_file = True

        uploads_dir = self._get_uploads_dir(thread_id)
        uploaded_files: list[dict] = []

        conversion_pool = None
        if has_convertible_file:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                conversion_pool = None
            else:
                import concurrent.futures

                #    Reuse one worker when already inside an event 循环 to avoid


                #    creating a 新建 ThreadPoolExecutor per converted 文件.


                conversion_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _convert_in_thread(path: Path):
            return asyncio.run(convert_file_to_markdown(path))

        try:
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

                if src_path.suffix.lower() in convertible_extensions:
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
                        info["markdown_virtual_path"] = f"/mnt/user-data/uploads/{md_path.name}"
                        info["markdown_artifact_url"] = f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{md_path.name}"

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
        """List files in a 线程's uploads 目录.

        Args:
            thread_id: 线程 ID.

        Returns:
            Dict with "files" and "计数" keys, matching the Gateway API
            ``list_uploaded_files`` 响应.
        """
        uploads_dir = self._get_uploads_dir(thread_id)
        if not uploads_dir.exists():
            return {"files": [], "count": 0}

        files = []
        with os.scandir(uploads_dir) as entries:
            file_entries = [entry for entry in entries if entry.is_file()]

        for entry in sorted(file_entries, key=lambda item: item.name):
            stat = entry.stat()
            filename = entry.name
            files.append(
                {
                    "filename": filename,
                    "size": str(stat.st_size),
                    "path": str(Path(entry.path)),
                    "virtual_path": f"/mnt/user-data/uploads/{filename}",
                    "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{filename}",
                    "extension": Path(filename).suffix,
                    "modified": stat.st_mtime,
                }
            )
        return {"files": files, "count": len(files)}

    def delete_upload(self, thread_id: str, filename: str) -> dict:
        """Delete a 文件 from a 线程's uploads 目录.

        Args:
            thread_id: 线程 ID.
            filename: Filename to 删除.

        Returns:
            Dict with 成功 and 消息, matching the Gateway API
            ``delete_uploaded_file`` 响应.

        Raises:
            FileNotFoundError: If the 文件 does not exist.
            PermissionError: If 路径 traversal is detected.
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

    #    ------------------------------------------------------------------


    #    Public API — artifacts


    #    ------------------------------------------------------------------



    def get_artifact(self, thread_id: str, path: str) -> tuple[bytes, str]:
        """Read an artifact 文件 produced by the 代理.

        Args:
            thread_id: 线程 ID.
            路径: Virtual 路径 (e.g. "mnt/用户-数据/outputs/文件.txt").

        Returns:
            Tuple of (file_bytes, mime_type).

        Raises:
            FileNotFoundError: If the artifact does not exist.
            ValueError: If the 路径 is 无效.
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
