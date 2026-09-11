"""Private runtime context keys shared across DeerFlow runtime components."""

from typing import Final

CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: Final[str] = "__deerflow_pre_run_message_ids"

# Recall compares input against the selected replay checkpoint, which can
# differ from the existing boundary used by audit and delegation consumers.
CURRENT_RUN_RECALL_BOUNDARY_MESSAGE_IDS_KEY: Final[str] = "__deerflow_recall_boundary_message_ids"
