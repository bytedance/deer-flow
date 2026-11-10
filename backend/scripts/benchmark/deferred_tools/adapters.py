"""Thin production adapters. Only already-authorized catalogs enter these paths."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_function

from deerflow.tools.builtins.tool_search import build_deferred_tool_setup, build_mcp_routing_middleware
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool

from .protocol import canonical_bytes

SCHEMAROUTER_VERSION = "0.17.0"
ADAPTERS = ("keywords", "regex", "auto-promote", "schemarouter")


def _never_execute(**kwargs):
    raise AssertionError("Retrieval benchmarks must never execute catalog tools")


def make_tools(definitions):
    result = []
    for definition in definitions:
        tool = StructuredTool.from_function(_never_execute, name=definition["name"], description=definition["description"], args_schema=definition["parameters"])
        tag_mcp_tool(tool, server_name="synthetic", transport="stdio")
        tag_mcp_routing(tool, {"mode": "prefer", "keywords": definition["routing_keywords"], "priority": 0})
        result.append(tool)
    return result


def build_adapter(name, definitions):
    tools = make_tools(definitions)
    schemas = {tool.name: convert_to_openai_function(tool) for tool in tools}
    if name == "schemarouter":
        try:
            version = importlib.metadata.version("schemarouter")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"Explicitly install schemarouter=={SCHEMAROUTER_VERSION} in a separate evaluation environment") from exc
        if version != SCHEMAROUTER_VERSION:
            raise ValueError(f"Expected schemarouter=={SCHEMAROUTER_VERSION}, found {version}")
        import schemarouter
        from schemarouter import SchemaRouter
        from schemarouter.integrations.langchain import tool_from_langchain

        router = SchemaRouter()
        for tool in tools:
            # Dict args_schema tools may expose LangChain's generic invocation
            # schema via get_input_jsonschema. Supply the exact native export.
            parameters = schemas[tool.name]["parameters"]
            view = SimpleNamespace(name=tool.name, description=tool.description, get_input_jsonschema=lambda p=parameters: p, get_output_jsonschema=lambda: {})
            router.add_tool(tool_from_langchain(view, remote=False))

        def retrieve(query):
            if not tools:
                # Host policy has no permitted capabilities. Do not ask the
                # third-party planner to plan with an empty registry.
                return {}, 2
            result = router.retrieve(query, k=5)
            candidates = result.candidates
            return {candidate.tool: candidate.input_schema for candidate in candidates}, len(canonical_bytes(result.model_dump(mode="json")))

        root = Path(schemarouter.__file__).parent
        source_manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.py"))}
        return retrieve, {"implementation": "schemarouter.SchemaRouter.retrieve", "version": version, "package_sources_sha256": hashlib.sha256(canonical_bytes(source_manifest)).hexdigest(), "k": 5}

    setup = build_deferred_tool_setup(tools, enabled=True)
    if name == "auto-promote":
        routing = build_mcp_routing_middleware(tools, setup, top_k=5)

        def retrieve(query):
            update = routing.before_model({"messages": [HumanMessage(query, id="benchmark-turn")]}, None) if routing else None
            names = update["promoted"]["names"] if update else []
            payload = [schemas[n] for n in names]
            return {n: schemas[n]["parameters"] for n in names}, len(canonical_bytes(payload))

        return retrieve, {"implementation": "McpRoutingMiddleware.before_model", "k": 5}

    def retrieve(query):
        if setup.tool_search_tool is None:
            return {}, 2
        command = setup.tool_search_tool.invoke({"type": "tool_call", "id": "benchmark-search", "name": "tool_search", "args": {"query": f"keywords:{query}" if name == "keywords" else query}})
        content = command.update["messages"][0].content
        if not command.update["promoted"]["names"] and content.startswith("Tool search stopped:"):
            raise ValueError("Native discovery budget exhausted; this is not a valid unsupported rejection")
        selected = json.loads(content) if command.update["promoted"]["names"] else []
        return {item["name"]: item["parameters"] for item in selected}, len(content.encode("utf-8"))

    return retrieve, {"implementation": "build_tool_search_tool.invoke", "query_mode": name, "k": 5}
