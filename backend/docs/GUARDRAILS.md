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
              ┌─────────┼──────────────┼───────────────────┐
              │         │              │                   │
              ▼         ▼              ▼                   ▼
         Built-in   OAP Passport    Custom             TypeSafe (Jev)
         Allowlist  Provider        Provider           risk gate
         (zero dep) (open standard) (your code)        (HTTP, opt-in)
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

## Four Provider Options

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
        # This skeleton reuses the sync path. If policy evaluation performs
        # async I/O, call and await the async evaluator here instead.
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

#### Optional: Runtime Attribution

Runtime attribution fields are optional. Providers that need richer policy context or audit records can read them, while simple tool allow/deny providers can ignore them:

| Field | Example use |
|---|---|
| `user_id` | Attach the authenticated DeerFlow user to a provider-side policy or audit record |
| `user_role` | Apply simple role-based policy, such as allowing an admin-only tool. Sourced from the authenticated user's `system_role` (renamed for the guardrail-facing surface, not a separate field) |
| `oauth_provider` | Link a decision to an external identity provider, when present |
| `oauth_id` | Link a decision to the external provider's subject/user id, when present |
| `thread_id` | Link a decision back to the conversation thread |
| `run_id` | Link a decision back to one execution run |
| `tool_call_id` | Identify the exact tool call that was allowed or denied |

These fields are populated by the Gateway from server-side auth state (the run worker always sets `thread_id`/`run_id`). For web-authenticated runs, `inject_authenticated_user_context` writes `user_id`/`user_role`/`oauth_provider`/`oauth_id` from `request.state.user`. For trusted IM / internal-auth runs (Slack, Discord, Telegram, Feishu, DingTalk, and other internal callers that provide a trusted owner header), the Gateway resolves the owner user server-side and writes the same attribution fields from that owner. Client-supplied values cannot override them — the server-side assignment wins.

If a trusted internal caller does not resolve to an owner user, the Gateway strips client-supplied `user_role`/`oauth_provider`/`oauth_id` from the run context instead of treating them as authoritative. Any `user_id` already present is left in place for legacy channel storage behavior, but role/oauth-based policy is only applied when the owner user was resolved server-side.

For example, if your deployment has user-scoped policy requirements, you can opt into a context-aware provider that passes the runtime fields into an external policy file. This keeps business policy out of Python code and `config.yaml`; the provider only normalizes context, evaluates a configured policy, and maps the result back to `GuardrailDecision`.

```python
import asyncio
import json
from pathlib import Path

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason


class ContextAwareGuardrailProvider:
    """Illustrative provider skeleton; policy loading/evaluation is provider-defined."""

    name = "context-aware-example"

    def __init__(self, *, policy_path, audit_path="./logs/guardrail-audit.jsonl", **kwargs):
        self.policy_path = Path(policy_path)
        self.audit_path = Path(audit_path)
        # Load policy rules here. In a real deployment this could call an
        # internal policy service, OPA/Cedar, AGT, or another rule engine.
        self.policy = self._load_policy(self.policy_path)

    def evaluate(self, request):
        decision = self._decide(request)
        self._write_audit(request, decision)
        return decision

    async def aevaluate(self, request):
        # ``_decide`` is in-memory policy work; the audit write is blocking
        # file I/O, so offload it off the event loop with ``asyncio.to_thread``
        # (DeerFlow enforces a blocking-IO gate in CI). If your policy
        # evaluation itself does blocking I/O — external policy service, file
        # read per call — move that behind ``asyncio.to_thread`` too, or
        # implement a native async evaluator and await it here.
        decision = self._decide(request)
        await asyncio.to_thread(self._write_audit, request, decision)
        return decision

    def _decide(self, request):
        # 1. Normalize DeerFlow request data into policy context.
        context = {
            "tool_name": request.tool_name,
            "tool_input": request.tool_input,
            "user_id": request.user_id,
            "user_role": request.user_role,
            "oauth_provider": request.oauth_provider,
            "oauth_id": request.oauth_id,
            "thread_id": request.thread_id,
            "run_id": request.run_id,
            "tool_call_id": request.tool_call_id,
            "agent_id": request.agent_id,
            "timestamp": request.timestamp,
            # Derived fields make simple rule engines handle multi-field checks.
            # Example policy: allow bash only for admin users.
            "role_tool_key": f"{request.user_role or ''}:{request.tool_name}",
            "command": request.tool_input.get("command", ""),
            "message": json.dumps(request.tool_input, ensure_ascii=False, default=str),
        }

        # 2. Evaluate the provider-defined policy schema.
        result = self._evaluate_policy(self.policy, context)

        # 3. Convert the policy result back to DeerFlow's decision object.
        return GuardrailDecision(
            allow=result["allow"],
            reasons=[
                GuardrailReason(
                    code=result["code"],
                    message=result["message"],
                )
            ],
            policy_id=result.get("policy_id"),
            metadata={
                "user_id": request.user_id,
                "user_role": request.user_role,
                "oauth_provider": request.oauth_provider,
                "oauth_id": request.oauth_id,
                "thread_id": request.thread_id,
                "run_id": request.run_id,
                "tool_call_id": request.tool_call_id,
            },
        )

    def _write_audit(self, request, decision):
        event = {
            "decision": "allow" if decision.allow else "deny",
            "reason": decision.reasons[0].message if decision.reasons else "",
            "policy_id": decision.policy_id,
            "tool_name": request.tool_name,
            "user_id": request.user_id,
            "user_role": request.user_role,
            "oauth_provider": request.oauth_provider,
            "oauth_id": request.oauth_id,
            "thread_id": request.thread_id,
            "run_id": request.run_id,
            "tool_call_id": request.tool_call_id,
            "agent_id": request.agent_id,
            "timestamp": request.timestamp,
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _load_policy(self, path):
        # Load your provider-defined policy file.
        raise NotImplementedError

    def _evaluate_policy(self, policy, context):
        # Evaluate ordered rules and return:
        # {"allow": bool, "code": str, "message": str, "policy_id": str | None}
        raise NotImplementedError
```

