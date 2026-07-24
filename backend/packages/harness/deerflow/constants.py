"""Shared runtime protocol constants."""

DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"

# Hidden subdirectory (under a thread's outputs dir) that holds the browser
# tools' per-step screenshots. These are transient live-progress frames, not
# deliverables, so the workspace-changes scanner excludes this directory. Both
# the browser tools (which write here) and the scanner (which ignores it) import
# this single source of truth so the name cannot drift between them.
BROWSER_FRAMES_DIRNAME = ".browser-frames"

# Persisted run-event envelope limits. Runtime definitions and the ORM both
# import these from this dependency-free module so lower layers never need to
# initialize deerflow.runtime just to validate storage constraints.
RUN_EVENT_TYPE_MAX_LENGTH = 32
RUN_EVENT_CATEGORY_MAX_LENGTH = 16

# Workspace changes are produced below the runtime layer, so their persisted
# event identity also lives here rather than in the runtime event catalog.
WORKSPACE_CHANGES_EVENT_TYPE = "workspace_changes"
WORKSPACE_CHANGES_EVENT_CATEGORY = "workspace"
