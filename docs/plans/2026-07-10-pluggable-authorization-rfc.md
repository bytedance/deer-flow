<!-- Authored by @zhfeng, discussed in https://github.com/bytedance/deer-flow/issues/4063.
     Added to the PR per @WillemJiang's request for design tracking. -->

# RFC: Pluggable Fine-Grained Authorization

**Status:** Draft for feedback (responds to [#3462](https://github.com/bytedance/deer-flow/issues/3462)).
**Affects:** `backend/packages/harness/deerflow/authz/` (new), `backend/app/gateway/authz.py`, `backend/packages/harness/deerflow/guardrails/`, `backend/packages/harness/deerflow/agents/lead_agent/agent.py`, `backend/packages/harness/deerflow/client.py`, `backend/packages/harness/deerflow/subagents/executor.py`, `backend/app/gateway/services.py`, `config.example.yaml`.

> Maintainer guidance from the issue ([@WillemJiang](https://github.com/bytedance/deer-flow/issues/3462)):
> *"在开始实现之前，我们需要梳理相关的资源与权限的管理映射关系。具体工具调用和资源访问这块可以结合现有的 GuardrailProvider 来进行整合。另外建议在实现之前，做一个 RFC 的设计，方便大家的提反馈建议。"*
>
> This RFC does exactly that: (1) maps the resource × permission space, (2) integrates with `GuardrailProvider`, (3) is an RFC for feedback before any implementation.

## TL;DR

DeerFlow's authorization today is **authentication + ownership**: every authenticated user gets every API permission (`authz.py:144` hands all users `_ALL_PERMISSIONS`), and the only real authorization beyond login is thread ownership (`owner_check`) and a handful of hard-coded `require_admin_user()` routes. There is **no resource-level authorization** — no role can be told "you may not call `write_file`", "you may not use model X", or "you may not run sandbox code".

This RFC proposes a **single pluggable `AuthorizationProvider` Protocol** that is the policy brain for all fine-grained authz, enforced at **two layers** from one policy:

1. **Capability filtering (assembly-time)** — removes tools a role can never use *before* they are bound to the agent, so the model never sees them and `tool_search` can never promote them back (fail-closed).
2. **Execution authorization (run-time)** — a per-call allow/deny that reuses the existing `GuardrailMiddleware` as its enforcement point, catching dynamic resources and argument-based restrictions.

We ship one built-in provider — `RbacAuthorizationProvider` — that reads `config.yaml`, so it works out-of-the-box (no code), and enterprises with LDAP/OPA/OAuth-scopes replace it by setting one class path. This is a deliberate **hybrid of "Plan A" (pluggable hook) and "Plan B" (built-in RBAC)** from the issue thread: pluggable surface, batteries-included default.

The two hard problems raised in the thread — **dynamic resources** and the **filter-vs-deny security boundary** — are both resolved by the two-layer design (see §7).

---

## 1. Background: what exists today

### 1.1 Authentication (who you are) — solid

`AuthMiddleware` (`backend/app/gateway/auth_middleware.py:65`) is a strict session gate. It stamps `request.state.user` from one of three sources:

| Source | `system_role` | When |
|---|---|---|
| Session (JWT cookie → `User`) | `"admin"` or `"user"` | Browser / API callers |
| Internal (`X-DeerFlow-Internal-Token`) | `"internal"` | IM channel workers, scheduler |
| Auth-disabled | `"admin"` | `auth_disabled` mode |

The `User` model (`backend/app/gateway/auth/models.py:15`) carries `system_role: Literal["admin", "user"]`; the DB column is `String(16)` *deliberately*, with a comment: *"kept as plain string to avoid ALTER TABLE pain when new roles are introduced"* (`persistence/user/model.py:33`). **The schema is already forward-compatible with new roles.**

### 1.2 Authorization (what you can do) — a placeholder

- **Route-level:** `@require_permission("resource", "action")` (`authz.py:197`) checks `AuthContext.permissions`. But `_authenticate()` (`authz.py:131`) sets `permissions=_ALL_PERMISSIONS` for *every* authenticated user. The comment at `authz.py:143` admits it: *"In future, permissions could be stored in user record."* It is a placeholder.
- **Ownership:** `owner_check=True` (`authz.py:278`) scopes threads/runs to their owner via `ThreadMetaStore.check_access`. This is real and works.
- **Admin routes:** `require_admin_user()` (`deps.py:482`) hard-codes `system_role == "admin"` for skill / MCP / channel-management endpoints.
- **Tool-level:** **none.** No role can be restricted from any tool, model, skill, or sandbox.

### 1.3 The GuardrailProvider (the integration point)

The maintainer pointed here for good reason. `GuardrailProvider` (`deerflow/guardrails/provider.py:46`) is already a pluggable, class-path-loaded, per-call authorization hook:

```python
@runtime_checkable
class GuardrailProvider(Protocol):
    name: str
    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...
    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...
```

`GuardrailRequest` **already carries identity** — `user_id`, `user_role`, `oauth_provider`, `oauth_id`, `thread_id`, `run_id`, `is_subagent`, `tool_call_id` — populated from the run context by `GuardrailMiddleware._build_request` (`guardrails/middleware.py:42`). It is wired by `GuardrailMiddleware` (`guardrails/middleware.py:22`), which blocks denied calls with an error `ToolMessage`, fails closed by default, and audits to `RunJournal`. It is attached for both lead agent and subagents in `_build_runtime_middlewares()` (`agents/middlewares/tool_error_handling_middleware.py:202`).

**What guardrails cannot do alone:** they fire *per tool call*, at *execution time*. They cannot remove a tool from the schema the model sees, so a denied-but-visible tool is still a prompt-injection surface, and they cannot prevent `tool_search` from promoting a tool back into view. Guardrails are the **execution layer**; they are not a **capability/visibility layer**. This RFC makes them one half of a two-layer system.

### 1.4 The tool assembly pipeline (where visibility is decided)

All tools are merged in `get_available_tools()` (`deerflow/tools/tools.py:44`): config tools + built-ins + MCP (cached, hot-reloadable by mtime) + ACP, deduped by name. In the lead agent (`agents/lead_agent/agent.py:561`):

```python
raw_tools = get_available_tools(...)
filtered = filter_tools_by_skill_allowed_tools(raw_tools + extra_tools, skills, ...)  # name allowlist from skills
if non_interactive:
    filtered = [t for t in filtered if t.name not in _NON_INTERACTIVE_DISABLED_TOOL_NAMES]
final_tools, setup = assemble_deferred_tools(filtered, enabled=...)   # deferred catalog built from `filtered`
```

The skill filter (`skills/tool_policy.py:42`) is the **exact pattern** a role filter should mirror: a name-set intersection. Crucially, `assemble_deferred_tools` builds the `tool_search` catalog from the *post-filter* list (`tool_search.py:182`), so anything removed before this point can never be promoted back. **This is the fail-closed insertion point.**

Three agent build paths assemble tools, and they must all apply the same filter or the policy is bypassable:

| Path | File | Skill filter applied? |
|---|---|---|
| Lead agent | `agents/lead_agent/agent.py:562` | ✅ |
| Subagent | `subagents/executor.py:578` (`_apply_skill_allowed_tools`) | ✅ |
| `DeerFlowClient` | `client.py:259` | ❌ *(passes `tools` straight to `assemble_deferred_tools`)* |

The `DeerFlowClient` gap is a pre-existing inconsistency; any new authz filter must be applied on all three.

### 1.5 Identity flow into the run — reliable for the web, gap for channels

`inject_authenticated_user_context()` (`app/gateway/services.py:278`) stamps `user_id` / `user_role` / `oauth_provider` / `oauth_id` into `config["context"]`, which `GuardrailMiddleware` reads. Reliability:

| Caller path | `user_role` |
|---|---|
| Web / browser session | always populated (`"admin"`/`"user"`) |
| Auth-disabled | always `"admin"` |
| IM channel, **bound** connection | connection owner's `system_role` |
| IM channel, **unbound** / lookup miss | **`None`** (explicitly popped, `services.py:301`) |
| Scheduled task | owner's role if resolvable, else `None` |

So `user_role` reaches the tool layer reliably **except for unbound IM channels**, where it is `None`. Any role-based design must define behavior for the `None` case (see §8).

---

## 2. Goals & non-goals

### Goals

- **G1 — Pluggable.** A single `AuthorizationProvider` Protocol, class-path-loaded exactly like `GuardrailProvider` / models / sandbox (`resolve_variable`). Enterprises plug LDAP, OPA, OAuth-scopes, or home-grown RBAC; no fork required.
- **G2 — Out-of-the-box.** A built-in `RbacAuthorizationProvider` reads `config.yaml`; operators configure roles without writing Python.
- **G3 — Resource-level.** Covers tools, models, skills, sandbox, MCP, and routes — not just API permissions.
- **G4 — Defense-in-depth.** Visibility filter **and** execution deny, from one policy. Neither alone is sufficient against prompt injection or dynamic promotion.
- **G5 — Fail-closed.** Provider error, missing role, or unresolvable identity defaults to deny (configurable to fail-open for non-security contexts).
- **G6 — Non-breaking.** Default config (`authorization.enabled: false`) preserves today's behavior (all authenticated users get everything). Adoption is opt-in per deployment.

### Non-goals

- **Not** a full user-management UI (create/disable users, bulk ops). The issue asks for it; this RFC covers *authorization*, not identity lifecycle. User provisioning remains in the auth module.
- **Not** per-message/per-sender IM roles. Channel senders inherit the connection owner's role today; per-sender identity is a separate, larger effort (see §11 open questions).
- **Not** replacing ownership checks. `owner_check` stays; the provider *adds* role policy on top.
- **Not** re-implementing what `require_admin_user` already does for management routes. Those migrate to the provider in a later phase, but behavior is preserved.

---

## 3. Resource × Permission map

The maintainer's first ask: *“梳理相关的资源与权限的管理映射关系.”* Here is the full inventory.

| Resource | Identifier (`target`) | Actions | Current enforcement | Proposed enforcement |
|---|---|---|---|---|
| **Tool** (built-in / MCP / ACP) | tool name (`write_file`, `mcp__github__*`) | `call` | none | assembly filter + guardrail (§5) |
| **Model** | model name (`claude-sonnet-4-6`) | `list`, `use` | none | models router + `_resolve_model_name` |
| **Skill** | skill name | `activate`, `read`, `manage` | `manage` admin-gated; `activate` ungated | `SkillActivationMiddleware` + `describe_skill` + (keep admin gate) |
| **Sandbox** | (singleton) | `execute` | none (global on/off) | `SandboxMiddleware` |
| **MCP server** | server name | `use` (its tools), `manage` | `manage` admin-gated | tool filter covers `use`; keep admin gate for `manage` |
| **Thread** | thread_id | `read`, `write`, `delete` | `owner_check` ✅ | keep ownership; provider may add role policy |
| **Run** | run_id | `create`, `read`, `cancel` | ownership via thread | keep |
| **Route** | `resource:action` (`threads:read`) | (decorator) | `_ALL_PERMISSIONS` placeholder | provider-derived permissions (§6.3) |
| **Scheduled task** | task_id | `create`, `manage`, `execute` | router-level auth | provider |
| **Agent self-mutation** | `update_agent` tool | `call` | withheld from webhook channels ✅ | assembly filter (per-role deny) + keep webhook withhold |
| **Memory** | (owner-scoped) | `read`, `write` | owner-scoped ✅ | keep |

**The headline gap is the first four rows** — tools, models, skills, sandbox have **no** role gate today. Routes are nominally gated but effectively wide-open via `_ALL_PERMISSIONS`.

---

## 4. Proposed architecture

```
                         ┌─────────────────────────────┐
                         │   AuthorizationProvider      │  ← pluggable policy brain
                         │   (Protocol, class-path)     │     (built-in: RbacAuthorizationProvider)
                         └──────────────┬───────────────┘
                                        │ one policy
                   ┌────────────────────┴───────────────────────┐
                   ▼                                            ▼
   ┌───────────────────────────────┐         ┌──────────────────────────────────┐
   │ Layer 1: Capability filter     │         │ Layer 2: Execution authorization │
   │ (assembly-time, per build)     │         │ (run-time, per call)             │
   │                                │         │                                  │
   │ filter_resources(principal,    │         │ authorize(AuthzRequest)          │
   │   "tool", candidates) -> list  │         │   reuses GuardrailMiddleware     │
   │                                │         │   via a thin adapter             │
   │ removes tools before           │         │                                  │
   │ create_agent → invisible +     │         │ catches dynamic resources +      │
   │ unpromotable (fail-closed)     │         │ argument-based deny              │
   └───────────────────────────────┘         └──────────────────────────────────┘
```

**One policy, two enforcement layers.** Layer 1 answers *"what can this role's agent ever see?"* (static, batch, at build). Layer 2 answers *"may this specific call proceed?"* (dynamic, per-call, at execution). Both consult the same provider, so an enterprise's LDAP-backed provider is the single source of truth.

### Why two layers (not one)

- **Layer 1 only** (visibility filter) — vulnerable to any future code path that binds a tool after the filter runs (e.g. a new dynamic tool source). Also leaks nothing, but can't do per-argument policy.
- **Layer 2 only** (guardrail) — the model still *sees* every tool schema, so a denied tool is a prompt-injection target and consumes context. hata33's concern in the thread is exactly this.
- **Both** — Layer 1 removes tools the role can never use (clean schema, no injection surface, unpromotable); Layer 2 is the safety net for anything that slips through and the place for argument-based rules. **This is the design.**

---

## 5. The `AuthorizationProvider` Protocol

Lives in a new package `deerflow/authz/` (harness), mirroring `deerflow/guardrails/`.

```python
# deerflow/authz/provider.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

@dataclass
class Principal:
    """The actor. Built once per run from request.state.user + context."""
    user_id: str | None = None
    role: str | None = None              # system_role today; provider may map richer
    oauth_provider: str | None = None
    oauth_id: str | None = None
    channel_user_id: str | None = None   # IM sender (distinct from connection owner)
    is_internal: bool = False            # internal/system caller
    attributes: dict[str, Any] = field(default_factory=dict)  # extensible: dept, team, quota…

@dataclass
class AuthzRequest:
    principal: Principal
    resource: str        # "tool" | "model" | "skill" | "sandbox" | "mcp_server" | "thread" | "route" | …
    action: str          # "call" | "list" | "use" | "activate" | "execute" | "read" | "write" | "delete" | "manage"
    target: str          # resource id: tool name, model name, skill name, "route:threads:read", …
    context: dict[str, Any] = field(default_factory=dict)  # thread_id, run_id, tool args, …

@dataclass
class AuthzReason:
    code: str
    message: str = ""

@dataclass
class AuthzDecision:
    allow: bool
    reasons: list[AuthzReason] = field(default_factory=list)
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class AuthorizationProvider(Protocol):
    """Pluggable fine-grained authorization. No base class required.

    Loaded by class path via resolve_variable() — the same mechanism as
    GuardrailProvider, models, tools, and sandbox.
    """
    name: str

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        """Per-call decision. Feeds Layer 2 (execution) and route checks."""
        ...

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        ...

    # Layer 1: batch visibility filter. Default = "delegate to authorize per item"
    # (correct but slow). Providers with a static role→resource map override
    # this for O(1) assembly-time filtering and fail-closed visibility.
    def filter_resources(
        self, principal: Principal, resource_type: str, candidates: list[str],
    ) -> list[str]: ...
```

**Design notes:**

- `Principal` is built once per run (from `request.state.user` + context) and threaded to both layers, so providers don't re-resolve identity per call.
- `resource` / `action` / `target` are free-form strings, not an enum, so new resource types (and provider-specific resources) need no schema change. The built-in RBAC provider interprets them; custom providers define their own.
- `filter_resources` has a default (per-item `authorize`) so a provider that only implements `authorize` still works for Layer 1 — but the built-in RBAC provider overrides it for fail-closed static filtering.
- Mirrors `GuardrailProvider` exactly in shape (sync + async, `@runtime_checkable`, no base class, `name` attribute) so the mental model is uniform.

---

## 6. Integration with GuardrailProvider (the maintainer's ask)

### 6.1 The execution layer reuses `GuardrailMiddleware` verbatim

We do **not** write a new middleware. `GuardrailMiddleware` already does everything Layer 2 needs: per-call hook, fail-closed, audit, error `ToolMessage`, sync+async. We add one thin adapter that presents an `AuthorizationProvider` as a `GuardrailProvider`:

```python
# deerflow/authz/adapter.py
class GuardrailAuthorizationAdapter:
    """Adapt an AuthorizationProvider to the GuardrailProvider Protocol.

    Lets the existing GuardrailMiddleware enforce AuthorizationProvider
    decisions at tool-call time — no new middleware class required.
    """
    name = "authorization"

    def __init__(self, provider: AuthorizationProvider, *, resource_type: str = "tool",
                 action: str = "call"):
        self._provider = provider
        self._resource_type = resource_type
        self._action = action

    def _to_authz(self, gr: GuardrailRequest) -> AuthzRequest:
        return AuthzRequest(
            principal=Principal(
                user_id=gr.user_id, role=gr.user_role,
                oauth_provider=gr.oauth_provider, oauth_id=gr.oauth_id,
                is_internal=(gr.user_role == "internal"),
            ),
            resource=self._resource_type, action=self._action, target=gr.tool_name,
            context={"thread_id": gr.thread_id, "run_id": gr.run_id,
                     "tool_call_id": gr.tool_call_id, "tool_input": gr.tool_input,
                     "is_subagent": gr.is_subagent},
        )

    def evaluate(self, request):  # -> GuardrailDecision
        d = self._provider.authorize(self._to_authz(request))
        return GuardrailDecision(allow=d.allow,
                                 reasons=[GuardrailReason(code=r.code, message=r.message) for r in d.reasons],
                                 policy_id=d.policy_id, metadata=d.metadata)

    async def aevaluate(self, request):
        d = await self._provider.aauthorize(self._to_authz(request))
        return GuardrailDecision(allow=d.allow, reasons=[...], policy_id=d.policy_id, metadata=d.metadata)
```

### 6.2 Auto-wiring in `_build_runtime_middlewares`

In `agents/middlewares/tool_error_handling_middleware.py:202` (the existing guardrail block), add a parallel block: when `authorization.enabled` and no explicit `guardrails.provider` is set, auto-attach `GuardrailMiddleware(GuardrailAuthorizationAdapter(authz_provider))`. Users who want an **external** guardrail (OAP) *and* role filtering configure both sections; users who want only RBAC configure only `authorization`. The built-in `RbacAuthorizationProvider` also natively implements the `GuardrailProvider` methods, so it can be set directly as `guardrails.provider` too — the adapter is the general escape hatch.

### 6.3 Route-level: replacing `_ALL_PERMISSIONS`

`AuthContext.permissions` is today a flat constant list. We make it **provider-derived**: `_authenticate()` (`authz.py:131`) asks the provider `authorize(principal, "route", action, target=f"{resource}:{action}")` for each registered permission (cached per-request). `@require_permission` is unchanged. Behavior with `authorization.enabled: false` is identical to today (all permissions granted). This is a phased migration (§9) — we don't touch every route on day one.

---

## 7. The two hard problems (resolved)

### 7.1 Dynamic resources

| Dynamic path | Why it's a problem | How the two-layer design handles it |
|---|---|---|
| **MCP hot-reload** | New MCP tools appear after agent build (cache mtime check, `mcp/cache.py:31`) | Tools are read at **build time** per run (`get_available_tools`). A newly-added MCP tool appears on the *next* run, where Layer 1 filters it. Mid-run appearance doesn't happen within a built graph. |
| **`tool_search` deferred promotion** | A hidden tool can be promoted back into the schema mid-run | Layer 1 runs **before** `assemble_deferred_tools` (`agent.py:565`). Filtered-out tools never enter the `DeferredToolCatalog` (`tool_search.py:182`), so they can **never** be promoted. Fail-closed by construction. |
| **`McpRoutingMiddleware` auto-promotion** | Keyword-based auto-promotion could surface a tool | Same: the catalog is post-filter, so auto-promotion can only pick from already-allowed tools. |
| **Skill runtime discovery** (`describe_skill`, `/skill` activation) | Skills can be discovered/activated mid-run | Skills are a *resource type* in the provider. `SkillActivationMiddleware` calls `authorize(principal, "skill", "activate", target=skill_name)` before injecting the skill. Denied skills never load. |
| **Argument-based rules** (e.g. `write_file` only to `/tmp`) | Static filter can't see args | Layer 2 (`authorize` with `context.tool_input`) handles this. The tool stays visible (it's allowed in principle) but specific calls are denied. |

**Principle:** Layer 1 = "what you can *ever* see" (static, fails closed). Layer 2 = "may *this* call proceed" (dynamic, argument-aware). Any resource that is dynamic-only (appears after build) is caught by Layer 2; any resource known at build is removed by Layer 1 and made unpromotable.

### 7.2 The filter-vs-deny security boundary

hata33's concern: *"只做'过滤可见性'不做'拦截执行', prompt injection 仍能让模型调被隐藏的工具."*

This is only true if filtering happens at the **visibility** layer (`DeferredToolFilterMiddleware`, which hides schemas but doesn't remove tools from the bound set). This RFC filters at the **assembly** layer — the tool is removed from `final_tools` passed to `create_agent`, so it is *not bound to the model at all*. The model cannot call a tool it was never given.

The residual risk — a tool that *is* allowed at assembly (visible) but should be denied for a specific call — is exactly what Layer 2 (guardrail) catches. **Filter + deny, both enforced, from one policy.** Neither is bypassable alone:

- A tool removed at assembly: not bound → uncallable → no injection surface.
- A tool visible but role-denied: guardrail blocks the call → uncallable.
- Provider error: `fail_closed=true` → deny.

---

## 8. Identity prerequisites (close the `user_role` gap)

Role-based authz is only as good as the role reaching the provider. Today `user_role` is `None` for unbound IM channels (`services.py:301`). We close this in `inject_authenticated_user_context` and a new `Principal` builder:

1. **`default_role` config** (`authorization.default_role`, default `"user"`): when `user_role` is `None`, the `Principal.role` falls back to this. Unbound channels get a defined, restrictable role instead of an implicit "admin-by-accident."
2. **`Principal` is built once per run** from `request.state.user` + context, in `services.py` alongside `inject_authenticated_user_context`, and stored on the run context as `principal` (alongside the existing `user_id`/`user_role`). Both layers read it.
3. **Role taxonomy lives in config, not the schema.** `User.system_role` stays `Literal["admin","user"]` for the *built-in* identity provider, but the DB column is already `String(16)`. The RBAC config defines `guest`, `operator`, etc.; a custom identity provider can mint richer roles. No schema migration required — by design (`persistence/user/model.py:33`).
4. **`internal` role** (channel workers/scheduler) is a real role in the RBAC config, not a special case. The provider decides what `internal` may do (typically: call tools on behalf of the owner, but no `update_agent`, no admin routes).

---

## 9. Phased rollout

Each phase is independently shippable and behind `authorization.enabled` (default `false` = today's behavior).

**Phase 0 — Foundations (no behavior change).**
- New `deerflow/authz/` package: `provider.py` (Protocol + dataclasses), `principal.py` (builder), `adapter.py`.
- `Principal` built in `services.py`, stored on run context.
- `default_role` config; close the `user_role=None` gap.
- `RbacAuthorizationProvider` skeleton + `AuthorizationConfig` (AppConfig section, singleton, live-reload — mirrors `guardrails_config.py`; **not** in `STARTUP_ONLY_FIELDS`).

**Phase 1 — Tool authorization (highest value, lowest risk).**
- Layer 1: `filter_tools_by_authorization(tools, principal)` applied at `agent.py:562`, `executor.py:578`, **and `client.py:259`** (fixing the existing skill-filter gap there too).
- Layer 2: auto-wire `GuardrailAuthorizationAdapter` in `_build_runtime_middlewares`.
- Built-in RBAC provider covers `tool:call` with allow/deny lists + `*` wildcard.
- Tests: per-role tool visibility, deferred-promotion fail-closed, prompt-injection-can't-call-removed-tool, subagent inheritance.

**Phase 2 — Route-level migration.**
- Replace `_ALL_PERMISSIONS` with provider-derived permissions in `_authenticate()` (per-request cached).
- `@require_permission` unchanged. **Keep `require_admin_user()` for management endpoints** (skills/MCP/channel config) — the project already settled on admin-gating there (GHSA-4693 → #3855/#3425; see §12 Q6). Only ordinary routes migrate.

**Phase 3 — Models, skills, sandbox.**
- `models.py:40` `list_models` filters by `authorize("model","list")`; `_resolve_model_name` checks `authorize("model","use")` (deny → fall back to an allowed default, not error, to avoid breaking runs).
- `SkillActivationMiddleware` + `describe_skill` gate on `authorize("skill","activate")`.
- `SandboxMiddleware` gates on `authorize("sandbox","execute")` (deny → tool returns a "sandbox not permitted for your role" error message, not a crash).

**Phase 4 (optional) — Frontend.** Surface the user's effective permissions so the UI can hide disabled models/tools/menus. Out of scope for the backend RFC; noted for completeness.

---

## 10. Config schema

Mirrors the `guardrails` section exactly (`config.example.yaml:1786`):

```yaml
# ============================================================================
# Authorization Configuration
# ============================================================================
# Optional fine-grained, role-based authorization. When enabled, a pluggable
# AuthorizationProvider decides what each role may call/use/see. Two layers
# are enforced from one policy: assembly-time capability filtering (tools the
# agent can never see) and run-time execution deny (reuses GuardrailMiddleware).
# See docs/plans/2026-07-10-pluggable-authorization-rfc.md.

authorization:
  enabled: false
  fail_closed: true            # block on provider error / unresolved identity
  default_role: user           # applied when user_role is None (unbound IM channels)
  provider:
    use: deerflow.authz.rbac:RbacAuthorizationProvider
    config:
      # role -> resource policy. "*" = all. Omitted resource type = unaffected.
      roles:
        admin:
          tools:  {allow: "*"}
          models: {allow: "*"}
          sandbox: {allow: true}
          skills: {allow: "*"}
        user:
          tools:  {allow: "*", deny: ["update_agent"]}
          models: {allow: ["claude-sonnet-4-6", "gpt-4o"]}
          sandbox: {allow: true}
          skills: {allow: "*"}
        guest:
          tools:  {allow: ["web_search", "read_file"]}
          models: {allow: ["gpt-4o-mini"]}
          sandbox: {allow: false}
          skills: {allow: []}
        internal:               # IM channel workers / scheduler
          tools:  {allow: "*", deny: ["update_agent"]}
          models: {allow: ["claude-sonnet-4-6"]}
          sandbox: {allow: true}
      # Optional: derive role from Principal.attributes instead of system_role.
      # Default: role = principal.role (i.e. User.system_role).
      # role_mapping:
      #   source: attribute      # or "system_role"
      #   attribute: department
      #   map: {eng: admin, cs: user}

# When authorization.enabled and guardrails.provider is unset, the authorization
# provider is auto-wired as the tool-call guardrail. To use an external guardrail
# (e.g. OAP) AS WELL, set guardrails.provider explicitly; both then enforce.
```

**Built-in provider semantics:**
- `allow: "*"` = all tools/models; `allow: [list]` = allowlist; omitted = inherit parent / allow.
- `deny` always wins over `allow` (defense-in-depth: a deny can never be overridden).
- Unknown role → `default_role` → if still unknown → `fail_closed` decides.
- `sandbox: {allow: false}` makes `SandboxMiddleware` deny execution for that role.
- Live-reloadable: `AuthorizationConfig` is a singleton reloaded by `get_app_config()`'s signature check, and the provider is re-instantiated per agent build (same as guardrails) — **not** in `STARTUP_ONLY_FIELDS`.

---

## 11. Alternatives considered

| Approach | From | Verdict |
|---|---|---|
| **Plan A** — minimal filter hook only (`ResourcePermissionProvider.filter_tools`) | hata33 | Adopted as Layer 1, but **insufficient alone** (no execution deny → injection risk; no non-tool resources). |
| **Plan B** — built-in config RBAC only | hata33 | Adopted as the *built-in provider*, but **insufficient alone** (enterprises still need to plug LDAP/OPA; no execution layer). |
| **Extend `GuardrailProvider` with `filter_tools`** | — | Rejected: bloats the OAP-aligned guardrail Protocol and couples visibility (per-build) with execution (per-call) semantics. Keep guardrails minimal; add a sibling Protocol. |
| **A new `AuthorizationMiddleware`** (parallel to guardrail) | — | Rejected: duplicates `GuardrailMiddleware`'s fail-closed/audit/error-message logic. Reuse guardrail via the adapter instead. |
| **Store permissions in the `User` row** | `authz.py:143` comment | Rejected for the pluggable case: a DB column per permission doesn't scale to enterprise LDAP/OPA. The provider *can* be DB-backed if a deployment wants that — it's an implementation choice, not the architecture. |

**This RFC = Plan A's pluggability + Plan B's batteries-included default + the two-layer enforcement that neither alone provides.**

> **Prior-art note.** The choice to add a sibling `AuthorizationProvider` rather than extend `GuardrailProvider` is not second-guessing the guardrail design - it is what that design explicitly deferred. PR [#3665](https://github.com/bytedance/deer-flow/pull/3665) (which added `user_role`/`user_id` to `GuardrailRequest`) states its scope as: *"保持 Guardrail 的职责边界不变：不新增 policy engine、RBAC 系统、governance 子系统"* ("keeps the guardrail boundary: adds no policy engine, RBAC system, or governance subsystem"). The guardrail is the *execution enforcement point*; the RBAC brain that #3665 deliberately left out is what this RFC adds - and it reuses the guardrail as that enforcement point (§6).

---

## 12. Open questions for feedback

1. **Role for unbound IM channels.** Default `default_role: user`, or a dedicated `guest`-like role? Unbound channels today have no owner in the user DB; should they be allowed to run at all under `authorization.enabled`, or require a bound connection?
2. **`internal` role scope.** Should `internal` (channel workers) be a fully-configurable role, or keep special-cased bypass semantics for backward compat with existing channel deployments?
3. **Model-deny behavior.** When a role requests a denied model, fall back to an allowed default (graceful) or hard-deny the run (strict)? Proposal: graceful fallback + audit, but strict is defensible.
4. **Argument-based tool rules.** In scope for the built-in RBAC provider (e.g. `write_file` path restrictions), or left to custom providers / OAP? Proposal: out of scope for v1 built-in; the `authorize` hook supports it for custom providers.
5. **Per-sender IM roles.** Defer entirely (separate RFC), or lay groundwork now via `Principal.channel_user_id`? Proposal: lay the `Principal` groundwork (already in the dataclass), defer the policy.
6. **Route migration cadence.** Migrate the `_ALL_PERMISSIONS` placeholder to provider-derived permissions, but **keep `require_admin_user()` hard-coded for management endpoints** (skills/MCP/channel config). Precedent: GHSA-4693 (#2996) proposed `@require_permission` for the MCP/memory/skills routers and was *closed*; the merged fix (#3855, #3425) chose `require_admin_user` instead. So for management surfaces, the project has already settled on admin-gating - this RFC respects that and only migrates ordinary routes. Proposal: Phase 2 migrates `_ALL_PERMISSIONS` only; management endpoints stay admin-gated (the provider may *additionally* be consulted, but `admin` remains the floor).

---

## 13. Test strategy (TDD, per AGENTS.md)

Backend tests in `backend/tests/`. Minimum coverage for Phase 1:

- `test_authz_provider_protocol.py` — Protocol conformance, `@runtime_checkable`, default `filter_resources` delegates to `authorize`.
- `test_rbac_authorization_provider.py` — per-role allow/deny, `*` wildcard, `deny` wins, unknown role → `default_role` → `fail_closed`, all resource types.
- `test_authz_tool_filter.py` — Layer 1: tools removed at assembly on all three build paths (lead / subagent / `DeerFlowClient`); filtered tools absent from `DeferredToolCatalog` (fail-closed promotion).
- `test_authz_guardrail_adapter.py` — Layer 2: adapter deny → `GuardrailMiddleware` returns error `ToolMessage`; `user_role` flows from context; `fail_closed` on provider error.
- `test_authz_prompt_injection.py` — a tool removed at assembly cannot be invoked even when the prompt tries to call it (the security-boundary guarantee).
- `test_authz_principal.py` — `user_role=None` → `default_role`; internal caller; subagent inherits principal.
- Extend `test_app_config_reload.py` — `authorization` section live-reloads; not in `STARTUP_ONLY_FIELDS` drift test.

---

## 14. References

- Issue: [#3462](https://github.com/bytedance/deer-flow/issues/3462)
- Existing design: `backend/docs/AUTH_DESIGN.md`, `backend/docs/GUARDRAILS.md`
- Guardrail provider: `backend/packages/harness/deerflow/guardrails/provider.py`
- Guardrail middleware: `backend/packages/harness/deerflow/guardrails/middleware.py`
- Tool assembly: `backend/packages/harness/deerflow/agents/lead_agent/agent.py:561`, `deerflow/tools/tools.py:44`, `deerflow/tools/builtins/tool_search.py:190`
- Skill filter pattern: `backend/packages/harness/deerflow/skills/tool_policy.py:42`
- Identity injection: `backend/app/gateway/services.py:278`
- Config resolution: `backend/packages/harness/deerflow/reflection/resolvers.py`, `deerflow/config/guardrails_config.py`, `deerflow/config/reload_boundary.py`
- Middleware wiring: `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py:154`

---

## 15. Related work & prior art (upstream issues & PRs)

A search of `bytedance/deer-flow` confirms **no RBAC implementation exists**; RBAC is a recognized but unowned roadmap item. This RFC situates itself in the prior work below.

### Direct lineage - what this RFC builds on

- **[#1669](https://github.com/bytedance/deer-flow/issues/1669)** - Q2 Roadmap. Lists *"Implement Role-Based Access Control (RBAC)"* under "Security and Permission Strengthening 🔥🔥🔥🔥" (top priority), referencing #1721 and #3506. **This is the roadmap slot #3462 and this RFC fill.**
- **[#1213](https://github.com/bytedance/deer-flow/issues/1213)** (closed) - the original RFC proposing OAP `before_tool_call` authorization for tools/skills. The `GuardrailProvider`/`GuardrailMiddleware` system is the implemented result. **Our RFC is the next layer on top of that lineage.**
- **[#3664](https://github.com/bytedance/deer-flow/issues/3664) / PR [#3665](https://github.com/bytedance/deer-flow/pull/3665)** (merged) - added `user_id`/`user_role`/`oauth_*`/`run_id`/`tool_call_id` to `GuardrailRequest` and wired Gateway -> context -> middleware. **This is the plumbing our Layer 2 relies on.** Critically, #3665 explicitly scoped guardrails to *not* be an RBAC system (quoted in §11) - the RBAC brain is the deliberately-deferred gap this RFC adds.
- **[#3672](https://github.com/bytedance/deer-flow/issues/3672) / PR [#3839](https://github.com/bytedance/deer-flow/pull/3839)** (merged) - propagate the bound connection owner's `role`/`oauth` into the guardrail context for IM/internal-auth runs. Documents the exact `user_role=None` gap for unbound channels ("If owner lookup fails, the run continues with role/oauth attribution unset") **that our `default_role` (§8) closes.**
- **[#2507](https://github.com/bytedance/deer-flow/issues/2507) / RFC PR [#2504](https://github.com/bytedance/deer-flow/pull/2504)** (closed) - "Deferred MCP tools can execute before `tool_search` promotion." Proposed direction: *"Add an execution gate before tool execution."* This became `DeferredToolFilterMiddleware.wrap_tool_call`'s execution deny. **Our §7.2 two-layer design is consistent with this precedent** - the project already chose "execution gate" as the pattern for the deferred capability boundary.

### Security precedents - the gaps that motivate #3462

- **GHSA-4693 / [#2996](https://github.com/bytedance/deer-flow/pull/2996)** (closed) - proposed `@require_permission` for MCP/memory/skills routers after any authenticated user could RCE via MCP stdio config injection. The merged fix was **[#3855](https://github.com/bytedance/deer-flow/pull/3855)** (admin-gate skills) + **[#3425](https://github.com/bytedance/deer-flow/pull/3425)** (harden MCP config endpoint) - i.e. the project chose `require_admin_user` over fine-grained permissions for management surfaces. **This RFC respects that precedent** (§9 Phase 2, §12 Q6): management endpoints stay admin-gated; only ordinary routes migrate to the provider.
- **[#1646](https://github.com/bytedance/deer-flow/issues/1646)**, **[#1648](https://github.com/bytedance/deer-flow/issues/1648)**, **[#2531](https://github.com/bytedance/deer-flow/issues/2531)** (open) - unauthenticated/over-broad MCP config + memory disclosure. Further evidence that resource-level authz is the open gap.

### Complementary (distinct axis, not overlapping)

- **[#2470](https://github.com/bytedance/deer-flow/issues/2470)** (open RFC) - "Pluggable auth *providers* with request-level hook." This is **authentication** (trusted-header/gateway SSO via an `AuthProvider` extension), and its non-goal #4 explicitly excludes authorization policy. **Complementary, not overlapping** - it decides *who you are*; this RFC decides *what you can do*.
- **[#3322](https://github.com/bytedance/deer-flow/issues/3322)**, **[#3476](https://github.com/bytedance/deer-flow/issues/3476)**, **[#2761](https://github.com/bytedance/deer-flow/issues/2761)** (open) - **per-user credential** isolation (per-user MCP tokens, user connectors for GitHub/Linear, per-user model API keys). This is a *different axis* from per-*role* tool authorization: per-user creds = "act as this user on external service X"; this RFC = "may role Y use tool/model Z at all." The `Principal` (§5) and provider hook could eventually support per-user policies, but per-user credential plumbing is a separate effort.
- **[#1721](https://github.com/bytedance/deer-flow/issues/1721)** (closed RFC) - the original user-authentication module design (the `AUTH_DESIGN.md` lineage). Scoped RBAC out as a non-goal ("当前用户角色只有 admin 和 user，尚未实现细粒度 RBAC"). **This RFC is the RBAC that #1721 deferred.**

### Other relevant security work

- **[#3630](https://github.com/bytedance/deer-flow/issues/3630) / [#3662](https://github.com/bytedance/deer-flow/pull/3662) / [#3661](https://github.com/bytedance/deer-flow/pull/3661)** (merged) - prompt-injection input sanitization + role isolation via system-message injection. Orthogonal defense; our Layer 1 (remove tools from the bound set) is the complementary capability-layer defense.
- **[#3837](https://github.com/bytedance/deer-flow/pull/3837)** (merged) - persist guardrail interventions as run events. Our Layer 2 reuses this audit trail for free.
- **[#3929](https://github.com/bytedance/deer-flow/issues/3929)** (open) - sandbox NodePort->ClusterIP (same author family of security hardening RFCs).

**Net takeaway:** the upstream has spent real effort plumbing identity into the guardrail execution point (#3665, #3839) and has explicitly deferred the RBAC policy brain. The two-layer design in this RFC is the natural next step the prior work points at - not a competing or redundant proposal.