**config.yaml:**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_guardrail:ContextAwareGuardrailProvider
    config:
      policy_path: ./policies/guardrail-policy.yml
      audit_path: ./logs/guardrail-audit.jsonl
```

Many policy engines use a similar shape: normalize request context, evaluate ordered rules, and return an allow/deny decision. The exact schema is provider-defined; the YAML below is illustrative:

```yaml
# policies/guardrail-policy.yml
version: "1.0"
rules:
  - name: allow-admin-bash
    condition:
      field: role_tool_key
      operator: eq
      value: admin:bash
    action: allow
    priority: 300
    message: Admin users may execute bash

  - name: deny-bash-for-other-roles
    condition:
      field: tool_name
      operator: eq
      value: bash
    action: deny
    priority: 200
    message: bash is restricted to admin users

  - name: deny-dangerous-command
    condition:
      field: message
      operator: matches
      value: "\\brm\\s+-rf\\b"
    action: deny
    priority: 100
    message: Dangerous shell command detected

defaults:
  action: allow
```

### Option 4: TypeSafe (Jev) Risk Gate (Network Provider)

Ships with DeerFlow. Sends **one `noul` question** to [TypeSafe](https://docs.typesafe.ai/api) System One (`POST {base_url}/v1/systemone`) — "does executing this tool call risk an irreversible or out-of-scope side effect?" — and denies the call when the returned probability reaches `threshold`. It is the only provider here that sends tool arguments to a third party.

**config.yaml:**
```yaml
guardrails:
  enabled: true
  fail_closed: true
  provider:
    use: deerflow.guardrails.typesafe:TypeSafeGuardrailProvider
    config:
      # api_key: <explicit key>; when omitted, read from api_key_env
      api_key_env: TYPESAFE_API_KEY
      model: jev-latest        # pin an exact version (e.g. jev-1.13.0) when
                               # decisions must stay traceable across releases
      threshold: 0.5           # example value; calibrate with the online evaluation
      tools: ["bash"]          # SMOKE-TEST scope only -- see "Coverage" below
      # allowed_tools: ["bash", "read_file", "write_file"]   # permission list; see "Allowed tools" below
```

| Setting | Default | Notes |
|---|---|---|
| `api_key` / `api_key_env` | `TYPESAFE_API_KEY` | One of the two must resolve, or agent construction fails. |
| `base_url` | `https://api.typesafe.ai` | |
| `model` | `jev-latest` | A rolling server-side alias; pin a version for reproducibility. |
| `threshold` | `0.5` | Deny when `probability >= threshold`. |
| `tools` | omitted = **every** tool | Probing every tool matches the "every call passes the gate" contract; narrowing it shrinks protection (see Coverage). |
| `allowed_tools` | omitted = **not enforced** | Hard permission list. Tools outside it are refused locally (`typesafe.tool_not_allowed`) before the probe scope and before any state is built; `[]` refuses every tool; tools in the list still face the risk gate (see "Allowed tools"). |
| `instructions` / `criteria` | risk rubric (below) | The default rubric judges the call text alone. |
| `timeout` | `5.0` | Per-attempt sub-limit (connect/read/write/pool) -- **not** a total budget. |
| `deadline_seconds` | `10.0` | Whole-evaluation budget, including retries and backoff. |
| `max_attempts` / `retry_backoff` | `2` / `0.5` | Retries only 429/529/transport errors; backoff `retry_backoff x 2^(n-1)`. |
| `max_state_chars` | `4000` | Argument text above this is denied locally. |
| `cache_size` / `cache_ttl_seconds` | `256` / `300` | FIFO cache keyed by `(tool, arguments)`; `0` disables it. |

