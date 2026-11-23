#!/bin/bash

# Install a skill and link it to the project's skills/custom directory
# Usage: bash skills/public/find-skills/scripts/install-skill.sh <owner/repo@skill-name>
# Example: bash skills/public/find-skills/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

set -e

if [[ -z "$1" ]]; then
  echo "Usage: $0 <owner/repo@skill-name>"
  echo "Example: $0 vercel-labs/agent-skills@vercel-react-best-practices"
  exit 1
fi

FULL_SKILL_NAME="$1"

# Extract skill name (the part after @)
SKILL_NAME="${FULL_SKILL_NAME##*@}"

if [[ -z "$SKILL_NAME" || "$SKILL_NAME" == "$FULL_SKILL_NAME" ]]; then
  echo "Error: Invalid skill format. Expected: owner/repo@skill-name"
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

if ! PROJECT_ROOT="$(find_project_root)"; then
  printf '%s\n' \
    'Error: Could not find a DeerFlow checkout (deer-flow.code-workspace not found).' \
    "This installer only links skills into a checkout's skills/custom directory." \
    'In a sandbox or Web session, ask an administrator to install a .skill archive through Capability Center → Skills → My skills → Install .skill.' >&2
  exit 1
fi

SKILL_SOURCE="$HOME/.agents/skills/$SKILL_NAME"
SKILL_TARGET="$PROJECT_ROOT/skills/custom"

# Step 1: Install the skill using npx. Preserve the original quiet success path,
# but return the command's status and output when installation fails.
if NPX_OUTPUT="$(npx skills add "$FULL_SKILL_NAME" -g -y 2>&1)"; then
  :
else
  NPX_STATUS=$?
  printf 'Error: npx skills add failed for %s (exit %d).\n%s\n' "$FULL_SKILL_NAME" "$NPX_STATUS" "$NPX_OUTPUT" >&2
  exit "$NPX_STATUS"
fi

# Step 2: Verify installation
if [[ ! -d "$SKILL_SOURCE" ]]; then
  echo "Skill '$SKILL_NAME' installation failed"
  exit 1
fi

# Step 3: Create symlink
mkdir -p "$SKILL_TARGET"
ln -sf "$SKILL_SOURCE" "$SKILL_TARGET/"

echo "Skill '$SKILL_NAME' installed successfully"
