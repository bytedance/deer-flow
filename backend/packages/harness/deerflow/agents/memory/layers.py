"""Helpers for DeerFlow layered memory organization."""

from __future__ import annotations

from typing import Any

LAYER_NAMES: tuple[str, ...] = ("working", "episodic", "semantic", "preference", "project")

LAYER_LABELS: dict[str, str] = {
    "working": "Working Memory",
    "episodic": "Episodic Memory",
    "semantic": "Semantic Memory",
    "preference": "Preference Memory",
    "project": "Project Memory",
}

_WORKING_HINTS = (
    "current",
    "now",
    "today",
    "this week",
    "working on",
    "task",
    "todo",
    "fix",
    "debug",
    "retry",
    "retest",
    "refactor",
)
_PROJECT_HINTS = (
    "deerflow",
    "deer-flow",
    "repo",
    "repository",
    "project",
    "architecture",
    "workflow",
    "memory",
    "backend",
    "frontend",
    "test",
    "build",
)
_PREFERENCE_HINTS = (
    "prefer",
    "preference",
    "likes",
    "liked",
    "dislike",
    "prefers",
    "style",
    "communication",
    "concise",
)


def create_empty_layer_index() -> dict[str, dict[str, Any]]:
    """Create an empty layer index for layered memory storage."""
    return {layer: {"summary": "", "updatedAt": "", "factIds": []} for layer in LAYER_NAMES}


def _normalize_layer_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in LAYER_NAMES else None


def _fact_text(fact: dict[str, Any]) -> str:
    content = fact.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""


def classify_fact_layer(fact: dict[str, Any]) -> str:
    """Classify a fact into one of the layered memory buckets."""
    explicit_layer = _normalize_layer_name(fact.get("layer"))
    if explicit_layer:
        return explicit_layer

    category = str(fact.get("category", "")).strip().lower()
    content = _fact_text(fact).lower()
    source_error = fact.get("sourceError")

    if category == "correction" or (isinstance(source_error, str) and source_error.strip()):
        return "working"
    if category == "preference":
        return "preference"
    if category == "knowledge":
        return "semantic"
    if category == "goal":
        return "project"
    if category == "behavior":
        return "working"

    if any(hint in content for hint in _PREFERENCE_HINTS):
        return "preference"
    if any(hint in content for hint in _WORKING_HINTS):
        return "working"
    if any(hint in content for hint in _PROJECT_HINTS):
        return "project"

    return "episodic"


def ensure_layer_index(memory_data: dict[str, Any]) -> dict[str, Any]:
    """Ensure layered memory metadata exists and is synchronized with facts."""
    if not isinstance(memory_data, dict):
        return memory_data

    existing_layers = memory_data.get("layers")
    normalized_layers = create_empty_layer_index()
    if isinstance(existing_layers, dict):
        for layer_name, layer_data in existing_layers.items():
            normalized_name = _normalize_layer_name(layer_name)
            if not normalized_name or not isinstance(layer_data, dict):
                continue
            normalized_layers[normalized_name]["summary"] = str(layer_data.get("summary", "") or "")
            normalized_layers[normalized_name]["updatedAt"] = str(layer_data.get("updatedAt", "") or "")

    facts = memory_data.get("facts", [])
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            layer_name = classify_fact_layer(fact)
            fact["layer"] = layer_name
            fact_id = fact.get("id")
            if isinstance(fact_id, str) and fact_id:
                normalized_layers[layer_name]["factIds"].append(fact_id)

    memory_data["layers"] = normalized_layers
    return memory_data


def group_facts_by_layer(memory_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Collect facts by layer after normalizing the layer index."""
    normalized = ensure_layer_index(memory_data)
    grouped: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYER_NAMES}

    facts = normalized.get("facts", [])
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            layer_name = _normalize_layer_name(fact.get("layer")) or classify_fact_layer(fact)
            grouped.setdefault(layer_name, []).append(fact)

    return grouped


def layer_order_for_context(current_context: str | None) -> list[str]:
    """Pick a layer traversal order based on the current context."""
    context = (current_context or "").lower()
    order = list(LAYER_NAMES)

    preferred: list[str] = []
    if any(hint in context for hint in _WORKING_HINTS):
        preferred.append("working")
    if any(hint in context for hint in _PROJECT_HINTS):
        preferred.append("project")
    if any(hint in context for hint in _PREFERENCE_HINTS):
        preferred.append("preference")

    if "history" in context or "recall" in context or "remember" in context:
        preferred.append("episodic")

    seen: set[str] = set()
    result = []
    for layer in preferred + order:
        if layer in seen:
            continue
        seen.add(layer)
        result.append(layer)
    return result


def layer_label(layer_name: str) -> str:
    return LAYER_LABELS.get(layer_name, layer_name.title())
