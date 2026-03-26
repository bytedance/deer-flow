# Guardrails: Pre-Tool-Call Authorization

> **Context:** [Issue #1213](https://github.com/bytedance/deer-flow/issues/1213) — DeerFlow has Docker sandboxing and human approval via `ask_clarification`, but no deterministic, policy-driven authorization layer for tool calls. An agent running autonomous multi-step tasks can execute any loaded tool with any arguments. Guardrails add a middleware that evaluates every tool call against a policy **before** execution.

## Why Guardrails

```
Without guardrails:                      With guardrails:

  Agent                                    Agent
    │                                        │
    ▼                                        ▼
  ┌──────────┐                             ┌──────────┐
  │ bash     │──▶ executes immediately     │ bash     │──▶ GuardrailMiddleware
  │ rm -rf / │                             │ rm -rf / │        │
  └──────────┘                             └──────────┘        ▼
                                                         ┌──────────────┐
                                                         │  Provider    │
                                                         │  evaluates   │
                                                         │  against     │
                                                         │  policy      │
                                                         └──────┬───────┘
                                                                │
                                                          ┌─────┴─────┐
                                                          │           │
                                                        ALLOW       DENY
                                                          │           │
                                                          ▼           ▼
                                                      Tool runs   Agent sees:
                                                      normally    "Guardrail denied:
                                                                   rm -rf blocked"
```

- **Sandboxing** provides process isolation but not semantic authorization. A sandboxed `bash` can still `curl` data out.
- **Human approval** (`ask_clarification`) requires a human in the loop for every action. Not viable for autonomous workflows.
- **Guardrails** provide deterministic, policy-driven authorization that works without human intervention.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Middleware Chain                               │
│                                                                      │
│  1. ThreadDataMiddleware     ─── per-thread dirs                     │
│  2. UploadsMiddleware        ─── file upload tracking                │
│  3. SandboxMiddleware        ─── sandbox acquisition                 │
│  4. DanglingToolCallMiddleware ── fix incomplete tool calls           │
│  5. GuardrailMiddleware ◄──── EVALUATES EVERY TOOL CALL             │
│  6. ToolErrorHandlingMiddleware ── convert exceptions to messages     │
│  7-12. (Summarization, Title, Memory, Vision, Subagent, Clarify)    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
           ┌──────────────────────────┐
           │    GuardrailProvider     │  ◄── pluggable: any class
           │    (configured in YAML)  │      with evaluate/aevaluate
           └────────────┬─────────────┘
                        │
              ┌─────────┼──────────────┐
              │         │              │
              ▼         ▼              ▼
         Built-in   OAP Passport    Custom
         Allowlist  Provider        Provider
         (zero dep) (open standard) (your code)
                        │
                  Any implementation
                  (e.g. APort, or
                   your own evaluator)
```

The `GuardrailMiddleware` implements `wrap_tool_call` / `awrap_tool_call` (the same `AgentMiddleware` pattern used by `ToolErrorHandlingMiddleware`). It:

1. Builds a `GuardrailRequest` with tool name, arguments, and passport reference
2. Calls `provider.evaluate(request)` on whatever provider is configured
3. If **deny**: returns `ToolMessage(status="error")` with the reason -- agent sees the denial and adapts
4. If **allow**: passes through to the actual tool handler
5. If **provider error** and `fail_closed=true` (default): blocks the call
6. `GraphBubbleUp` exceptions (LangGraph control signals) are always propagated, never caught

## Three Provider Options

### Option 1: Built-in AllowlistProvider (Zero Dependencies)

The simplest option. Ships with DeerFlow. Block or allow tools by name. No external packages, no passport, no network.

**config.yaml:**
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash", "write_file"]
```

This blocks `bash` and `write_file` for all requests. All other tools pass through.

You can also use an allowlist (only these tools are permitted):
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      allowed_tools: ["web_search", "read_file", "ls"]
```

**Try it:**
1. Add the config above to your `config.yaml`
2. Start DeerFlow: `make dev`
3. Ask the agent: "Use bash to run echo hello"
4. The agent sees: `Guardrail denied: tool 'bash' was blocked (oap.tool_not_allowed)`

### Option 2: OAP Passport Provider (Policy-Based)

For policy enforcement based on the [Open Agent Passport (OAP)](https://github.com/aporthq/aport-spec) open standard. An OAP passport is a JSON document that declares an agent's identity, capabilities, and operational limits. Any provider that reads an OAP passport and returns OAP-compliant decisions works with DeerFlow.

```
┌─────────────────────────────────────────────────────────────┐
│                    OAP Passport (JSON)                        │
│                   (open standard, any provider)              │
│  {                                                           │
│    "spec_version": "oap/1.0",                                │
│    "status": "active",                                       │
│    "capabilities": [                                         │
│      {"id": "system.command.execute"},                       │
│      {"id": "data.file.read"},                               │
│      {"id": "data.file.write"},                              │
│      {"id": "web.fetch"},                                    │
│      {"id": "mcp.tool.execute"}                              │
│    ],                                                        │
│    "limits": {                                               │
│      "system.command.execute": {                             │
│        "allowed_commands": ["git", "npm", "node", "ls"],     │
│        "blocked_patterns": ["rm -rf", "sudo", "chmod 777"]   │
│      }                                                       │
│    }                                                         │
│  }                                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
               Any OAP-compliant provider
          ┌────────────────┼────────────────┐
          │                │                │
     Your own         APort (ref.      Other future
     evaluator        implementation)  implementations
```

**Creating a passport manually:**

An OAP passport is just a JSON file. You can create one by hand following the [OAP specification](https://github.com/aporthq/aport-spec/blob/main/oap/oap-spec.md) and validate it against the [JSON schema](https://github.com/aporthq/aport-spec/blob/main/oap/passport-schema.json). See the [examples](https://github.com/aporthq/aport-spec/tree/main/oap/examples) directory for templates.

**Using APort as a reference implementation:**

[APort Agent Guardrails](https://github.com/aporthq/aport-agent-guardrails) is one open-source (Apache 2.0) implementation of an OAP provider. It handles passport creation, local evaluation, and optional hosted API evaluation.

```bash
pip install aport-agent-guardrails
aport setup --framework deerflow
```

This creates:
- `~/.aport/deerflow/config.yaml` -- evaluator config (local or API mode)
- `~/.aport/deerflow/aport/passport.json` -- OAP passport with capabilities and limits

**config.yaml (using APort as the provider):**
```yaml
guardrails:
  enabled: true
  provider:
    use: aport_guardrails.providers.generic:OAPGuardrailProvider
```

**config.yaml (using your own OAP provider):**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_oap_provider:MyOAPProvider
    config:
      passport_path: ./my-passport.json
```

Any provider that accepts `framework` as a kwarg and implements `evaluate`/`aevaluate` works. The OAP standard defines the passport format and decision codes; DeerFlow doesn't care which provider reads them.

**What the passport controls:**

| Passport field | What it does | Example |
|---|---|---|
| `capabilities[].id` | Which tool categories the agent can use | `system.command.execute`, `data.file.write` |
| `limits.*.allowed_commands` | Which commands are allowed | `["git", "npm", "node"]` or `["*"]` for all |
| `limits.*.blocked_patterns` | Patterns always denied | `["rm -rf", "sudo", "chmod 777"]` |
| `status` | Kill switch | `active`, `suspended`, `revoked` |

**Evaluation modes (provider-dependent):**

OAP providers may support different evaluation modes. For example, the APort reference implementation supports:

| Mode | How it works | Network | Latency |
|---|---|---|---|
| **Local** | Evaluates passport locally (bash script). | None | ~300ms |
| **API** | Sends passport + context to a hosted evaluator. Signed decisions. | Yes | ~65ms |

A custom OAP provider can implement any evaluation strategy -- the DeerFlow middleware doesn't care how the provider reaches its decision.

**Try it:**
1. Install and set up as above
2. Start DeerFlow and ask: "Create a file called test.txt with content hello"
3. Then ask: "Now delete it using bash rm -rf"
4. Guardrail blocks it: `oap.blocked_pattern: Command contains blocked pattern: rm -rf`

### Option 3: Custom Provider (Bring Your Own)

Any Python class with `evaluate(request)` and `aevaluate(request)` methods works. No base class or inheritance needed -- it's a structural protocol.

```python
# my_guardrail.py

class MyGuardrailProvider:
    name = "my-company"

    def evaluate(self, request):
        from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason

        # Example: block any bash command containing "delete"
        if request.tool_name == "bash" and "delete" in str(request.tool_input):
            return GuardrailDecision(
                allow=False,
                reasons=[GuardrailReason(code="custom.blocked", message="delete not allowed")],
                policy_id="custom.v1",
            )
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request):
        return self.evaluate(request)
```

**config.yaml:**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_guardrail:MyGuardrailProvider
```

Make sure `my_guardrail.py` is on the Python path (e.g. in the backend directory or installed as a package).

**Try it:**
1. Create `my_guardrail.py` in the backend directory
2. Add the config
3. Start DeerFlow and ask: "Use bash to delete test.txt"
4. Your provider blocks it

## Implementing a Provider

### Required Interface

```
┌──────────────────────────────────────────────────┐
│              GuardrailProvider Protocol            │
│                                                   │
│  name: str                                        │
│                                                   │
│  evaluate(request: GuardrailRequest)              │
│      -> GuardrailDecision                         │
│                                                   │
│  aevaluate(request: GuardrailRequest)   (async)   │
│      -> GuardrailDecision                         │
└──────────────────────────────────────────────────┘

┌──────────────────────────┐    ┌──────────────────────────┐
│     GuardrailRequest      │    │    GuardrailDecision      │
│                           │    │                           │
│  tool_name: str           │    │  allow: bool              │
│  tool_input: dict         │    │  reasons: [GuardrailReason]│
│  agent_id: str | None     │    │  policy_id: str | None    │
│  thread_id: str | None    │    │  metadata: dict           │
│  is_subagent: bool        │    │                           │
│  timestamp: str           │    │  GuardrailReason:         │
│                           │    │    code: str              │
└──────────────────────────┘    │    message: str           │
                                └──────────────────────────┘
```

### DeerFlow Tool Names

These are the tool names your provider will see in `request.tool_name`:

| Tool | What it does |
|---|---|
| `bash` | Shell command execution |
| `write_file` | Create/overwrite a file |
| `str_replace` | Edit a file (find and replace) |
| `read_file` | Read file content |
| `ls` | List directory |
| `web_search` | Web search query |
| `web_fetch` | Fetch URL content |
| `image_search` | Image search |
| `present_file` | Present file to user |
| `view_image` | Display image |
| `ask_clarification` | Ask user a question |
| `task` | Delegate to subagent |
| `mcp__*` | MCP tools (dynamic) |

### OAP Reason Codes

Standard codes used by the [OAP specification](https://github.com/aporthq/aport-spec):

| Code | Meaning |
|---|---|
| `oap.allowed` | Tool call authorized |
| `oap.tool_not_allowed` | Tool not in allowlist |
| `oap.command_not_allowed` | Command not in allowed_commands |
| `oap.blocked_pattern` | Command matches a blocked pattern |
| `oap.limit_exceeded` | Operation exceeds a limit |
| `oap.passport_suspended` | Passport status is suspended/revoked |
| `oap.evaluator_error` | Provider crashed (fail-closed) |

### Provider Loading

DeerFlow loads providers via `resolve_variable()` -- the same mechanism used for models, tools, and sandbox providers. The `use:` field is a Python class path: `package.module:ClassName`.

The provider is instantiated with `**config` kwargs if `config:` is set, plus `framework="deerflow"` is always injected. Accept `**kwargs` to stay forward-compatible:

```python
class YourProvider:
    def __init__(self, framework: str = "generic", **kwargs):
        # framework="deerflow" tells you which config dir to use
        ...
```

## Configuration Reference

```yaml
guardrails:
  # Enable/disable guardrail middleware (default: false)
  enabled: true

  # Block tool calls if provider raises an exception (default: true)
  fail_closed: true

  # Passport reference -- passed as request.agent_id to the provider.
  # File path, hosted agent ID, or null (provider resolves from its config).
  passport: null

  # Provider: loaded by class path via resolve_variable
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:  # optional kwargs passed to provider.__init__
      denied_tools: ["bash"]
```

## Testing

```bash
cd backend
uv run python -m pytest tests/test_guardrail_middleware.py -v
```

25 tests covering:
- AllowlistProvider: allow, deny, both allowlist+denylist, async
- GuardrailMiddleware: allow passthrough, deny with OAP codes, fail-closed, fail-open, passport forwarding, empty reasons fallback, empty tool name, protocol isinstance check
- Async paths: awrap_tool_call for allow, deny, fail-closed, fail-open
- GraphBubbleUp: LangGraph control signals propagate through (not caught)
- Config: defaults, from_dict, singleton load/reset

## Files

```
packages/harness/deerflow/guardrails/
    __init__.py              # Public exports
    provider.py              # GuardrailProvider protocol, GuardrailRequest, GuardrailDecision
    middleware.py             # GuardrailMiddleware (AgentMiddleware subclass)
    builtin.py               # AllowlistProvider (zero deps)

packages/harness/deerflow/config/
    guardrails_config.py     # GuardrailsConfig Pydantic model + singleton

packages/harness/deerflow/agents/middlewares/
    tool_error_handling_middleware.py  # Registers GuardrailMiddleware in chain

config.example.yaml          # Three provider options documented
tests/test_guardrail_middleware.py  # 25 tests
docs/GUARDRAILS.md           # This file
```
