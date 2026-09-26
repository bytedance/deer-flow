"""Tool provenance: display attribution only, with a fixed precedence.

The plugin tag is written by the host at construction; every other source keeps
the heuristic label it had. Nothing here is a trust input — the one decision
that needs certainty (the Layer-2 infrastructure exemption) compares object
identity, not a label.
"""

from __future__ import annotations

import logging

import pytest
from langchain_core.tools import Tool

from deerflow.agents.assembly_descriptor import describe_tool
from deerflow.extensions.plugin_tools import plugin_tool_name
from deerflow.tools.mcp_metadata import MCP_TOOL_METADATA_KEY, MCP_TOOL_SOURCE_METADATA_KEY
from deerflow.tools.tool_provenance import (
    PLUGIN_TOOL_METADATA_KEY,
    PLUGIN_TOOL_SOURCE_METADATA_KEY,
    get_plugin_source,
    is_plugin_tool,
    resolve_tool_provenance,
    tag_plugin_tool,
    tool_provenance_context,
)

NAMESPACE = "acme.reports"
INSTALLATION = "acme.plugin:install"


def _tool(module: str = "some.vendor.tools", name: str = "gadget") -> Tool:
    def func(**_kwargs):
        return "ok"

    func.__module__ = module
    return Tool(name=name, description="A tool", func=func)


def _plugin_tool(namespace: str = NAMESPACE, declaration: str = "export", *, installation: str = INSTALLATION, operation: str | None = None) -> Tool:
    tool = _tool(name=plugin_tool_name(namespace, declaration))
    tag_plugin_tool(tool, namespace=namespace, declaration=declaration, installation=installation, operation=operation)
    return tool


# --- Tag round trip ------------------------------------------------------------


def test_plugin_tag_round_trips_into_provenance_and_context():
    tool = _plugin_tool()

    assert is_plugin_tool(tool) is True
    provenance = resolve_tool_provenance(tool)
    assert provenance is not None
    assert provenance.source == f"plugin:{NAMESPACE}"
    assert provenance.namespace == NAMESPACE
    assert provenance.declaration == "export"
    assert provenance.installation == INSTALLATION
    assert provenance.operation is None
    assert tool_provenance_context(tool) == {
        "source": f"plugin:{NAMESPACE}",
        "namespace": NAMESPACE,
        "declaration": "export",
        "installation": INSTALLATION,
    }


def test_declared_shared_operation_is_carried_through():
    tool = _plugin_tool(operation="acme.reports.export")

    provenance = resolve_tool_provenance(tool)
    assert provenance is not None and provenance.operation == "acme.reports.export"
    assert tool_provenance_context(tool)["operation"] == "acme.reports.export"


def test_plugin_tag_is_read_by_the_assembly_descriptor():
    """The descriptor identity and the execution-time label cannot disagree."""
    assert describe_tool(_plugin_tool()).source == f"plugin:{NAMESPACE}"


def test_tagging_preserves_unrelated_metadata():
    tool = _tool()
    tool.metadata = {"kept": "value"}

    tag_plugin_tool(tool, namespace=NAMESPACE, declaration="export", installation=INSTALLATION)

    assert tool.metadata["kept"] == "value"
    assert tool.metadata[PLUGIN_TOOL_METADATA_KEY] is True
    assert tool.metadata[PLUGIN_TOOL_SOURCE_METADATA_KEY]["declaration"] == "export"


# --- Consistency and precedence ------------------------------------------------


def test_mis_attributed_tag_is_dropped_with_a_warning(caplog: pytest.LogCaptureFixture):
    """A tag whose name is not this plugin's generated name never becomes a label."""
    tool = _tool(name="gadget")
    tag_plugin_tool(tool, namespace=NAMESPACE, declaration="export", installation=INSTALLATION)

    with caplog.at_level(logging.WARNING):
        provenance = resolve_tool_provenance(tool)

    assert provenance is not None
    assert provenance.source == "community"  # the heuristic the tool would have had
    assert provenance.namespace is None
    assert "inconsistent plugin provenance tag" in caplog.text


