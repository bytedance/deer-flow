"""Shared runtime protocol constants."""

DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"

# Hidden subdirectory (under a thread's outputs dir) that holds the browser
# tools' per-step screenshots. These are transient live-progress frames, not
# deliverables, so the workspace-changes scanner excludes this directory. Both
# the browser tools (which write here) and the scanner (which ignores it) import
# this single source of truth so the name cannot drift between them.
BROWSER_FRAMES_DIRNAME = ".browser-frames"
