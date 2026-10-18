"""Installable WeKnora read-only provider; all evidence goes through core."""

from deerflow_extension_api import extension

from .provider import WeKnoraProvider

__all__ = ["WeKnoraProvider", "install"]


@extension(api="0.2.7", name="weknora")
def install(registry, config):
    if not registry.knowledge_provider("weknora", WeKnoraProvider(dict(config))):
        raise RuntimeError("This host does not support knowledge provider registration")