**Allowed tools (`allowed_tools`).** A hard permission list, not an exemption from evaluation. Omitted, no list is enforced (the probe scope decides what is evaluated). Set to `[]`, no tool may run. Set to a list, only those tools may run — a call to any other tool is refused locally (`typesafe.tool_not_allowed`) with no state built, no request and no cache entry, and the refusal is a guardrail decision, so `fail_closed: false` cannot reopen it. A listed tool is **still** probed and still denied when its risk probability reaches `threshold`; the list answers "may this tool run at all", the risk gate answers "is this particular call safe". It is checked before `tools`, so a tool outside the list is refused even when `tools` would have skipped probing it — an unlisted tool must not inherit an allow from being out of probe scope. The provider has no denylist: express deny rules and per-role limits in `authorization.*`.

**What is sent.** The tool name plus the call's full argument JSON, under `state.tool_call`. The provider does **not** redact: arguments can carry user content, file paths, shell commands or secrets, and `pii_redaction_middleware` does not apply on this path. Narrow `tools` to the tools that can cause side effects, and clear the egress with your data-protection owner before enabling.

**Limits are enforced locally.** Arguments that cannot be serialised as strict JSON (bytes, non-string keys, `NaN`/`Infinity`, lone surrogates that UTF-8 cannot encode) and argument text above `max_state_chars` are **denied without a request** (`typesafe.state_unusable`). A local refusal is a guardrail decision, so `fail_closed: false` does not turn it into an unevaluated tool run. Nothing is truncated and sent -- a prefix could hide the dangerous half of a `write_file` payload. The trade-off is real: long heredocs, inline scripts and large `write_file` bodies can trip the limit, and those refusals count toward the deployment's false-positive rate. Raising `max_state_chars` increases the data leaving the process.

**Deadlines.** The async path cancels an in-flight request through `asyncio.timeout`, which bounds the request duration but not the wall-clock cost of cleanup. The synchronous path cannot preempt a blocking call: it checks the deadline after the response headers arrive, around the body read, and before the decision is accepted, and drops results that arrived late. **No total return-time bound is promised on the sync path.**

**Audit boundary.** Denials reach the run journal (`middleware:guardrail`) with the probability, threshold, served model version and state digest in the reason message, so the threshold comparison can be replayed from the record. The served model version is response content, so it is recorded verbatim only when it fits a conservative token shape; anything else (an echoed argument, injected text, an oversized string) is recorded as `unrecorded:sha256:<digest>` rather than echoed into the message, which reaches the denied `ToolMessage`, the journal and middleware logs. Local denials (`typesafe.state_unusable`) record the failure category, the limit and the observed length -- never a probability or a model version, because the model was never asked. Allowed calls are not persisted anywhere, and native subagents do not inherit a run journal. This provider adds no audit fields.

**Coverage -- read before narrowing `tools`.** A denial does not stop the operation: the agent can retry the same effect through an unprobed tool, an MCP tool, a subagent or a shell wrapper. `tools: ["bash"]` above is a smoke-test scope, not a production recommendation. Inventory the equivalent capabilities reachable from the main agent and its subagents, probe those paths, or forbid them through `authorization.*` / the sandbox. Moving a tool out of `tools` removes it from the gate -- that is a reduction in protection, not a fix for false positives. The provider never propagates one denial to semantically equivalent later calls.

**Replacing the built-in AllowlistProvider.** `guardrails.provider` is a single slot: pointing it at TypeSafe **replaces** the allowlist provider and its rules stop applying. The allow half moves into the provider's `allowed_tools`; deny rules have no in-provider equivalent and still belong to `authorization.*`.

| Old `AllowlistProvider.config` | TypeSafe equivalent |
|---|---|
| `allowed_tools: [a, b]` | `allowed_tools: [a, b]` — listed tools still face the risk gate, every other tool is refused locally |
| `allowed_tools: []` | `allowed_tools: []` (refuse everything) |
| `allowed_tools` omitted or null | omit `allowed_tools` (not enforced) — do not write `allowed_tools: []` unless "no tool may run" is intended |
| `denied_tools: [a]` | no in-provider equivalent: `authorization.*` `deny: [a]`, which wins over allow |
| `denied_tools` omitted or null | nothing to migrate |

Verify them while the old guardrail is still enabled, then switch the slot. Deny rules and per-role limits go to the RBAC provider as before:

```yaml
authorization:
  enabled: true
  fail_closed: true
  default_role: user
  provider:
    use: deerflow.authz.rbac:RbacAuthorizationProvider
    config:
      roles:
        user:
          tools:
            deny: ["write_file"]   # the allow half lives in the provider's allowed_tools
```

