"""Optional LightRAG document and entity relation retrieval plugin."""

from deerflow_extension_api import extension

from .provider import LightRAGProvider

__all__ = ["LightRAGProvider", "install"]


@extension(api="0.2.7", name="lightrag-relations")
def install(registry, config):
    if not registry.knowledge_provider("lightrag-relations", LightRAGProvider(dict(config))):
        raise RuntimeError("This host does not support knowledge providers")
