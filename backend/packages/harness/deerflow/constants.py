"""Shared runtime protocol constants."""

DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"

# Hidden subdirectory (under a thread's outputs dir) that holds the browser
# tools' per-step screenshots. These are transient live-progress frames, not
# deliverables, so the workspace-changes scanner excludes this directory. Both
# the browser tools (which write here) and the scanner (which ignores it) import
# this single source of truth so the name cannot drift between them.
BROWSER_FRAMES_DIRNAME = ".browser-frames"

# Default subdirectory (under a thread's outputs dir) where the tool-output
# budget middleware persists oversized tool outputs. These are process
# feedback the model reads back via ``read_file`` (the budget preview carries
# the reference), not deliverables, so the workspace-changes scanner excludes
# this directory and run delivery verification never counts it as a produced
# artifact. Both the budget middleware's default ``storage_subdir`` and the
# scanner import this single source of truth so the name cannot drift between
# them; a custom configured ``storage_subdir`` is threaded through the
# snapshot capture as an extra excluded dir name.
TOOL_RESULTS_DIRNAME = ".tool-results"

# Default timeout (seconds) for MCP server bring-up: tool discovery (subprocess
# spawn + initialize + tools/list) and persistent-session initialization. A hung
# stdio server (e.g. npx blocked on a package download or a server that never
# answers initialize) would otherwise block agent construction forever — and on
# the Gateway event loop, the whole process. Per-server override is
# ``mcpServers.<name>.session_init_timeout``; ``None`` disables the timeout.
DEFAULT_MCP_SESSION_INIT_TIMEOUT = 60.0

# Durable MCP task storage/protocol limits. The runtime validators and ORM use
# the same constants so SQLite cannot accept values that PostgreSQL later
# rejects at its VARCHAR boundaries.
MCP_TASK_SERVER_NAME_MAX_LENGTH = 128
MCP_TASK_REMOTE_ID_MAX_LENGTH = 255
MCP_TASK_NAME_MAX_LENGTH = 255
MCP_TASK_RESULT_ARTIFACT_MAX_BYTES = 65_536
MCP_TASK_POLL_AFTER_MAX_SECONDS = 86_400

# Persisted run-event envelope limits. Runtime definitions and the ORM both
# import these from this dependency-free module so lower layers never need to
# initialize deerflow.runtime just to validate storage constraints.
RUN_EVENT_TYPE_MAX_LENGTH = 32
RUN_EVENT_CATEGORY_MAX_LENGTH = 16

# Workspace changes are produced below the runtime layer, so their persisted
# event identity also lives here rather than in the runtime event catalog.
WORKSPACE_CHANGES_EVENT_TYPE = "workspace_changes"
WORKSPACE_CHANGES_EVENT_CATEGORY = "workspace"
