#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# CodeArtifact Entrypoint
# ─────────────────────────────────────────────────────────────────────────────
# Fetches a short-lived CodeArtifact auth token using IAM credentials
# (from EC2 instance role, ECS task role, or env vars) and configures
# UV_EXTRA_INDEX_URL so that `uvx` can install private MCP server packages.
#
# Required env vars:
#   CODEARTIFACT_DOMAIN       (e.g., "thinktank")
#   AWS_ACCOUNT_ID            (e.g., "123456789012")
#   AWS_DEFAULT_REGION        (e.g., "us-east-1")
#
# Optional env vars:
#   CODEARTIFACT_REPOSITORY   (default: "mcp-servers")
#
# If CODEARTIFACT_DOMAIN is not set, this script is a no-op passthrough.
# ─────────────────────────────────────────────────────────────────────────────

set -e

if [ -n "$CODEARTIFACT_DOMAIN" ]; then
  REPO="${CODEARTIFACT_REPOSITORY:-mcp-servers}"

  echo "Fetching CodeArtifact token for ${CODEARTIFACT_DOMAIN}/${REPO}..." >&2

  TOKEN=$(aws codeartifact get-authorization-token \
    --domain "$CODEARTIFACT_DOMAIN" \
    --domain-owner "$AWS_ACCOUNT_ID" \
    --region "$AWS_DEFAULT_REGION" \
    --query authorizationToken \
    --output text)

  REPO_URL=$(aws codeartifact get-repository-endpoint \
    --domain "$CODEARTIFACT_DOMAIN" \
    --domain-owner "$AWS_ACCOUNT_ID" \
    --repository "$REPO" \
    --region "$AWS_DEFAULT_REGION" \
    --format pypi \
    --query repositoryEndpoint \
    --output text)

  # Inject token into the URL: https://aws:<token>@<domain>.codeartifact.<region>.amazonaws.com/...
  AUTHED_URL=$(echo "$REPO_URL" | sed "s|https://|https://aws:${TOKEN}@|")

  export UV_EXTRA_INDEX_URL="${AUTHED_URL}simple/"

  echo "CodeArtifact index configured." >&2
fi

# Execute the original command
exec "$@"
