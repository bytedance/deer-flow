"""Optional management backend. No UI or retrieval installation dependency."""

from importlib import import_module
from typing import Any

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BackendAction, PluginContribution
from pydantic import Field

from .contracts import Model
from .router import NAMESPACE, build_router


class Settings(Model):
    enabled: bool = Field(default=False, strict=True)
    provider_factory: str = "deerflow_extension_knowledge_management.weknora:WeKnoraManagement"
    provider_config: dict[str, Any] = Field(default_factory=dict)


async def describe_contract(payload, context):
    if not context.principal.is_admin or context.principal.is_internal:
        raise PermissionError("Management requires an administrator")
    return {"version": 1, "authorization": "explicit-admin-resource-grants", "execution": "provider-owned"}


@extension(api="0.2.7", name="knowledge-management")
def install(registry, config):
    settings = Settings.model_validate(dict(config))
    if not settings.enabled:
        return
    # Executable factory paths are operator-owned configuration, never HTTP input.
    module, attribute = settings.provider_factory.split(":", 1)
    provider = getattr(import_module(module), attribute)(settings.provider_config)
    if not registry.plugin(PluginContribution(namespace=NAMESPACE, title="Knowledge management", enabled=True, backend=(BackendAction("contract", describe_contract),))):
        raise RuntimeError("Host does not support knowledge management plugin admission")
    registry.routers((build_router(provider),))
