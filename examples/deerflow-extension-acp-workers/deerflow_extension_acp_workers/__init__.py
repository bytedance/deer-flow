"""Installable ACP delegated-worker adapter."""

from deerflow_extension_api import extension

from .backend import ACPWorkerBackend


@extension(api="0.2.12", name="acp-workers")
def install(registry, config):
    if not registry.worker_backend("acp", ACPWorkerBackend()):
        raise RuntimeError("This DeerFlow host does not support worker backends")
