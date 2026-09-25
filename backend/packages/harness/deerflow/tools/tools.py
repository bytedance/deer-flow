import copy
import logging
import threading

from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.constants import CONVERSATION_TOOL_USE
from deerflow.mcp.tasks.runtime import is_mcp_task_runtime_available
from deerflow.reflection import resolve_variable
from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.subagents.batch_runtime import is_subagent_batch_runtime_available
from deerflow.tools.builtins import (
    ask_clarification_tool,
    batch_status,
    batch_task,
    cancel_background_task,
    cancel_batch,
    list_background_tasks,
    list_uploaded_files,
    present_file_tool,
    review_skill_package,
    task_tool,
    view_image_tool,
)
from deerflow.tools.mcp_metadata import tag_mcp_tool
from deerflow.tools.sync import make_sync_tool_wrapper

logger = logging.getLogger(__name__)

BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
    review_skill_package,
]

SUBAGENT_TOOLS = [
    task_tool,
    # task_status_tool is no longer exposed to LLM (backend handles polling internally)
]


def _is_host_bash_tool(tool: object) -> bool:
    """Return True if the tool config represents a host-bash execution surface."""
    group = getattr(tool, "group", None)
    use = getattr(tool, "use", None)
    if group == "bash":
        return True
    if use == "deerflow.sandbox.tools:bash_tool":
        return True
    return False


_sync_invocable_tool_lock = threading.Lock()


def _ensure_sync_invocable_tool(tool: BaseTool) -> BaseTool:
    """Attach a sync wrapper to async-only tools used by sync agent callers.

    The wrapped objects are process-wide singletons (BUILTIN_TOOLS /
    SUBAGENT_TOOLS / MCP cache entries) and tool assembly may now run on
    worker threads concurrently; double-checked locking makes the in-place
    ``tool.func`` wrap explicitly single-shot instead of incidental.
    """
    if getattr(tool, "func", None) is not None or getattr(tool, "coroutine", None) is None:
        return tool
    with _sync_invocable_tool_lock:
        if getattr(tool, "func", None) is None:
            tool.func = make_sync_tool_wrapper(tool.coroutine, tool.name)
    return tool


def _extract_max_tokens(model_config: object | None) -> int | None:
    """Safely extract a positive integer max_tokens from a model config object.

    Handles ModelConfig (where max_tokens may be stored as an extra dynamic field),
    dicts, SimpleNamespace, or test stubs. Rejects booleans, mocks, non-numeric
    values, negative numbers, zero, and None.
    """
    if model_config is None:
        return None
    raw = model_config.get("max_tokens") if isinstance(model_config, dict) else getattr(model_config, "max_tokens", None)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _clone_tool_with_description(tool: BaseTool, description: str) -> BaseTool:
    """Return a copy of tool with an updated description, leaving the original intact."""
    if isinstance(tool, BaseModel):
        return tool.model_copy(update={"description": description})
    cloned = copy.copy(tool)
    cloned.description = description
    return cloned


