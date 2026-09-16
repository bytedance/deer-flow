"""Projection of an assembled agent into a comparable descriptor.

The factory knows things nothing downstream can recover: which model survived
the runtime overrides, what the rendered prompt actually said, which tools
authorization left in place, and the order the middleware stack ended up in.
This module turns that transient knowledge into
:class:`~deerflow_extension_api.assembly.AgentAssemblyDescriptor`.

Two rules shape the projection:

* **Declared beats probed.** A middleware that implements
  ``release_policy_parameters()`` owns its own behaviour identity; probing
  private attributes is the fallback for the ones that do not, and is marked as
  such so a reader can tell a contract from a guess.
* **Hash, do not copy.** Prompts, tool descriptions, and argument schemas are
  reduced to hashes. A descriptor is an identity, not a second copy of the
  agent's payload.
"""

from __future__ import annotations

import logging
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from deerflow_extension_api import (
    AgentAssemblyDescriptor,
    MiddlewareDescriptor,
    ToolDescriptor,
    canonical_hash,
    collect_release_policies,
)

from deerflow.sandbox.env_policy import is_blocked_env_name
from deerflow.tools.mcp_metadata import get_mcp_source, is_mcp_tool

logger = logging.getLogger(__name__)

# Fields on a model profile that are pure identity/presentation metadata: they
# never reach the provider constructor (see ``create_chat_model``'s own
# exclude set) and renaming/re-describing a model must not look like a
# behaviour change. ``use`` is surfaced separately as ``provider``.
_MODEL_METADATA_FIELDS = frozenset(
    {
        "name",
        "display_name",
        "description",
        "use",
        "context_window",
        "pricing",
    }
)
_MIDDLEWARE_PUBLIC_FIELDS = (
    "max_concurrent",
    "max_total",
    "warn_threshold",
    "hard_limit",
    "window_size",
    "max_tracked_threads",
    "tool_freq_warn",
    "tool_freq_hard_limit",
    "trigger",
    "keep",
    "trim_tokens_to_summarize",
    "fail_closed",
    "passport",
    "_tool_freq_overrides",
    "_top_k",
    "_deferred",
    "_catalog_hash",
)
_MIDDLEWARE_HASHED_TEXT_FIELDS = (
    "summary_prompt",
    "system_prompt",
    "tool_description",
)
_MODEL_IDENTITY_FIELDS = (
    "model",
    "model_name",
    "deployment_name",
)
_PROVIDER_PARAMETER_FIELDS = (
    "_allowed",
    "_denied",
    "_default_role",
    "_resource_type",
    "_action",
)
_DETECTOR_PARAMETER_FIELDS = (
    "_finish_reasons",
    "_stop_reasons",
)


