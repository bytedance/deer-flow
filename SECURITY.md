# Security Policy

## Supported Versions

As deer-flow doesn't provide an official release yet, please use the latest version for the security updates.
Currently, we have two branches to maintain:
* main branch for deer-flow 2.x
* main-1.x branch for deer-flow 1.x 

## Reporting a Vulnerability

Please go to https://github.com/bytedance/deer-flow/security to report the vulnerability you find.

## CLI Credential Mounts (Claude Code / Codex)

DeerFlow can reuse your Claude Code / Codex CLI subscription login as a model
provider (`ClaudeChatModel`, the Codex provider) or for ACP agents that run the
CLI in-container. The Compose stack used to bind-mount the **entire** `~/.claude`
and `~/.codex` directories (read-only) into the gateway container in **every**
configuration — exposing not just credentials but full conversation history,
per-project session data, and global CLI config. A gateway compromise (prompt
injection, tool/MCP misuse, RCE) would leak all of it.

These directories are **no longer mounted by default**. Supply CLI credentials
with the least exposure that fits your setup:

| Need | How | Exposure |
|------|-----|----------|
| Claude model provider | env `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN` (via `.env`) | none — token only |
| Codex model provider | env `CODEX_AUTH_PATH` pointing at a single mounted `auth.json` | one file |
| ACP agent running the CLI in-container | opt-in `docker/docker-compose.cli-auth.yaml` overlay | full dir (read-only) |

The Gateway credential loader checks environment variables **before** the
default credential files, so the env-token paths need no bind mount at all. Use
the `docker-compose.cli-auth.yaml` overlay only when the in-container CLI
genuinely needs the full config directory (e.g. some ACP adapters).