def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    model_name: str | None = None,
    subagent_enabled: bool = False,
    *,
    mcp_plugins: list[str] | None = None,
    include_upload_tool: bool = True,
    include_conversation_reader: bool = False,
    app_config: AppConfig | None = None,
    extensions=None,
    chat_model: BaseChatModel | None = None,
) -> list[BaseTool]:
    """Get all available tools from config.

    Note: MCP tools should be initialized at application startup using
    `initialize_mcp_tools()` from deerflow.mcp module.

    Args:
        groups: Optional list of tool groups to filter by.
        include_mcp: Whether to include tools from MCP servers (default: True).
        model_name: Optional model name to determine if vision tools should be included.
        chat_model: Constructed model whose effective output cap supplies write_file
            guidance. When supplied, an absent cap omits the hint; only callers
            without a model fall back to the configured profile.
        subagent_enabled: Whether to include subagent tools (task, task_status).
        include_upload_tool: Whether to include ``list_uploaded_files`` (default: True).
            Ordinary task subagents enable it only after snapshotting the
            parent's current-run upload state. Durable batch and non-standard
            subagent callers without that state keep it disabled.
        include_conversation_reader: Allow the configured conversation reader
            only when the host provides its authorized runtime capability.
            Defaults to false for embedded callers and subagents.

    Returns:
        List of available tools.
    """
    config = app_config or get_app_config()
    tool_configs = [tool for tool in config.tools if groups is None or tool.group in groups]
    if not include_conversation_reader:
        tool_configs = [tool for tool in tool_configs if tool.use != CONVERSATION_TOOL_USE]

    # Knowledge tools are opt-in as a group. Provider connection and retrieval
    # settings live on each tool entry; the generic capability flag controls
    # whether the group is exposed at all.
    knowledge_base_config = getattr(config, "knowledge_base", None)
    if not getattr(knowledge_base_config, "enabled", False):
        tool_configs = [tool for tool in tool_configs if tool.group != "knowledge"]

    # Do not expose host bash by default when LocalSandboxProvider is active.
    if not is_host_bash_allowed(config):
        tool_configs = [tool for tool in tool_configs if not _is_host_bash_tool(tool)]

    loaded_tools_raw = [(cfg, resolve_variable(cfg.use, BaseTool)) for cfg in tool_configs]

    # Warn when the config ``name`` field and the tool object's ``.name``
    # attribute diverge — this mismatch is the root cause of issue #1803 where
    # the LLM receives one name in its tool schema but the runtime router
    # recognises a different name, producing "not a valid tool" errors.
    for cfg, loaded in loaded_tools_raw:
        if cfg.name != loaded.name:
            logger.warning(
                "Tool name mismatch: config name %r does not match tool .name %r (use: %s). The tool's own .name will be used for binding.",
                cfg.name,
                loaded.name,
                cfg.use,
            )

    loaded_tools = [_ensure_sync_invocable_tool(t) for _, t in loaded_tools_raw]

    # Conditionally add tools based on config
    builtin_tools = BUILTIN_TOOLS.copy()
    if is_mcp_task_runtime_available():
        builtin_tools.extend((list_background_tasks, cancel_background_task))
    if include_upload_tool:
        builtin_tools.append(list_uploaded_files)
    skill_evolution_config = getattr(config, "skill_evolution", None)
    if getattr(skill_evolution_config, "enabled", False):
        from deerflow.tools.skill_manage_tool import skill_manage_tool

        builtin_tools.append(skill_manage_tool)

    # Add subagent tools only if enabled via runtime parameter
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)
        if is_subagent_batch_runtime_available():
            builtin_tools.extend((batch_task, batch_status, cancel_batch))
        logger.info("Including native subagent tools")

    # If no model_name specified, use the first model (default)
    if model_name is None and config.models:
        model_name = config.models[0].name

    # Add view_image_tool only if the model supports vision
    model_config = config.get_model_config(model_name) if model_name else None
    if model_config is not None and model_config.supports_vision:
        builtin_tools.append(view_image_tool)
        logger.info(f"Including view_image_tool for model '{model_name}' (supports_vision=True)")

    # Annotate write_file with the constructed model's effective output budget so the
    # model does not assume the 80 KB streaming ceiling is the practical limit
    # for a single completion. The tool is cloned to avoid mutating the
    # module-level singleton in-place across assemblies or leaking guidance to
    # models configured without max_tokens.
    max_tokens = _extract_max_tokens(chat_model if chat_model is not None else model_config)
    if max_tokens is not None:
        safe_chars = int(max_tokens * 3 * 0.7)
        budget_note = (
            f"\n\nPER-RESPONSE BUDGET: your output limit is {max_tokens} tokens "
            f"(≈{safe_chars} chars). Single non-append writes above this will be truncated. "
            "For larger documents, write the first section now, "
            "then use append=True for subsequent sections."
        )
        loaded_tools = [
            _clone_tool_with_description(
                tool,
                f"{getattr(tool, 'description', '') or ''}{budget_note}",
            )
            if tool.name == "write_file" and hasattr(tool, "description") and "PER-RESPONSE BUDGET:" not in (getattr(tool, "description", "") or "")
            else tool
            for tool in loaded_tools
        ]

    # Get cached MCP tools if enabled
    # NOTE: We use ExtensionsConfig.from_file() instead of config.extensions
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when loading MCP tools.
    mcp_tools = []
    if include_mcp:
        try:
            from deerflow.config.extensions_config import ExtensionsConfig
            from deerflow.mcp.cache import get_cached_mcp_tools, refresh_mcp_cache_if_active

            try:
                extensions_config = ExtensionsConfig.from_file()
            except Exception as exc:
                # Only this call carries the resolved-credential risk:
                # from_file() resolves $VAR values before validation, so a
                # ValidationError message can embed secrets. Log the type only.
                logger.error("Failed to load MCP extensions config (%s)", type(exc).__name__)
            else:
                if extensions_config.get_enabled_mcp_servers():
                    mcp_tools = get_cached_mcp_tools()
                    if mcp_tools:
                        logger.info(f"Using {len(mcp_tools)} cached MCP tool(s)")

                        # Tag MCP-sourced tools so deferred-tool assembly at each
                        # agent construction site can identify them. Lead agents
                        # assemble their full configured MCP catalog and apply active
                        # skill policy at runtime; subagents may pass an already
                        # policy-filtered list because their skills load at startup.
                        for t in mcp_tools:
                            tag_mcp_tool(t)
                else:
                    # A change that disables the last MCP server must still retire
                    # the previously initialized cache and its pooled sessions.
                    # This never initializes tools: a process that never initialized
                    # MCP pays no config-hashing or discovery cost, while one that
                    # did still checks the existing cache for staleness.
                    refresh_mcp_cache_if_active()
                if mcp_plugins is not None:
                    from deerflow.capabilities.runtime import filter_mcp_plugins

                    mcp_tools = filter_mcp_plugins(mcp_tools, mcp_plugins, extensions_config)
        except ImportError:
            logger.warning("MCP module not available. Install 'langchain-mcp-adapters' package to enable MCP tools.")
        except Exception:
            # Tool caching, pool cleanup and plugin filtering raise ordinary
            # exceptions whose messages are safe and needed for debugging.
            logger.exception("Failed to get cached MCP tools")

    # Add invoke_acp_agent tool if any ACP agents are configured
    acp_tools: list[BaseTool] = []
    try:
        from deerflow.tools.builtins.invoke_acp_agent_tool import build_invoke_acp_agent_tool

        if app_config is None:
            from deerflow.config.acp_config import get_acp_agents

            acp_agents = get_acp_agents()
        else:
            acp_agents = getattr(config, "acp_agents", {}) or {}
        if acp_agents:
            acp_tools.append(build_invoke_acp_agent_tool(acp_agents))
            logger.info(f"Including invoke_acp_agent tool ({len(acp_agents)} agent(s): {list(acp_agents.keys())})")
    except Exception as e:
        logger.warning(f"Failed to load ACP tool: {e}")

    logger.info(f"Total tools loaded: {len(loaded_tools)}, built-in tools: {len(builtin_tools)}, MCP tools: {len(mcp_tools)}, ACP tools: {len(acp_tools)}")

    # Deduplicate by tool name — config-loaded tools take priority, followed by
    # built-ins, MCP tools, and ACP tools.  Duplicate names cause the LLM to
    # receive ambiguous or concatenated function schemas (issue #1803).
    from deerflow.extensions import get_agent_build_extensions
    from deerflow.extensions.plugin_tools import build_plugin_tools

    ordinary_tools = loaded_tools + builtin_tools + mcp_tools + acp_tools
    # Keep plugin-vs-plugin validation strict. Host/plugin collisions use the
    # ordinary-first deduplication below, without dropping unrelated tools.
    plugin_tools = build_plugin_tools(extensions if extensions is not None else get_agent_build_extensions(), groups=groups)
    all_tools = [_ensure_sync_invocable_tool(t) for t in ordinary_tools + plugin_tools]
    seen_names: set[str] = set()
    unique_tools: list[BaseTool] = []
    for t in all_tools:
        if t.name not in seen_names:
            unique_tools.append(t)
            seen_names.add(t.name)
        else:
            logger.warning(
                "Duplicate tool name %r detected and skipped — check your config.yaml and MCP server registrations (issue #1803).",
                t.name,
            )
    return unique_tools
