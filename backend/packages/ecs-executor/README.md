# Native ECS submission scope

This optional package adds a trusted submission boundary to DeerFlow's existing
MCP tool and durable task driver paths. It does not provide a remote MCP server,
execute commands, deploy infrastructure, or introduce a parallel task runtime.

Install this package in the Gateway environment (from `backend/`,
`uv pip install ./packages/ecs-executor`) alongside the matching local
`deerflow-harness`. Select an enabled deployment HTTP MCP server and its **raw**
submit tool using Gateway process environment variables:

| Variable | Meaning |
| --- | --- |
| `ECS_EXECUTOR_SCOPE_SERVER` | Exact configured server name |
| `ECS_EXECUTOR_SCOPE_SUBMIT_TOOL` | Exact raw submit name, before MCP prefixing |
| `ECS_EXECUTOR_SCOPE_AUDIENCE` | Exact remote verifier audience |
| `ECS_EXECUTOR_SCOPE_SECRET` | Operator-managed HMAC secret, at least 32 UTF-8 bytes; use a randomly generated secret |

Register the no-argument builder in operator-managed `extensions_config.json`:

```json
{
  "mcpInterceptors": [
    "ecs_executor.interceptor:build_execution_scope_interceptor"
  ],
  "mcpServers": {
    "ecs": {
      "type": "http",
      "url": "https://executor.example/mcp",
      "task_toolsets": [
        {
          "name": "execution",
          "submit_tool": "submit",
          "status_tool": "status",
          "cancel_tool": "cancel"
        }
      ]
    }
  }
}
```

This is a configuration illustration, not a working endpoint. Enable the native
`mcp_tasks` runtime with SQL persistence before configuring `task_toolsets`.
Restart the Gateway after package, interceptor, secret, or task binding changes.
The selected server must use HTTP; SSE and stdio are rejected. Never configure
`X-DeerFlow-Execution-Scope` statically, in any casing. Register this interceptor
last so another custom interceptor cannot overwrite its reserved header or mutate
the signed arguments. Earlier copies of that header are removed case-insensitively.

The interceptor reads `request.runtime.context`, falling back to ambient
`langgraph.runtime.get_runtime().context` for native durable submissions.
It requires the Gateway's current `user_id`, `thread_id`, `run_id`, and explicit
`thread_incarnation` context key. The native user resolver selects the owner;
the native incarnation helper also enforces its lifecycle guard. Ambient runtime
fallback includes the current native runnable config for metadata guard checking;
identity is still read from the runtime, never from `config.context`. An explicit
legacy `thread_incarnation: null` remains valid. Model arguments never supply
owner or lifecycle authority. The signature and secret remain outside model
arguments and error messages; operators must redact the scope header from
HTTP logs and traces.

The header contains a canonical JSON payload and HMAC-SHA256 signature as two
unpadded base64url segments. Claims are `aud`, `user_id`, `thread_id`,
`incarnation`, `run_id`, `operation`, `iat`, `exp`, and `args_sha256`.
Submission lifetime defaults to 60 seconds and cannot exceed 300 seconds;
verifiers reject future-issued scopes with no clock-skew allowance, so Gateway
and executor clocks must be synchronized. IDs are nonempty and at most 255
characters. Tokens are at most 8 KiB, and strict JSON arguments are at most
256 KiB with nesting at most 32. Argument serialization uses sorted object
keys, ASCII JSON escapes, compact separators and rejects nonfinite numbers.

A future remote submit handler must call `verify_execution_scope` **before any
execution**, supplying its separately authenticated user ID, actual parsed
arguments, operator-selected audience and operation, and the same secret.
Reject absent or invalid headers and persist the verified owner/thread/incarnation
with the remote task. Native custom-builder load failures are logged and skipped
by DeerFlow, so remote mandatory verification is the final fail-closed boundary.
The scope proves submission intent; it is not a single-use nonce. Replay prevention
and durable admission/idempotency belong to the future remote task store.

Status and cancel calls pass through without a new scope because the native task
poller runs after the originating run ends. The future remote executor must
compare its persisted remote owner against independently authenticated callers.
Native background HTTP user context is installed from the persisted local owner
only when that server has enabled `user_auth`; configure per-user remote
credentials for these calls rather than relying on the originating run context.

The backend tests load this optional source package through a test-only path
fixture, so normal `make test` / `uv run pytest` needs no package installation
or extra `PYTHONPATH`. With backend dependencies installed, run from `backend/`:

```bash
uv run pytest tests/test_ecs_executor_scope.py -q
```