@pytest.mark.parametrize(
    "source",
    [
        {"namespace": "BAD NAMESPACE", "declaration": "export", "installation": INSTALLATION},
        {"namespace": NAMESPACE, "declaration": "", "installation": INSTALLATION},
        {"namespace": NAMESPACE, "declaration": "export", "installation": None},
        {"namespace": NAMESPACE, "declaration": "export", "installation": INSTALLATION, "operation": ""},
        "not-a-mapping",
    ],
)
def test_structurally_invalid_tags_are_not_plugin_provenance(source):
    tool = _plugin_tool()
    tool.metadata = {**(tool.metadata or {}), PLUGIN_TOOL_SOURCE_METADATA_KEY: source}

    assert is_plugin_tool(tool) is True
    assert get_plugin_source(tool) is None
    provenance = resolve_tool_provenance(tool)
    assert provenance is not None and provenance.source == "community"


def test_mcp_flag_wins_over_a_plugin_tag():
    """MCP tools are tagged first in the documented precedence."""
    tool = _plugin_tool()
    tool.metadata = {
        **(tool.metadata or {}),
        MCP_TOOL_METADATA_KEY: True,
        MCP_TOOL_SOURCE_METADATA_KEY: {"server_name": "filesystem", "transport": "stdio"},
    }

    provenance = resolve_tool_provenance(tool)
    assert provenance is not None
    assert provenance.source == "mcp:filesystem"
    assert provenance.mcp_server == "filesystem"
    assert provenance.mcp_transport == "stdio"
    assert provenance.namespace is None


def test_an_mcp_flag_without_source_details_stays_labelled():
    tool = _tool()
    tool.metadata = {MCP_TOOL_METADATA_KEY: True}

    provenance = resolve_tool_provenance(tool)
    assert provenance is not None and provenance.source == "mcp:unknown"


def test_declared_tool_source_is_honoured_for_an_untagged_tool():
    """Out-of-repo tool builders keep their declaration-controlled display label."""
    tool = _tool()
    tool.metadata = {"deerflow_tool_source": "custom-vendor"}

    provenance = resolve_tool_provenance(tool)
    assert provenance is not None and provenance.source == "custom-vendor"


def test_plugin_tag_is_checked_before_a_declared_source():
    tool = _plugin_tool()
    tool.metadata = {**(tool.metadata or {}), "deerflow_tool_source": "custom-vendor"}

    provenance = resolve_tool_provenance(tool)
    assert provenance is not None and provenance.source == f"plugin:{NAMESPACE}"


# --- Heuristic fallbacks (unchanged display labels) -----------------------------


@pytest.mark.parametrize(
    "module,expected",
    [
        ("deerflow.tools.builtins.web_search", "builtin"),
        ("deerflow.agents.memory.manager", "builtin"),
        ("deerflow.skills.loader", "skill"),
        ("some.vendor.tools", "community"),
        ("", "builtin"),  # no usable __module__ on the callable
    ],
)
def test_module_heuristic_labels_are_unchanged(module: str, expected: str):
    provenance = resolve_tool_provenance(_tool(module=module))
    assert provenance is not None and provenance.source == expected


def test_every_real_tool_resolves_to_a_label():
    """An untagged source can never turn a label lookup into ``None``."""
    for tool in (_tool(), _tool(module=""), _plugin_tool()):
        provenance = resolve_tool_provenance(tool)
        assert provenance is not None and provenance.source


def test_missing_tool_resolves_to_nothing():
    assert resolve_tool_provenance(None) is None
    assert tool_provenance_context(None) == {}


def test_context_form_omits_absent_optional_fields():
    context = tool_provenance_context(_tool(module="deerflow.tools.builtins.web_search"))
    assert context == {"source": "builtin"}
