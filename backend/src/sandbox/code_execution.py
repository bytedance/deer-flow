"""Dedicated Python code execution tool with structured I/O and output truncation."""

import logging
import os

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.sandbox.exceptions import SandboxError
from src.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_thread_directories_exist,
    get_thread_data,
    is_local_sandbox,
    replace_virtual_path,
    truncate_output,
)

logger = logging.getLogger(__name__)

# Maximum characters to return in tool output (saves context tokens)
MAX_OUTPUT_LENGTH = 4096

# Marker file inside the PTC directory that indicates setup is complete
_PTC_SETUP_MARKER = ".setup_done"


def _is_ptc_enabled() -> bool:
    """Check if Programmatic Tool Calling is enabled in sandbox config."""
    try:
        from src.config.app_config import get_app_config

        config = get_app_config()
        return config.sandbox.ptc_enabled if config.sandbox else False
    except Exception:
        return False


def _resolve_gateway_url() -> str:
    """Resolve the PTC Gateway URL based on sandbox type.

    Resolution order:
        1. ``PTC_GATEWAY_URL`` env var (explicit override)
        2. ``http://host.docker.internal:8001`` (Docker sandbox)
        3. ``http://localhost:8001`` (local sandbox / default)
    """
    explicit = os.environ.get("PTC_GATEWAY_URL")
    if explicit:
        return explicit.rstrip("/")

    # For Docker sandbox, use the Docker internal hostname
    # For local sandbox, use localhost
    return "http://localhost:8001"


def _ensure_ptc_setup(runtime: ToolRuntime, workspace_path: str) -> dict[str, str]:
    """Generate PTC client modules in the workspace if not already done.

    Creates the directory structure:
        {workspace}/.ptc/
            mcp_client.py
            tools/__init__.py
            tools/{server}.py  (per MCP server)

    Uses a marker file to skip re-generation on subsequent calls.
    Generates a fresh session token each time (tokens have TTL).

    Args:
        runtime: The tool runtime with context (thread_id).
        workspace_path: Physical workspace directory path.

    Returns:
        Dict of env vars to inject: PTC_TOKEN, PTC_GATEWAY_URL, PYTHONPATH.
    """
    from src.ptc.client_codegen import generate_base_client, generate_init_module, generate_server_module
    from src.ptc.session_token import create_session_token

    ptc_dir = os.path.join(workspace_path, ".ptc")
    tools_dir = os.path.join(ptc_dir, "tools")
    marker_path = os.path.join(ptc_dir, _PTC_SETUP_MARKER)

    # Generate modules only once per workspace
    if not os.path.exists(marker_path):
        os.makedirs(tools_dir, exist_ok=True)

        # Write the base client
        base_client_code = generate_base_client()
        with open(os.path.join(ptc_dir, "mcp_client.py"), "w") as f:
            f.write(base_client_code)

        # Get MCP tools grouped by server
        from src.mcp.cache import get_cached_mcp_tools_by_server
        from src.tools.catalog import ToolCatalog

        by_server = get_cached_mcp_tools_by_server()

        if by_server:
            # Build a catalog to get ToolEntry objects with full parameter schemas
            all_tools = []
            mcp_map = {}
            for server_name, tools in by_server.items():
                all_tools.extend(tools)
                for t in tools:
                    mcp_map[t.name] = server_name

            catalog = ToolCatalog.from_tools(tools=all_tools, core_tool_names=set(), mcp_server_map=mcp_map)
            catalog_by_server = catalog.get_tools_by_server()

            server_names = []
            for server_name, entries in catalog_by_server.items():
                if server_name is None:
                    continue  # Skip non-MCP tools
                from src.ptc.client_codegen import _sanitize_identifier

                safe_name = _sanitize_identifier(server_name)
                server_names.append(server_name)

                module_code = generate_server_module(server_name, entries)
                with open(os.path.join(tools_dir, f"{safe_name}.py"), "w") as f:
                    f.write(module_code)

            # Write tools/__init__.py
            init_code = generate_init_module(server_names)
            with open(os.path.join(tools_dir, "__init__.py"), "w") as f:
                f.write(init_code)
        else:
            # No MCP tools — write empty init
            with open(os.path.join(tools_dir, "__init__.py"), "w") as f:
                f.write('"""No MCP tools available."""\n')

        # Write marker
        with open(marker_path, "w") as f:
            f.write("ok")

        logger.info("PTC setup complete: generated client modules in %s", ptc_dir)

    # Always generate a fresh session token
    thread_id = runtime.context.get("thread_id", "unknown")
    token = create_session_token(thread_id)

    return {
        "PTC_TOKEN": token,
        "PTC_GATEWAY_URL": _resolve_gateway_url(),
        "PYTHONPATH": ptc_dir,
    }


