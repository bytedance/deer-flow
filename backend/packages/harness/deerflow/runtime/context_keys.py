"""Private runtime context keys shared across DeerFlow runtime components."""

from collections.abc import Mapping
from typing import Final

MCP_BROWSER_USER_CONTEXT_KEY: Final[str] = "__deerflow_mcp_browser_user"

CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: Final[str] = "__deerflow_pre_run_message_ids"

# Server-authored checkpoint metadata that binds materialized state to the
# agent policy which produced it. The sentinel is intentionally not a valid
# custom-agent name, so a missing/invalid legacy value cannot be confused with
# the default agent and accidentally authorize a memory write.
CHECKPOINT_AGENT_NAME_METADATA_KEY: Final[str] = "deerflow_agent_name"
DEFAULT_AGENT_NAME_METADATA_VALUE: Final[str] = "__default__"

# Server-owned pinned project snapshot for a run, resolved once at admission
# (spec §7.1). Holds ``{project_id, name, instructions, shelf, shelf_hash}``.
# Clients can never supply it: it is popped from both run-config sections at
# Gateway admission and refused by the run worker's runtime-context merge.
PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"
AGENT_AUTH_CONTEXT_KEY: Final[str] = "__deerflow_mcp_agent_authority"

# Server-owned marker for a run whose thread is incognito. Middlewares and
# tools read it to skip durable writes (memory, blob storage); clients can
# never supply it, so a normal run cannot opt itself out of persistence.
INCOGNITO_CONTEXT_KEY: Final[str] = "__deerflow_incognito"


def is_incognito_runtime(runtime: object) -> bool:
    """Return whether *runtime* belongs to an incognito thread.

    The marker is server-owned: Gateway admission pins it from the stored
    thread, and the run worker hoists it into the runtime context, so a client
    cannot mark or unmark a run. Anything other than the exact boolean ``True``
    means an ordinary run.
    """
    context = getattr(runtime, "context", None)
    return isinstance(context, Mapping) and context.get(INCOGNITO_CONTEXT_KEY) is True


def checkpoint_agent_binding_metadata(metadata: object) -> dict[str, str]:
    """Copy a checkpoint's server-authored agent binding for a state rewrite.

    Callers must pass persisted checkpoint metadata, never request metadata.
    Missing or malformed values remain unbound so memory writes fail closed.
    """
    if not isinstance(metadata, Mapping):
        return {}
    value = metadata.get(CHECKPOINT_AGENT_NAME_METADATA_KEY)
    if not isinstance(value, str) or not value:
        return {}
    return {CHECKPOINT_AGENT_NAME_METADATA_KEY: value}
