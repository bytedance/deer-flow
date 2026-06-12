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
| Claude model provider | env `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN` (via `.env`), or `CLAUDE_CODE_CREDENTIALS_PATH` → a single mounted `.credentials.json` | none / one file |
| Codex model provider | env `CODEX_AUTH_PATH` pointing at a single mounted `auth.json` | one file |
| ACP agent | the adapter's own auth — many ACP adapters take an env API key (e.g. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) and need no mount; use the opt-in `docker/docker-compose.cli-auth.yaml` overlay only if your adapter reads the full CLI config dir | none / full dir |

The Gateway credential loader checks environment variables **before** the
default credential files, so the env-token paths need no bind mount at all. ACP
adapters authenticate independently of DeerFlow via their own documented env —
for example the common `claude-code-acp` adapter starts as
`ANTHROPIC_API_KEY=… claude-code-acp` and honors `CLAUDE_CONFIG_DIR` to redirect
its config directory, so it needs no `~/.claude` mount at all. Prefer the
adapter's documented env auth, and reach for the
`docker-compose.cli-auth.yaml` overlay only as a fallback for an adapter that
genuinely reads the full CLI config directory.
