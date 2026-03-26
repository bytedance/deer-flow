#!/bin/bash
set -e

# Auto-login to Jira if acli is installed and credentials are set
if command -v acli >/dev/null 2>&1 && [ -n "$API_TOKEN" ] && [ -n "$JIRA_SITE" ] && [ -n "$JIRA_EMAIL" ] && ! acli jira auth status >/dev/null 2>&1; then
  echo "$API_TOKEN" | acli jira auth login --site "$JIRA_SITE" --email "$JIRA_EMAIL" --token 2>&1 >&2
fi

# Auto-login to GitHub CLI if GITHUB_TOKEN is set
if command -v gh >/dev/null 2>&1 && [ -n "$GITHUB_TOKEN" ]; then
  export GH_TOKEN="$GITHUB_TOKEN"
fi

exec "$@"
