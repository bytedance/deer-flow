# ACP delegated workers

This extension registers `acp` as a delegated-task backend. It requires a
DeerFlow host with extension API 0.2.12 and the worker backend contract. The
operator installs and authenticates the actual ACP program separately.

From `backend/`, install this trusted local package through the existing manager:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-acp-workers --yes
```

The manager installs the package and adds its `plugins:` entry. Make it required
with `--required` when startup must fail if the adapter cannot load. If configuring
an already installed distribution manually, the entry is:

```yaml
plugins:
  - use: deerflow_extension_acp_workers:install
    required: true
acp_agents:
  coder:
    command: your-acp-launcher
    args: []
    description: External coding agent
    timeout_seconds: 1800
    auto_approve_permissions: false
subagents:
  workers:
    external-coder:
      backend: acp
      description: External coding work with a self-contained prompt
      config:
        agent: coder
```

Restart the Gateway after installation/configuration. Enable subagents for the
parent agent and include the alias in its allowlist when one is configured.
The model can now use `task(subagent_type="external-coder", prompt="...")`.
`config` accepts only the existing ACP agent name. Launch arguments, environment,
model hints and ACP permission handling remain in the referenced `acp_agents`
entry. Worker aliases cannot shadow native targets and have no managed editor.

The shared task deadline includes queueing and startup. Each execution gets a
separate workspace. No host MCP configuration or parent workspace is forwarded.
The graph checks `invoke_acp_agent` permissions and approvals before spawning;
approvals bind the exact target/config and may edit only the prompt. Delivered
steer cancels rather than pauses ACP work, even during admission; continue does
not revive it. Slots remain occupied until teardown completes after timeout.

External limits are `backend_capped`, optional usage is self-reported, and
completed acceptance criteria remain UNVERIFIED. The legacy tool retains its
old behavior. See the [subagents guide](../../docs/guide/subagents.md) for the
complete lifecycle and evidence contract.

Run the package tests from the repository root:

```sh
uv run --project backend --no-sync pytest examples/deerflow-extension-acp-workers/tests -q
```
