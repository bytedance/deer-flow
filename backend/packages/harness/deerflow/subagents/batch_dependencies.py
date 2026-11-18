"""Optional dependencies between items of one existing native batch."""

from graphlib import CycleError, TopologicalSorter

from deerflow.subagents.batch_runtime import BatchItemInput


def batch_dependencies(items: list[BatchItemInput]) -> dict[str, tuple[str, ...]]:
    if not any(item.get("depends_on") for item in items):
        return {}
    keys = {item["key"] for item in items}
    if len(keys) != len(items):
        raise ValueError("Batch item keys must be unique")
    graph = {}
    for item in items:
        dependencies = item.get("depends_on", [])
        if not isinstance(dependencies, (list, tuple)) or any(not isinstance(key, str) or key not in keys or key == item["key"] for key in dependencies):
            raise ValueError("Dependencies must name other items in this batch")
        graph[item["key"]] = tuple(dict.fromkeys(dependencies))
    try:
        TopologicalSorter(graph).prepare()
    except CycleError:
        raise ValueError("Batch dependencies must not contain a cycle") from None
    return graph