def _plain_value(value: object) -> object | None:
    """Reduce ``value`` to JSON-shaped data, or ``None`` when it cannot be.

    ``None`` means "not describable", which is deliberately indistinguishable
    from a real ``None``: both are equally uninformative for identity, and
    inventing a marker would make two undescribable values look different.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        children = [_plain_value(child) for child in value]
        if any(child is None and original is not None for child, original in zip(children, value, strict=True)):
            return None
        return sorted(children, key=str) if isinstance(value, (set, frozenset)) else children
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            plain = _plain_value(child)
            if plain is not None or child is None:
                result[key] = plain
        return result
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _plain_value(model_dump(mode="python"))
        except Exception:
            return None
    return None


def _stable_type_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def describe_model_identity(value: object) -> dict[str, str]:
    """Name a chat model without serialising it.

    Chat-model objects carry credentials and clients, so they are never plain
    data. What identifies them for comparison is the class plus the configured
    model name, unwrapped through any ``bound`` runnable wrapper the middleware
    stack layered on top.
    """
    original = value
    if isinstance(value, str):
        return {"class": "builtins.str", "name": value}
    resolved = value
    seen: set[int] = set()
    for _ in range(8):
        if not hasattr(resolved, "bound") or id(resolved) in seen:
            break
        seen.add(id(resolved))
        bound = getattr(resolved, "bound")
        if bound is None or bound is resolved:
            break
        resolved = bound
    identity = {"class": _stable_type_name(resolved)}
    for candidate in (resolved, original):
        for field_name in _MODEL_IDENTITY_FIELDS:
            field_value = getattr(candidate, field_name, None)
            if isinstance(field_value, str) and field_value:
                identity["name"] = field_value
                break
        if "name" in identity:
            break
    return identity


def _provider_identity(value: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "class": _stable_type_name(value),
        "name": str(getattr(value, "name", type(value).__name__)),
    }
    parameters: dict[str, object] = {}
    for field_name in _PROVIDER_PARAMETER_FIELDS:
        if not hasattr(value, field_name):
            continue
        raw_value = getattr(value, field_name)
        plain = _plain_value(raw_value)
        if plain is not None or raw_value is None:
            parameters[field_name.removeprefix("_")] = plain
    if parameters:
        identity["parameters"] = parameters
    nested = getattr(value, "_provider", None)
    if nested is not None and nested is not value:
        identity["provider"] = _provider_identity(nested)
    return identity


def _tool_schema(tool: object) -> dict[str, object]:
    get_input_schema = getattr(tool, "get_input_schema", None)
    if callable(get_input_schema):
        try:
            schema_model = get_input_schema()
            schema = schema_model.model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:
            pass
    args_schema = getattr(tool, "args_schema", None)
    model_json_schema = getattr(args_schema, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            schema = model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:
            pass
    return {}


def _tool_source(tool: object) -> str:
    if is_mcp_tool(tool):
        source = get_mcp_source(tool)
        return f"mcp:{source['server_name']}" if source is not None else "mcp:unknown"
    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, dict):
        declared = metadata.get("deerflow_tool_source")
        if isinstance(declared, str) and declared:
            return declared
    callable_object = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    module = getattr(callable_object, "__module__", "") or ""
    if module.startswith("deerflow.tools.builtins") or module.startswith("deerflow.agents.memory"):
        return "builtin"
    if "skill" in module:
        return "skill"
    return "community" if module else "builtin"


def describe_tool(tool: object) -> ToolDescriptor:
    """Project one bound tool into its identity."""
    source = get_mcp_source(tool) if is_mcp_tool(tool) else None
    return ToolDescriptor(
        name=str(getattr(tool, "name", type(tool).__name__)),
        description_hash=canonical_hash(str(getattr(tool, "description", "") or "")),
        schema_hash=canonical_hash(_plain_value(_tool_schema(tool))),
        source=_tool_source(tool),
        mcp_server=source["server_name"] if source is not None else None,
        mcp_transport=source["transport"] if source is not None else None,
    )


def _probe_middleware_parameters(middleware: object) -> dict[str, object]:
    """Best-effort identity for a middleware that declares none of its own."""
    parameters: dict[str, object] = {}
    for field_name in _MIDDLEWARE_PUBLIC_FIELDS:
        if not hasattr(middleware, field_name):
            continue
        raw_value = getattr(middleware, field_name)
        plain = _plain_value(raw_value)
        if plain is not None or raw_value is None:
            parameters[field_name.removeprefix("_")] = plain
    for field_name in _MIDDLEWARE_HASHED_TEXT_FIELDS:
        raw_value = getattr(middleware, field_name, None)
        if isinstance(raw_value, str):
            parameters[f"{field_name}_hash"] = canonical_hash(raw_value)
    model = getattr(middleware, "model", None)
    if model is not None:
        parameters["model"] = describe_model_identity(model)
    provider = getattr(middleware, "provider", None)
    if provider is not None:
        parameters["provider"] = _provider_identity(provider)
    routing_index = getattr(middleware, "_routing_index", None)
    plain_routing_index = _plain_value(routing_index)
    if plain_routing_index is not None:
        parameters["routing_index_hash"] = canonical_hash(plain_routing_index)
    detectors = getattr(middleware, "_detectors", None)
    if isinstance(detectors, (list, tuple)):
        detector_descriptors: list[dict[str, object]] = []
        for detector in detectors:
            descriptor: dict[str, object] = {
                "class": _stable_type_name(detector),
                "name": str(getattr(detector, "name", type(detector).__name__)),
            }
            detector_parameters: dict[str, object] = {}
            for field_name in _DETECTOR_PARAMETER_FIELDS:
                if not hasattr(detector, field_name):
                    continue
                raw_value = getattr(detector, field_name)
                plain = _plain_value(raw_value)
                if plain is not None or raw_value is None:
                    detector_parameters[field_name.removeprefix("_")] = plain
            if detector_parameters:
                descriptor["parameters"] = detector_parameters
            detector_descriptors.append(descriptor)
        parameters["detectors"] = detector_descriptors
    config = getattr(middleware, "_config", None)
    plain_config = _plain_value(config)
    if isinstance(plain_config, dict):
        parameters["config"] = plain_config
    return parameters


def _unwrap_middleware(middleware: object) -> tuple[object, str | None]:
    """Return the middleware that owns the behaviour, plus its extension.

    Extension contributions reach the stack inside an isolation wrapper whose
    dynamically generated subclass is named after the wrapper, not the
    contribution — so every contributed middleware in the process shares one
    class name and one (empty) probe result. Describing the wrapper would
    collapse them all into a single indistinguishable descriptor and hide any
    policy change inside them.

    Duck-typed on ``inner``/``source`` rather than importing the wrapper type:
    ``deerflow.extensions`` sits below this layer, so importing it here would
    point the dependency backwards, and any future wrapper of the same shape
    is handled for free.
    """
    described = middleware
    extension: str | None = None
    for _ in range(4):
        inner = getattr(described, "inner", None)
        if inner is None or inner is described:
            break
        source = getattr(described, "source", None)
        if not isinstance(source, str) or not source:
            source = getattr(described, "name", None)
        if isinstance(source, str) and source and extension is None:
            extension = source
        described = inner
    return described, extension


def describe_middleware(middleware: object) -> MiddlewareDescriptor:
    """Project one middleware, preferring its own declaration over probing."""
    described, extension = _unwrap_middleware(middleware)
    name = type(described).__name__
    declared = collect_release_policies([described])
    if name in declared:
        parameters = _plain_value(declared[name])
        if not isinstance(parameters, dict):
            logger.warning("%s declared a release policy that is not plain data; recording it as unserialisable", name)
            parameters = {"error": "UnserialisableDeclaration"}
    else:
        parameters = {"probed": True, **_probe_middleware_parameters(described)}
    return MiddlewareDescriptor(
        name=name,
        module=type(described).__module__,
        policy_parameters=parameters,
        extension=extension,
    )


def _build_identity() -> dict[str, str]:
    """Which build produced this assembly, when the deployment says so.

    Reported on its own descriptor field rather than inside
    ``effective_policies`` because the latter is hashed into the fingerprint:
    a redeploy that changes nothing about an agent must not change that
    agent's fingerprint.
    """
    try:
        package_version = version("deerflow-harness")
    except PackageNotFoundError:
        package_version = "unknown"
    return {
        "package_version": package_version,
        "image_digest": os.environ.get("DEER_FLOW_IMAGE_DIGEST", "unknown"),
        "git_commit": os.environ.get("DEER_FLOW_GIT_COMMIT", "unknown"),
    }


def _effective_model_fields(model_config: object) -> dict[str, object]:
    """All fields the model profile actually carries, declared or extra.

    ``ModelConfig`` is ``extra="allow"``, so a provider kwarg a user sets
    (``temperature``, ``max_tokens``, anything else) lives only as an extra
    field — a fixed allowlist would never see it. ``model_dump`` is the
    profile's own account of its fields, extras included, so it is preferred
    over probing named attributes. Falls back to plain instance attributes
    for a non-pydantic profile (e.g. the ``SimpleNamespace`` a subagent
    builds when its model name has no entry in the config table).
    """
    model_dump = getattr(model_config, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return dumped
    namespace = getattr(model_config, "__dict__", None)
    return dict(namespace) if isinstance(namespace, dict) else {}


def _model_parameters(model_config: object, model_overrides: dict[str, object] | None = None) -> dict[str, object]:
    """The behaviour-affecting half of a model profile, as actually constructed.

    Built from the profile's own effective fields plus any per-caller
    overrides actually applied on top (e.g. a custom agent's ``model_settings``
    sampling overrides, or a request's runtime overrides) — mirroring what
    ``create_chat_model`` layers onto the constructor — rather than a fixed
    allowlist, so a changed ``temperature``/``max_tokens``/arbitrary provider
    kwarg is always visible here.

    Credential-shaped field names (``api_key`` and anything else
    ``is_blocked_env_name`` flags) are never projected, and values that
    cannot be reduced to plain JSON-shaped data are silently dropped rather
    than raising (see ``_plain_value``).

    ``thinking_enabled`` and ``reasoning_effort`` are descriptor fields in their
    own right, so they are deliberately not duplicated here.
    """
    use = getattr(model_config, "use", None)
    result: dict[str, object] = {"provider": str(use) if use else None}
    effective = _effective_model_fields(model_config)
    if model_overrides:
        effective = {**effective, **{key: value for key, value in model_overrides.items() if value is not None}}
    for field_name, value in effective.items():
        if not isinstance(field_name, str) or field_name in _MODEL_METADATA_FIELDS:
            continue
        if is_blocked_env_name(field_name):
            continue
        plain = _plain_value(value)
        if plain is not None or value is None:
            result[field_name] = plain
    return result


def _skill_content_hash(skill: object) -> str | None:
    """Digest of a skill's ``SKILL.md`` body.

    ``SkillActivationMiddleware`` injects this body as current-turn context
    (see ``skill_activation_middleware._read_skill_content``), so it is what
    actually drives the agent's behaviour when the skill is used — not just
    the name/description/allowed-tools already projected above. ``Skill``
    does not cache its content as a field (the middleware re-reads it from
    disk at activation time), so this does the same rather than inventing a
    cached-content field the rest of the system does not have. A skill whose
    file has gone missing or become unreadable is recorded as undescribable
    (``None``) rather than raising — assembly must not fail because a skill
    file disappeared out from under it.
    """
    skill_file = getattr(skill, "skill_file", None)
    if not isinstance(skill_file, Path):
        return None
    try:
        content = skill_file.read_text(encoding="utf-8")
    except OSError:
        return None
    return canonical_hash(content)


def build_assembly_descriptor(
    *,
    namespace: str,
    agent_name: str,
    requested_model: str | None,
    effective_model: str,
    model_config: object,
    model_overrides: dict[str, object] | None = None,
    thinking_enabled: bool,
    reasoning_effort: object,
    rendered_base_prompt: str,
    prompt_template_id: str = "deerflow-lead-agent-v1",
    tools: list[object],
    middlewares: list[object],
    deferred_names: frozenset[str],
    enabled_skills: list[object],
    effective_policies: dict[str, object],
) -> AgentAssemblyDescriptor:
    """Describe one finished assembly.

    ``tools`` is the list bound to the graph; middleware-owned tools are folded
    in because the model sees them exactly the same way. The skill catalog is
    hashed rather than listed field-by-field so editing a skill's body changes
    the fingerprint while the descriptor stays small.
    """
    skill_catalog = [
        {
            "name": str(getattr(skill, "name", "")),
            "description": str(getattr(skill, "description", "")),
            "allowed_tools": sorted(str(item) for item in (getattr(skill, "allowed_tools", None) or ())),
            "content_hash": _skill_content_hash(skill),
            "secrets_autonomous": bool(getattr(skill, "secrets_autonomous", True)),
            "required_secrets": sorted(f"{getattr(requirement, 'name', '')}:{bool(getattr(requirement, 'optional', False))}" for requirement in (getattr(skill, "required_secrets", None) or ())),
        }
        for skill in enabled_skills
    ]
    assembled_tools = list(tools)
    for middleware in middlewares:
        middleware_tools = getattr(middleware, "tools", None)
        if isinstance(middleware_tools, (list, tuple)):
            assembled_tools.extend(middleware_tools)

    resolved_policies = dict(effective_policies)
    resolved_policies["prompt_template_id"] = prompt_template_id
    resolved_policies["skill_catalog_hash"] = canonical_hash(sorted(skill_catalog, key=lambda item: item["name"]))

    return AgentAssemblyDescriptor(
        namespace=namespace,
        agent_name=agent_name,
        requested_model=requested_model,
        effective_model=effective_model,
        model_parameters=_model_parameters(model_config, model_overrides),
        thinking_enabled=thinking_enabled,
        reasoning_effort=_plain_value(reasoning_effort),
        base_prompt_hash=canonical_hash(rendered_base_prompt),
        tools=tuple(describe_tool(tool) for tool in assembled_tools),
        middlewares=tuple(describe_middleware(middleware) for middleware in middlewares),
        deferred_tool_names=tuple(sorted(str(name) for name in deferred_names)),
        enabled_skills=tuple(entry["name"] for entry in skill_catalog),
        effective_policies=resolved_policies,
        build=_build_identity(),
    )


__all__ = [
    "build_assembly_descriptor",
    "describe_middleware",
    "describe_model_identity",
    "describe_tool",
]
