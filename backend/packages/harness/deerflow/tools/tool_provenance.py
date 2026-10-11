"""Host-recorded tool provenance.

Two consumers with different trust needs share this module:

* **Display attribution** — which component a tool came from, for assembly
  descriptors, traces and enterprise context. Best effort and consistency
  checked; a provenance label is **never** a trust input.
* **Exemption identity** — the one host decision that needs certainty (the
  Layer-2 infrastructure-tool exemption) compares the concrete bound tool
  object, not a label. That reference travels on
  ``GuardrailRequest.tool_identity``; this module decides nothing.

Only two sources write a tag, both host-written at construction time: MCP tools
(:mod:`deerflow.tools.mcp_metadata`, written by the loader) and plugin tools
(:func:`tag_plugin_tool`, written by ``deerflow.extensions.plugin_tools``).
Every other source keeps a heuristic label computed here, and the resolution
order is part of the contract:

``mcp flag`` → ``plugin tag`` → declared ``deerflow_tool_source`` → module
heuristic → ``builtin`` when the callable exposes no module.

Some host-owned sources are labeled ``community`` by that heuristic
(task-continuity tools, project-shelf tools, config- and middleware-declared
tools); those labels are display-only and unchanged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from deerflow.tools.mcp_metadata import get_mcp_source, is_mcp_tool

logger = logging.getLogger(__name__)

PLUGIN_TOOL_METADATA_KEY = "deerflow_plugin"
PLUGIN_TOOL_SOURCE_METADATA_KEY = "deerflow_plugin_source"
DECLARED_TOOL_SOURCE_METADATA_KEY = "deerflow_tool_source"

# Mirrors the host plugin-namespace registration rule
# (deerflow.config.plugin_settings). Independent copy on purpose: this module is
# a leaf that must not import the extension registry, and
# tests/test_plugin_targets.py asserts all three copies agree on one sample set.
_NAMESPACE_PATTERN = r"[a-z][a-z0-9_.-]{0,95}"
_NAMESPACE_RE = re.compile(_NAMESPACE_PATTERN)

# Order of the optional fields in the plain-mapping form handed to enterprise
# consumers (GuardrailRequest.tool_provenance, AuthzRequest.context).
_OPTIONAL_CONTEXT_FIELDS = ("namespace", "declaration", "installation", "operation", "mcp_server", "mcp_transport")


@dataclass(frozen=True, slots=True)
class ToolProvenance:
    """Where a bound tool came from, for display and enterprise context."""

    source: str
    """``"plugin:<namespace>"`` | ``"mcp:<server>"`` | ``"builtin"`` | ``"skill"`` | ``"community"``."""

    namespace: str | None = None
    declaration: str | None = None
    """The plugin's raw ``ModelTool.name`` (not the generated bound tool name)."""

    installation: str | None = None
    """The contributing ``ExtensionSpec`` source string."""

    operation: str | None = None
    """The plugin's declared shared operation, when it declared one."""

    mcp_server: str | None = None
    mcp_transport: str | None = None


def tag_plugin_tool(
    tool: object,
    *,
    namespace: str,
    declaration: str,
    installation: str,
    operation: str | None = None,
) -> None:
    """Record host-side plugin provenance on ``tool`` (mutates in place).

    Only the host calls this, at plugin-tool construction, with values the
    registry already validated. ``ModelTool`` carries no metadata field, so a
    plugin cannot inject a ``deerflow_*`` tag through its declaration.
    """
    source: dict[str, Any] = {
        "namespace": namespace,
        "declaration": declaration,
        "installation": installation,
    }
    if operation is not None:
        source["operation"] = operation
    tool.metadata = {
        **(getattr(tool, "metadata", None) or {}),
        PLUGIN_TOOL_METADATA_KEY: True,
        PLUGIN_TOOL_SOURCE_METADATA_KEY: source,
    }


def is_plugin_tool(tool: object) -> bool:
    """True when ``tool`` carries the plugin tag written by :func:`tag_plugin_tool`."""
    metadata = getattr(tool, "metadata", None)
    return isinstance(metadata, Mapping) and metadata.get(PLUGIN_TOOL_METADATA_KEY) is True


