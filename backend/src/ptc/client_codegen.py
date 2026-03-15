"""PTC client code generator.

Generates Python modules that sandbox code imports to call MCP tools.
All generated code uses only Python stdlib (``urllib.request`` + ``json``)
so that it works in sandboxes without third-party HTTP libraries.

Generated file structure (written to ``{workspace}/.ptc/``):
    mcp_client.py          — low-level call_tool() that POSTs to the proxy
    tools/__init__.py       — re-exports all server modules
    tools/{server}.py       — per-server module with typed wrapper functions
"""

from __future__ import annotations

import keyword
import re

from src.tools.catalog import ToolEntry, ToolParameterSchema


def _sanitize_identifier(name: str) -> str:
    """Convert a string to a valid Python identifier.

    Replaces hyphens, dots, and other non-identifier characters with underscores.
    Prepends ``_`` if the name is a Python keyword or starts with a digit.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    if keyword.iskeyword(sanitized):
        sanitized = f"{sanitized}_"
    return sanitized


# ---------------------------------------------------------------------------
# Base client: mcp_client.py
# ---------------------------------------------------------------------------


def generate_base_client() -> str:
    """Generate the base ``mcp_client.py`` module.

    This module provides ``call_tool(server, tool, **kwargs)`` that POSTs to
    the PTC Gateway proxy endpoint.  Reads ``PTC_TOKEN`` and ``PTC_GATEWAY_URL``
    from environment variables.

    Returns:
        Python source code as a string.
    """
    return '''\
"""Auto-generated PTC client — DO NOT EDIT.

Low-level helper that forwards tool calls from the sandbox to the
host-side PTC proxy via HTTP.  Uses only Python stdlib.
"""

import json
import os
import urllib.request
import urllib.error


class ToolCallError(Exception):
    """Raised when a PTC tool invocation fails."""
    pass


_TOKEN = os.environ.get("PTC_TOKEN", "")
_GATEWAY_URL = os.environ.get("PTC_GATEWAY_URL", "http://localhost:8001")
_TIMEOUT = 120  # seconds


def call_tool(server_name: str, tool_name: str, **kwargs) -> str:
    """Invoke an MCP tool via the PTC proxy.

    Args:
        server_name: The MCP server to target (e.g. "postgres").
        tool_name: The tool name on that server (e.g. "query").
        **kwargs: Tool arguments.

    Returns:
        The tool result as a string.

    Raises:
        ToolCallError: If the proxy returns an error or the request fails.
    """
    url = f"{_GATEWAY_URL}/api/ptc/call"
    payload = {
        "token": _TOKEN,
        "server_name": server_name,
        "tool_name": tool_name,
        "arguments": kwargs,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            pass
        raise ToolCallError(f"PTC proxy returned HTTP {e.code}: {detail}") from e
    except Exception as e:
        raise ToolCallError(f"PTC proxy request failed: {e}") from e

    if not body.get("success"):
        raise ToolCallError(body.get("error", "Unknown error"))

    return body.get("result", "")
'''


# ---------------------------------------------------------------------------
# Per-server wrapper module: tools/{server}.py
# ---------------------------------------------------------------------------


def _build_function_signature(params: list[ToolParameterSchema]) -> str:
    """Build a Python function signature string from parameter schemas.

    Required parameters come first, followed by optional parameters with
    defaults.
    """
    required = [p for p in params if p.required]
    optional = [p for p in params if not p.required]

    parts: list[str] = []
    for p in required:
        parts.append(f"{_sanitize_identifier(p.name)}: {p.type_hint}")
    for p in optional:
        default = p.default if p.default is not None else "None"
        parts.append(f"{_sanitize_identifier(p.name)}: {p.type_hint} = {default}")

    return ", ".join(parts)


def _build_docstring(description: str, params: list[ToolParameterSchema]) -> str:
    """Build a Google-style docstring for a wrapper function."""
    lines: list[str] = []
    if description:
        lines.append(f'    """{description}')
    else:
        lines.append('    """Call this tool.')

    if params:
        lines.append("")
        lines.append("    Args:")
        for p in params:
            pname = _sanitize_identifier(p.name)
            desc = p.description or p.type_hint
            lines.append(f"        {pname}: {desc}")

    lines.append('    """')
    return "\n".join(lines)


def _build_kwargs_dict(params: list[ToolParameterSchema]) -> str:
    """Build the keyword-arguments dict for ``call_tool()``."""
    if not params:
        return ""
    parts = []
    for p in params:
        safe = _sanitize_identifier(p.name)
        # Use the original param name as the keyword for the MCP tool
        if safe == p.name:
            parts.append(f"{p.name}={safe}")
        else:
            parts.append(f'"{p.name}"={safe}')  # noqa: E501
    return ", ".join(parts)


def generate_server_module(server_name: str, entries: list[ToolEntry]) -> str:
    """Generate a ``tools/{server}.py`` module with typed wrapper functions.

    Each wrapper calls ``call_tool(server, tool, **kwargs)``.

    Args:
        server_name: The MCP server name.
        entries: List of ToolEntry objects for this server.

    Returns:
        Python source code as a string.
    """
    lines: list[str] = [
        f'"""Auto-generated PTC wrappers for MCP server \'{server_name}\' — DO NOT EDIT."""',
        "",
        "from mcp_client import call_tool",
        "",
    ]

    for entry in entries:
        func_name = _sanitize_identifier(entry.name)
        sig = _build_function_signature(entry.parameters)
        docstring = _build_docstring(entry.description, entry.parameters)
        kwargs = _build_kwargs_dict(entry.parameters)

        lines.append(f"def {func_name}({sig}) -> str:")
        lines.append(docstring)
        lines.append(f'    return call_tool("{server_name}", "{entry.name}", {kwargs})')
        lines.append("")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Init module: tools/__init__.py
# ---------------------------------------------------------------------------


def generate_init_module(server_names: list[str]) -> str:
    """Generate ``tools/__init__.py`` that re-exports all server modules.

    Args:
        server_names: List of MCP server names.

    Returns:
        Python source code as a string.
    """
    lines: list[str] = [
        '"""Auto-generated PTC tools package — DO NOT EDIT."""',
        "",
    ]
    for name in sorted(server_names):
        safe = _sanitize_identifier(name)
        lines.append(f"from tools import {safe}  # noqa: F401")
    lines.append("")
    return "\n".join(lines)
