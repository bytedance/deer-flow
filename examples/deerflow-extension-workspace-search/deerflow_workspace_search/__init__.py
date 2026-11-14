"""Install a persistent workspace search index behind the host search contract."""

from .index import WorkspaceSearchIndex


def install(registry, config):
    index = WorkspaceSearchIndex(path=str(config.get("path", ".deer-flow/workspace-search.db")))
    if not registry.workspace_search(index):
        raise RuntimeError("This host does not support workspace search providers")
    registry.service(index)
