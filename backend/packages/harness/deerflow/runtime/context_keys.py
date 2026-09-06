"""Private runtime context keys shared across DeerFlow runtime components."""

from typing import Final

CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: Final[str] = "__deerflow_pre_run_message_ids"

# Server-authored checkpoint metadata that binds materialized state to the
# agent policy which produced it. The sentinel is intentionally not a valid
# custom-agent name, so a missing/invalid legacy value cannot be confused with
# the default agent and accidentally authorize a memory write.
CHECKPOINT_AGENT_NAME_METADATA_KEY: Final[str] = "deerflow_agent_name"
DEFAULT_AGENT_NAME_METADATA_VALUE: Final[str] = "__default__"
