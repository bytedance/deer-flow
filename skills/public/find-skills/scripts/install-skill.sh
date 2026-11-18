#!/bin/bash

# Install a skill and link it to the project's skills/custom directory
# Usage: ./skills/install-skill.sh <owner/repo@skill-name>
# Example: ./skills/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

set -e

if [[ -z "$1" ]]; then
  echo "Usage: $0 <owner/repo@skill-name>" >&2
  echo "Example: $0 vercel-labs/agent-skills@vercel-react-best-practices" >&2
  exit 1
fi

FULL_SKILL_NAME="$1"

# Extract skill name (the part after @)
SKILL_NAME="${FULL_SKILL_NAME##*@}"

if [[ -z "$SKILL_NAME" || "$SKILL_NAME" == "$FULL_SKILL_NAME" ]]; then
  echo "Error: Invalid skill format. Expected: owner/repo@skill-name" >&2
  exit 1
fi

# Find project root by looking for deer-flow.code-workspace
find_project_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/deer-flow.code-workspace" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo ""
  return 1
}

# The installer links into a checkout's skills/custom directory. A sandbox
# workspace has no project root, and the skills it projects there are read-only,
# so report that before handing control to npx.
if ! PROJECT_ROOT="$(find_project_root)"; then
  echo "Error: no deer-flow.code-workspace found in $PWD or its parent directories." >&2
  echo "This script links a skill into the skills/custom directory of a DeerFlow checkout." >&2
  echo "Run it from the repository root, or install the skill through the Gateway from a sandbox workspace." >&2
  exit 1
fi

SKILL_SOURCE="$HOME/.agents/skills/$SKILL_NAME"
SKILL_TARGET="$PROJECT_ROOT/skills/custom"

if ! command -v npx >/dev/null 2>&1; then
  echo "Error: npx is not available. Install Node.js to download skills from skills.sh." >&2
  exit 1
fi

# Step 1: Install the skill using npx
if ! NPX_OUTPUT="$(npx skills add "$FULL_SKILL_NAME" -g -y 2>&1)"; then
  echo "Error: 'npx skills add $FULL_SKILL_NAME' failed:" >&2
  printf '%s\n' "$NPX_OUTPUT" >&2
  exit 1
fi

# Step 2: Verify installation
if [[ ! -d "$SKILL_SOURCE" ]]; then
  echo "Error: skill '$SKILL_NAME' was not installed to $SKILL_SOURCE" >&2
  exit 1
fi

# Step 3: Create symlink
if ! mkdir -p "$SKILL_TARGET"; then
  echo "Error: cannot create $SKILL_TARGET" >&2
  exit 1
fi

if ! ln -sf "$SKILL_SOURCE" "$SKILL_TARGET/"; then
  echo "Error: cannot link $SKILL_SOURCE into $SKILL_TARGET" >&2
  exit 1
fi

echo "Skill '$SKILL_NAME' installed successfully"