def get_plugin_source(tool: object) -> dict[str, Any] | None:
    """Return the structurally valid plugin tag, or ``None``.

    Valid means the flag is set, every required field is a non-empty string, the
    namespace matches the host charset, and ``operation`` is a non-empty string
    when present. The tag's *name consistency* with the tool is checked by
    :func:`resolve_tool_provenance`, which owns the ``tool.name`` comparison.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, Mapping) or metadata.get(PLUGIN_TOOL_METADATA_KEY) is not True:
        return None
    source = metadata.get(PLUGIN_TOOL_SOURCE_METADATA_KEY)
    if not isinstance(source, Mapping):
        return None
    namespace = source.get("namespace")
    declaration = source.get("declaration")
    installation = source.get("installation")
    if not all(isinstance(value, str) and value for value in (namespace, declaration, installation)):
        return None
    if not _NAMESPACE_RE.fullmatch(namespace):
        return None
    resolved: dict[str, Any] = {
        "namespace": namespace,
        "declaration": declaration,
        "installation": installation,
    }
    operation = source.get("operation")
    if operation is not None:
        if not isinstance(operation, str) or not operation:
            return None
        resolved["operation"] = operation
    return resolved


def _callable_module(tool: object) -> str:
    callable_object = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    return getattr(callable_object, "__module__", "") or ""


def resolve_tool_provenance(tool: object | None) -> ToolProvenance | None:
    """Resolve *tool*'s provenance, or ``None`` when there is no tool at all.

    Every tool without a tag still resolves to a label, so a label lookup is
    never ``None`` for a real tool.
    """
    if tool is None:
        return None

    if is_mcp_tool(tool):
        source = get_mcp_source(tool)
        if source is None:
            return ToolProvenance(source="mcp:unknown")
        return ToolProvenance(
            source=f"mcp:{source['server_name']}",
            mcp_server=source["server_name"],
            mcp_transport=source["transport"],
        )

    plugin = get_plugin_source(tool)
    if plugin is not None:
        # Local import: plugin_tools tags its tools through this module, so a
        # module-level import here would be a cycle. The consistency check runs
        # only for tagged tools, which are host-built plugin tools.
        from deerflow.extensions.plugin_tools import plugin_tool_name

        if getattr(tool, "name", None) == plugin_tool_name(plugin["namespace"], plugin["declaration"]):
            return ToolProvenance(
                source=f"plugin:{plugin['namespace']}",
                namespace=plugin["namespace"],
                declaration=plugin["declaration"],
                installation=plugin["installation"],
                operation=plugin.get("operation"),
            )
        # A mis-attributed tag is dropped rather than mislabeling the tool. This
        # is a consistency check, not an authenticity check: code able to forge
        # the metadata can forge the name with it. It exists so a tag that does
        # not describe *this* tool never becomes a label.
        logger.warning(
            "Dropping inconsistent plugin provenance tag on tool %r (declared %s/%s)",
            getattr(tool, "name", tool),
            plugin["namespace"],
            plugin["declaration"],
        )

    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, Mapping):
        declared = metadata.get(DECLARED_TOOL_SOURCE_METADATA_KEY)
        if isinstance(declared, str) and declared:
            return ToolProvenance(source=declared)

    module = _callable_module(tool)
    if module.startswith("deerflow.tools.builtins") or module.startswith("deerflow.agents.memory"):
        return ToolProvenance(source="builtin")
    if "skill" in module:
        return ToolProvenance(source="skill")
    return ToolProvenance(source="community" if module else "builtin")


def tool_provenance_context(tool: object | None) -> dict[str, Any]:
    """Plain-mapping form of :func:`resolve_tool_provenance` for request contexts."""
    provenance = resolve_tool_provenance(tool)
    if provenance is None:
        return {}
    context: dict[str, Any] = {"source": provenance.source}
    for field in _OPTIONAL_CONTEXT_FIELDS:
        value = getattr(provenance, field)
        if value is not None:
            context[field] = value
    return context
