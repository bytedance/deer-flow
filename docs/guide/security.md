# ⚠️ Security Notice

## Improper Deployment May Introduce Security Risks

DeerFlow has key high-privilege capabilities including **system command execution, resource operations, and business logic invocation**, and is designed by default to be **deployed in a local trusted environment (accessible only via the 127.0.0.1 loopback interface)**. If you deploy the agent in untrusted environments — such as LAN networks, public cloud servers, or other multi-endpoint accessible environments — without strict security measures, it may introduce security risks, including:

- **Unauthorized illegal invocation**: Agent functionality could be discovered by unauthorized third parties or malicious internet scanners, triggering bulk unauthorized requests that execute high-risk operations such as system commands and file read/write, potentially causing serious security consequences.
- **Compliance and legal risks**: If the agent is illegally invoked to conduct cyberattacks, data theft, or other illegal activities, it may result in legal liability and compliance risks.

## Gateway Admin Is Equivalent to Code Execution

An admin can register stdio MCP servers, which run commands inside the Gateway
container. The API restricts them to an allowlist (`npx`, `uvx` by default,
extended via `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST`) and rejects arguments and
environment variables that would evaluate arbitrary code. That is defense in
depth, not a boundary: these launchers exist to fetch and run remote packages,
so **treat Gateway admin as equivalent to code execution on the host** and grant
it accordingly.

## External Chat Message Roles

Gateway run requests and manual thread-state updates reject client-supplied
`system` / `developer` messages with HTTP 400, including equivalent serialized
message forms. Ordinary chat, attachments, and assistant/tool history replay
remain supported. Session or PAT authentication does not grant system-prompt
authority; trusted internal run producers retain that ability.

This check prevents new role injection; it does not rewrite existing
checkpoints. If an older version accepted an injected system message, use a
fresh thread or have an operator review and clean the affected state. Restarting
the service does not remove persisted instructions, and restoring an older
checkpoint can restore them.

For local verification, run `python backend/tests/poc_external_system_message_injection.py --help`.
The same opt-in PoC supports `--expect vulnerable` on an isolated old revision
and `--expect blocked` after the fix. Its help includes PAT creation, thread-ID
selection, browser follow-up, and the distinction between persistence and model
obedience. Use a fresh disposable thread for each run; the test appends messages.

On an isolated unfixed checkout, `--expect vulnerable` demonstrates acceptance
only when the request returns 200 and the exact injected message remains in the
checkpoint as `type=system` across a normal follow-up. A marker in a web answer
is model-dependent and is not evidence by itself that the role was promoted.
After applying the fix, run the same script with `--expect blocked`: it requires
the specific role-rejection 400, an unchanged checkpoint, a successful ordinary
follow-up, and absence of the rejected message IDs. Other 400 responses and
authentication, conflict, or server errors are inconclusive rather than passes.

The PoC does not clean up automatically. When verification is complete, delete
the disposable chat with the web sidebar's delete action and revoke the
short-lived PAT if one was created. Restarting the service does not remove a
persisted injected instruction.

## Deployment Defaults

The Docker stack publishes its entry port on `127.0.0.1` only, and local
`make dev` / `make start` bind nginx, the Gateway, and the frontend to loopback,
matching the local-trusted-environment model described above. To reach it from
another machine, set `BIND_HOST` in `.env` (e.g. `BIND_HOST=0.0.0.0`) — and only
after putting the security measures below in place. Local runs apply `BIND_HOST`
to nginx on port `2026` only; the Gateway and frontend stay on loopback behind
it.

**Complete first-run setup before the host becomes reachable.** A fresh
instance has no accounts yet, so create the admin account through `/setup`
immediately after starting any deployment that is not loopback-only.

## Security Recommendations

**Note: We strongly recommend deploying DeerFlow in a local trusted network environment.** If you need cross-device or cross-network deployment, you must implement strict security measures, such as:

- **IP allowlist**: Use `iptables`, or deploy hardware firewalls / switches with Access Control Lists (ACL), to **configure IP allowlist rules** and deny access from all other IP addresses.
- **Authentication gateway**: Configure a reverse proxy (e.g., nginx) and **enable strong pre-authentication**, blocking any unauthenticated access.
- **Network isolation**: Where possible, place the agent and trusted devices in the **same dedicated VLAN**, isolated from other network devices.
- **Stay updated**: Continue to follow DeerFlow's security feature updates.
