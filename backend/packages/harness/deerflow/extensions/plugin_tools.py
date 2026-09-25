"""Unified plugins participate in the ordinary tool assembly and authorization path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Mapping
from copy import deepcopy
from types import MappingProxyType

from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.plugins import ToolContext
from jsonschema import Draft202012Validator
from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool, ToolException

from deerflow.config.plugin_settings import defaults
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.tool_provenance import tag_plugin_tool

logger = logging.getLogger(__name__)


def plugin_settings(source, plugin):
    """Unified plugins use their deployment-owned manifest; no runtime override."""
    return defaults(plugin.settings_contribution())


def validate_schema(schema, *, tool=False):
    try:
        plain = json.loads(json.dumps(schema))
        if plain.get("type") != "object":
            raise ValueError("Plugin schemas must describe objects")

        # No reference resolution or network access during validation.
        def check(value):
            if isinstance(value, dict):
                if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ValueError("Inline plugin schemas are required")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(plain)
        if tool and {"runtime", "config"} & plain.get("properties", {}).keys():
            raise ValueError("Reserved tool argument")
        Draft202012Validator.check_schema(plain)
    except Exception as exc:
        raise ValueError("Invalid plugin object schema") from exc


def plugin_tool_name(namespace, name):
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).hexdigest()[:12]
    return f"ext_{re.sub('[^a-z0-9_]', '_', namespace)[:20]}_{name[:25]}_{digest}"


def _build_tool(source, plugin, declaration):
    schema = deepcopy(dict(declaration.input_schema))
    validator = Draft202012Validator(schema)

    async def invoke(runtime: ToolRuntime, **payload):
        try:
            settings = await asyncio.to_thread(plugin_settings, source, plugin)
            if settings["enabled"] is not True:
                raise ToolException("Plugin disabled by administrator.")
            if len(json.dumps(payload, allow_nan=False).encode()) > 256 * 1024 or not validator.is_valid(payload):
                raise ToolException("Invalid plugin tool input.")
            context = runtime.context if isinstance(runtime.context, Mapping) else {}
            tool_context = ToolContext(
                ExtensionPrincipal(resolve_runtime_user_id(runtime)),
                MappingProxyType(settings),
                context.get("thread_id"),
            )
            async with asyncio.timeout(30):
                result = await declaration.handler(MappingProxyType(payload), tool_context)
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 64 * 1024:
                raise ToolException("Plugin result exceeds 64 KiB.")
            return encoded
        except ToolException:
            raise
        except Exception as exc:
            logger.warning("Plugin tool failed: %s/%s (%s)", plugin.namespace, declaration.name, type(exc).__name__)
            raise ToolException("Plugin tool unavailable or input rejected.") from None

    tool = StructuredTool(name=plugin_tool_name(plugin.namespace, declaration.name), description=declaration.description, args_schema=schema, coroutine=invoke, handle_tool_error=True)
    tag_plugin_tool(tool, namespace=plugin.namespace, declaration=declaration.name, installation=source)
    return tool


def build_plugin_tools(loaded, *, groups=None, reserved_names=()):
    tools = []
    names = set(reserved_names)
    for source, plugin in loaded.plugins:
        if not plugin.tools:
            continue
        try:
            if plugin_settings(source, plugin)["enabled"] is not True:
                continue
        except Exception as exc:
            logger.warning("Plugin policy unavailable: %s (%s)", plugin.namespace, type(exc).__name__)
            continue
        for declaration in plugin.tools:
            if groups is not None and declaration.group not in groups:
                continue
            tool = _build_tool(source, plugin, declaration)
            if tool.name in names:
                raise ValueError(f"Plugin tool name collision: {tool.name}")
            names.add(tool.name)
            tools.append(tool)
    return tools
