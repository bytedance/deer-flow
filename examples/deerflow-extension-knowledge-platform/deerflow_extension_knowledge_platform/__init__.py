"""Optional platform/space policy. No frontend, retrieval or core modifications."""

from importlib import import_module

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BackendAction, PluginContribution

from .models import Settings
from .router import NAMESPACE, build_router
from .service import Platform
from .store import Store, administrator


async def contract(payload, context):
    administrator(context.principal)
    return {"version": 1, "authorization": "space-intersection-with-explicit-admin-provider-grants", "storage": "plugin-owned-sqlite", "retrieval_acl": False}


@extension(api="0.2.9", name="knowledge-platform")
def install(registry, config):
    if config.get("enabled", False) is False:
        return
    settings = Settings.model_validate(dict(config))
    providers = {}
    for connection in settings.connections:
        module, attribute = connection.provider_factory.split(":", 1)
        providers[connection.id] = getattr(import_module(module), attribute)(connection.provider_config)
    store = Store(settings)
    platform = Platform(settings, store, providers)
    if not registry.plugin(PluginContribution(namespace=NAMESPACE, title="Knowledge platform", enabled=True, backend=(BackendAction("contract", contract),))):
        raise RuntimeError("Host does not support platform plugin admission")
    registry.routers((build_router(platform),))