Only the deny half needs RBAC now: the provider's `allowed_tools` carries the allow half for every caller, subagents included. Apply the migrated limits to **every role the old global guardrail covered**, admin/internal roles included; `default_role` only fills missing roles and never overrides an authenticated principal's role, and unknown roles fail closed. The mapping covers tool permissions only -- RBAC sets no limit on resources a known role has no policy for, and an OAP provider may carry semantics this mapping does not express. Verify allow, deny, omitted list, empty list, allow/deny overlap, the default role and real roles, including from a subagent, before switching. Rollback means restoring the old provider; keep the migrated RBAC limits until that restore is verified. RBAC also filters tool visibility at assembly time, so identical tool permissions do not guarantee identical model behavior.

**Failure surface.** When TypeSafe is unreachable, only probed calls that miss the cache are affected (blocked while `fail_closed: true`). Unprobed tools and cache hits keep working. Every failure raises: it is never silently downgraded to an allow. Provider errors report the status code or the offending field's type — never the response body, the HTTP reason phrase, or the tool arguments, all of which a malformed or hostile response can control or echo back.

**Smoke test.** Use a throwaway sandbox, a disposable file, and a test key:

```bash
cd backend
uv run python -m pytest tests/test_typesafe_guardrail_provider.py tests/blocking_io/test_typesafe_guardrail_provider.py -v
make dev   # then ask the agent to delete the disposable file with bash
```

Check the denial message the agent receives and the `middleware:guardrail` journal event. Do not run this against real project data or a production key.

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
│  user_id: str | None      │    │    code: str              │
│  user_role: str | None    │    │    message: str           │
│  oauth_provider: str | None│   │                           │
│  oauth_id: str | None     │    │                           │
│  run_id: str | None       │    │                           │
│  tool_call_id: str | None │    │                           │
│                           │    │                           │
└──────────────────────────┘    │                           │
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
| `present_files` | Present file to user |
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
uv run python -m pytest tests/test_typesafe_guardrail_provider.py -v
uv run python -m pytest tests/blocking_io/test_typesafe_guardrail_provider.py -v
```

`tests/test_guardrail_middleware.py` -- 25 tests covering:
- AllowlistProvider: allow, deny, both allowlist+denylist, async
- GuardrailMiddleware: allow passthrough, deny with OAP codes, fail-closed, fail-open, passport forwarding, empty reasons fallback, empty tool name, protocol isinstance check
- Async paths: awrap_tool_call for allow, deny, fail-closed, fail-open
- GraphBubbleUp: LangGraph control signals propagate through (not caught)
- Config: defaults, from_dict, singleton load/reset

`tests/test_typesafe_guardrail_provider.py` -- the TypeSafe provider over `httpx.MockTransport`:
- Threshold boundary, request shape and state digest
- Local denials with zero requests: over-limit arguments, unserialisable arguments, unprobed tools, allowed_tools refusals (`[]` refuses everything; a refusal outranks the probe scope and state validation)
- Allowed tools still reaching the risk gate, and allowed_tools refusals surviving `fail_closed: false`
- Response validation (`noul` type/range/finiteness, `answers`, `model`) and non-retryable vs retryable failures
- Cache hits, TTL expiry, FIFO eviction, failures and local denials never cached
- Deadline behaviour on both paths, including late results that must not be adopted
- Transport factory call counts, transport closure, and per-path client isolation
- Middleware integration: denial `ToolMessage`, replayable journal reason, fail-closed/fail-open

`tests/blocking_io/test_typesafe_guardrail_provider.py` -- anchor that drives `aevaluate` against a real loopback HTTP
server, with a meta-check proving the sync path on the loop trips the Blockbuster gate.

## Files

```
packages/harness/deerflow/guardrails/
    __init__.py              # Public exports
    provider.py              # GuardrailProvider protocol, GuardrailRequest, GuardrailDecision
    middleware.py             # GuardrailMiddleware (AgentMiddleware subclass)
    builtin.py               # AllowlistProvider (zero deps)
    typesafe.py              # TypeSafeGuardrailProvider (System One HTTP risk gate)

packages/harness/deerflow/config/
    guardrails_config.py     # GuardrailsConfig Pydantic model + singleton

packages/harness/deerflow/agents/middlewares/
    tool_error_handling_middleware.py  # Registers GuardrailMiddleware in chain

config.example.yaml          # Four provider options documented
tests/test_guardrail_middleware.py  # 25 tests
tests/test_typesafe_guardrail_provider.py  # TypeSafe provider + middleware integration
tests/blocking_io/test_typesafe_guardrail_provider.py  # Async path must stay off the loop
docs/GUARDRAILS.md           # This file
```
