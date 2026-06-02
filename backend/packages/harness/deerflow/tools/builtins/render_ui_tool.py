"""Tool for rendering dynamic UI components in the user interface."""

import json
import uuid

from langchain.tools import tool
from langgraph.config import get_config, get_stream_writer

from deerflow.tools.render_ui_metrics import get_render_ui_metrics

ALLOWED_COMPONENTS = frozenset(
    {"chart", "echart", "table", "card", "form", "confirm", "code", "timeline", "markdown", "layout", "image", "device-selector", "device-selector-multi", "sub-device-selector", "abnormal-list-selector", "agent_handoff"}
)

ALLOWED_ACTIONS = frozenset({"create", "update", "delete"})

SCHEMA_VERSION = "1.0"


@tool("render_ui", parse_docstring=True)
def render_ui_tool(
    component: str,
    props: dict,
    interactive: bool = False,
    callback_id: str | None = None,
    callback_timeout_ms: int | None = None,
    parent_id: str | None = None,
    block_id: str | None = None,
    action: str = "create",
    sequence: int | None = None,
    functional_interaction: bool = False,
) -> str:
    """Render a UI component in the user interface.

    Use this tool to display rich visual components such as charts, tables,
    cards, forms, and more. The component will be rendered in the chat interface.

    Args:
        component: Component type. One of: chart, echart, table, card, form, confirm, code, timeline, markdown, layout, image, device-selector, device-selector-multi, sub-device-selector, abnormal-list-selector, agent_handoff.
        props: Component properties object. Structure depends on the component type.
        interactive: Whether the component accepts user interaction (e.g., form submission).
        callback_id: Required if interactive=True. Used to route interaction callbacks back to the agent.
        callback_timeout_ms: Optional timeout in milliseconds for interactive components. After this time, the interaction expires.
        parent_id: Optional parent block_id for layout grouping. Use when nesting blocks inside a layout.
        block_id: Optional block_id for update/delete actions. If not provided for create, a new UUID is generated.
        action: One of 'create', 'update', 'delete'. Default is 'create'.
        sequence: Optional ordering hint. Blocks with lower sequence numbers appear first.
        functional_interaction: If True, this interactive block remains visible in historical turns instead of being hidden.

    Returns:
        A success or error message indicating the result of the render operation.
    """
    if component not in ALLOWED_COMPONENTS:
        return f"Error: Unknown component '{component}'. Allowed: {sorted(ALLOWED_COMPONENTS)}"

    if action not in ALLOWED_ACTIONS:
        return f"Error: Unknown action '{action}'. Allowed: {sorted(ALLOWED_ACTIONS)}"

    if interactive and not callback_id:
        return "Error: interactive=True requires a callback_id"

    if action in ("update", "delete") and not block_id:
        return f"Error: action='{action}' requires a block_id"

    metrics = get_render_ui_metrics()

    with metrics.measure(component):
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id", "")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id", "")

        # Check for duplicate interactive blocks BEFORE persisting or streaming.
        # This must happen early so the second call doesn't leak a duplicate block
        # to the frontend.
        if interactive and callback_id and action == "create":
            from deerflow.agents.middlewares.genui_middleware import get_interaction_store

            store = get_interaction_store()
            existing = store.get(thread_id, callback_id)
            if existing and not existing.submitted and not existing.is_expired:
                return (
                    f"Error: An active interactive form with callback_id '{callback_id}' "
                    f"already exists (block_id={existing.callback_id}). "
                    f"Do NOT create a duplicate. Wait for the user to submit the existing form."
                )

        from deerflow.agents.genui_persistence import persist_block, resolve_create_block_id, clear_on_new_run

        clear_on_new_run(thread_id, checkpoint_id)

        if action == "create":
            resolved_block_id = (
                resolve_create_block_id(thread_id, block_id) or str(uuid.uuid4())
            )
        else:
            resolved_block_id = block_id or str(uuid.uuid4())

        block = {
            "schema_version": SCHEMA_VERSION,
            "type": "ui_block",
            "action": action,
            "block_id": resolved_block_id,
            "component": component,
            "props": props,
            "interactive": interactive,
        }

        if callback_id:
            block["callback_id"] = callback_id
        if callback_timeout_ms is not None:
            block["callback_timeout_ms"] = callback_timeout_ms
        if parent_id:
            block["parent_id"] = parent_id
        if sequence is not None:
            block["sequence"] = sequence
        if functional_interaction:
            block["functional_interaction"] = True

        writer = get_stream_writer()
        writer(block)

        persist_block(thread_id, block)

        from deerflow.agents.genui_persistence import get_persisted_blocks

        folded = get_persisted_blocks(thread_id)
        writer({"type": "ui_blocks_folded", "blocks": folded})

        if interactive and callback_id and action == "create":
            from deerflow.agents.middlewares.genui_middleware import get_interaction_store

            timeout_seconds = (callback_timeout_ms / 1000.0) if callback_timeout_ms else 300.0

            store = get_interaction_store()
            store.register(
                callback_id=callback_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                timeout=timeout_seconds,
            )

    block_json = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
    return f"UI component '{component}' ({action}) rendered successfully. block_id={resolved_block_id}\n<!--ui_block:{block_json}-->"
