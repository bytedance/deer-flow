# DeerFlow + Sandbox0 demo

Run this from `backend/` with an existing DeerFlow model configuration and the
Sandbox0 provider selected:

```bash
uv run --extra sandbox0 python examples/sandbox0/demo.py --config /path/to/config.yaml
```

Supply the Sandbox0 credential through `SANDBOX0_API_KEY`; optionally set
`SANDBOX0_BASE_URL` for a self-hosted regional endpoint. Supply model credentials
through the environment variables referenced by your config. The model must
support tool calling and subagent execution. This runs real LLM requests and
creates billable sandbox resources.

The demo creates isolated local data and a new conversation. It:

1. Uploads a synthetic sales CSV using `DeerFlowClient.upload_files`.
2. Runs a real Agent with a prepared skill, file tools, bash, planning and a
   delegated subagent. The subagent independently verifies the total.
3. Downloads artifacts through `DeerFlowClient.get_artifact` and checks their
   numeric content, rather than trusting the model's final response.
4. Verifies that the sandbox is paused after the turn, resets the provider, and
   asks a second turn to reuse and modify the existing files.
5. Checks the same remote identity, an increased runtime generation, the updated
   result and coverage of all ten required tools.
6. Deletes the demo sandbox by default. `--keep` retains it until its hard TTL.

Evidence is written to a unique directory under `.deer-flow/sandbox0-demo`, or
under `--output`. The evidence contains tool names, sandbox generations and
assertion results; it does not record prompts, model credentials or tool output.
The generated config is private (mode 0600) and may contain values from the input
config; keep the output directory private.

This exercises the sandbox-dependent Agent flow. It does not certify unrelated
integrations (Slack, email, browser services, MCP servers), the frontend, or
production load/fault tolerance. Model behavior is nondeterministic: a missing
required tool call fails the demo rather than being counted as coverage.

For a provider-only live check that does not call a model, run:

```bash
uv run --extra sandbox0 python examples/sandbox0/smoke.py --config /path/to/config.yaml
```

This checks real command/file/search operations, skill and upload transfer,
artifact mirroring, provider restart, pause/resume, and ephemeral `/tmp` cleanup.
It also deletes its fixture sandbox. Passing this smoke check does not replace
the real Agent demo above.