@tool("execute_python", parse_docstring=True)
def execute_python_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    code: str,
    save_output_to: str | None = None,
) -> str:
    """Execute Python code in a sandboxed environment with structured output.

    Prefer this tool over `bash(command="python ...")` for data analysis, computation,
    and any task where structured output handling is beneficial. Output is automatically
    truncated to save context tokens, with an option to save full output to a file.

    Examples:
        execute_python(description="Analyze CSV", code="import pandas as pd\\ndf = pd.read_csv('/mnt/user-data/uploads/data.csv')\\nprint(df.describe())")
        execute_python(description="Save stats", code="import json\\nprint(json.dumps({'mean': 42.5}))", save_output_to="/mnt/user-data/outputs/stats.json")
        execute_python(description="Plot chart", code="import matplotlib; matplotlib.use('Agg')\\nimport matplotlib.pyplot as plt\\nplt.plot([1,2,3])")

    Args:
        description: Explain the purpose of this code execution in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        code: The Python code to execute. Include all necessary imports. Each execution is stateless.
        save_output_to: Optional absolute path to save the full (untruncated) output. Useful when output may exceed the display limit.
    """
    if not code or not code.strip():
        return "Error: No code provided"

    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        thread_data = get_thread_data(runtime) if is_local_sandbox(runtime) else None

        # Write code to a temp file in workspace
        workspace_path = "/mnt/user-data/workspace"
        if is_local_sandbox(runtime) and thread_data:
            workspace_path = replace_virtual_path(workspace_path, thread_data)

        # Create temp script
        os.makedirs(workspace_path, exist_ok=True)
        script_name = f"_exec_{os.getpid()}_{id(code)}.py"
        script_path = os.path.join(workspace_path, script_name)

        try:
            # Write the code
            with open(script_path, "w") as f:
                f.write(code)

            # Build execution command with optional PTC env vars
            ptc_env_prefix = ""
            if _is_ptc_enabled():
                try:
                    ptc_env = _ensure_ptc_setup(runtime, workspace_path)
                    env_parts = [f'{k}="{v}"' for k, v in ptc_env.items()]
                    ptc_env_prefix = " ".join(env_parts) + " "
                except Exception as e:
                    logger.warning("PTC setup failed (proceeding without PTC): %s", e)

            # Execute via sandbox
            virtual_script_path = f"/mnt/user-data/workspace/{script_name}"
            if is_local_sandbox(runtime):
                # For local sandbox, use the actual path
                output = sandbox.execute_command(f"{ptc_env_prefix}python {script_path}")
            else:
                output = sandbox.execute_command(f"{ptc_env_prefix}python {virtual_script_path}")

        finally:
            # Clean up temp script
            try:
                os.remove(script_path)
            except OSError:
                pass

        # Save full output if requested
        if save_output_to and output:
            save_path = save_output_to
            if is_local_sandbox(runtime) and thread_data:
                save_path = replace_virtual_path(save_path, thread_data)
            try:
                save_dir = os.path.dirname(save_path)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                with open(save_path, "w") as f:
                    f.write(output)
            except OSError as e:
                logger.warning("Failed to save output to %s: %s", save_output_to, e)

        # Truncate output for context efficiency
        if not output:
            return "(no output)"

        if len(output) <= MAX_OUTPUT_LENGTH:
            return output

        truncated = truncate_output(output, MAX_OUTPUT_LENGTH)
        notice = f"\n\n[Output truncated — {len(output)} chars total]"
        if save_output_to:
            notice += f"\n[Full output saved to {save_output_to}]"
        else:
            notice += "\n[Use save_output_to parameter to save the full output]"
        return truncated + notice

    except SandboxError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing Python code: {type(e).__name__}: {e}"
