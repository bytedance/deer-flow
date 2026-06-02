## Context

DeerFlow uses Next.js 16 App Router. Chat pages live at two route patterns:

- General chat: `/workspace/chats/[thread_id]` (`src/app/workspace/chats/[thread_id]/page.tsx`)
- Agent chat: `/workspace/agents/[agent_name]/chats/[thread_id]` (`src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`)

Existing URL parameter handling: `useSpecificChatMode()` reads `?mode=skill`, `useThreadChat()` reads `?mock=true`, agent pages support `auto_start` starters from agent config only.

### Agent Landscape

| Category | Agents | Needs from deep-link |
|----------|--------|---------------------|
| Fault diagnosis | pump, rotating, reciprocating | `device_id`, `component_id`, `diagnosis_date`, `diagnosis_hour` |
| Monitoring & anomaly | monitoring-analysis, anomaly-judgment | `device_id`, `start_time`, `end_time`, `analysis_type` |
| AI reports | daily, weekly, monthly, diagnosis, trend, closure, custom, failure-analysis | `template_id`, `date`, `device_id`, `org_id` |
| Defect closure | defect-closure | `ticket_id`, `action` |
| CRM | crm-analyst | `query_type`, `date_range`, `product_category` |

### Core Insight

Hardcoding each agent's parameters in the frontend is a maintenance dead-end. Instead, **the frontend should be a transparent pipe**: a small set of reserved params gets special handling, and everything else passes through verbatim to the agent via `additionalKwargs`. Each agent's SOUL.md is the authoritative source for what params it accepts and how it uses them.

## Goals / Non-Goals

**Goals:**
- Define a minimal set of reserved URL parameters (`prompt`, `auto_send`, `source`, `context`)
- All other query parameters automatically pass through to `sendMessage`'s `additionalKwargs`
- Generic enough to support every existing agent and future agents with zero frontend changes
- Validate and sanitize all URL-originated input at the boundary
- Reuse existing patterns (`useSpecificChatMode`, `additionalKwargs`, agent auto-start)

**Non-Goals:**
- No deep-linking into existing threads (only `new` threads)
- No backend API changes
- No agent-specific validation logic in frontend — that belongs in each agent's SOUL.md
- No structured JSON-in-URL encoding

## Decisions

### Decision 1: Reserved params + transparent passthrough

**Chosen**: 4 reserved parameters with special handling. Everything else passes through.

**Reserved params** (consumed by frontend):

| Parameter   | Type   | Max    | Behavior |
|-------------|--------|--------|----------|
| `prompt`    | string | 2000   | Pre-fills or auto-sends as message text |
| `auto_send` | `"1"`  | —      | If exactly `"1"`, sends immediately |
| `source`    | string | 100    | Passed in `additionalKwargs`, logged to console |
| `context`   | string | 500    | Passed in `additionalKwargs` for round-tripping |

**Passthrough params** (all other keys):

Any query parameter NOT in the reserved set is collected into `additionalKwargs` with generic validation (trim whitespace, max 500 chars per value, strip control chars). Invalid values are silently dropped.

```ts
// Example: URL = /workspace/agents/fault-diagnosis--pump/chats/new
//   ?device_id=P-203A&component_id=Bearing-1
//   &diagnosis_date=2026-06-01&diagnosis_hour=8
//   &auto_send=1&source=grafana-alerting

// Reserved params → special handling
// Passthrough params → additionalKwargs:
{
  device_id: "P-203A",
  component_id: "Bearing-1",
  diagnosis_date: "2026-06-01",
  diagnosis_hour: "8",
}
```

**Why**: Adding a new agent or a new parameter to an existing agent requires zero frontend changes. The contract is between the external system (URL builder) and the agent (SOUL.md). The frontend is just plumbing.

**Alternatives considered**:
- Agent-specific parameter whitelists in frontend → rejected: unbounded maintenance burden as agents evolve
- JSON blob encoding → rejected: hard to construct by hand, harder to debug
- Per-agent route patterns → rejected: URL routing shouldn't couple to agent parameter schemas

### Decision 2: All passthrough params go into `additionalKwargs`

The data flows through the existing LangGraph SDK message pipeline:

```
URL params → useDeepLinkChat parses & validates
  → sendMessage(threadId, { text: prompt, files: [] }, { agent_name }, {
      additionalKwargs: { source, context, ...allPassthroughParams }
    })
  → backend LangGraph run
  → agent reads message.additional_kwargs in the first human message
  → agent validates and acts
```

No new API calls, no new data channels. The LangGraph SDK already round-trips `additional_kwargs` on messages.

### Decision 3: One hook — `useDeepLinkChat`

Create `useDeepLinkChat()` in `src/components/workspace/chats/use-deep-link-chat.ts`.

The hook:
1. Reads all query params from `useSearchParams()`
2. Separates reserved params from passthrough params
3. Validates each with generic rules (length, control chars)
4. Returns `{ prompt, autoSend, source, context, passthroughParams }`
5. Uses a `useRef` sentinel to fire exactly once per mount
6. Only activates when `isNewThread === true`

Why separate from `useSpecificChatMode`: that hook is skill-specific (hardcoded i18n text, `mode=skill` check). Deep-link is a different concern.

### Decision 4: Generic validation for passthrough params

All passthrough params share the same validation:
- Trim whitespace
- Max 500 chars per value
- Strip control characters (`\x00`–`\x1F` except space)
- Skip empty values after trimming
- Silently drop invalid values — never crash

Agent-specific semantic validation (regex for device_id, date format, enum values) belongs in the agent's SOUL.md, not the frontend. This keeps the passthrough truly generic.

### Decision 5: auto_send precedence

When `auto_send=1`:
1. If `prompt` is present → use deep-link prompt, skip agent auto_start
2. If only passthrough params (no prompt) → use agent's first `auto_start` starter prompt as message text, append passthrough params
3. If neither prompt nor agent auto_start → do nothing (don't send empty message)

### Decision 6: Parameter naming convention

- Reserved params: lowercase snake_case (matching existing `auto_send` style)
- Passthrough params: any valid query param name. Recommend snake_case for consistency with `additional_kwargs` convention.

## Cross-Agent Deep-Link Examples

```
# Fault diagnosis — alert platform
/workspace/agents/fault-diagnosis--pump/chats/new
  ?device_id=P-203A&component_id=Bearing-1
  &diagnosis_date=2026-06-01&diagnosis_hour=8
  &auto_send=1&source=grafana-alerting

# Monitoring analysis — dashboard deep-link
/workspace/agents/monitoring-analysis/chats/new
  ?device_id=V-401&analysis_type=trend
  &start_time=2026-05-25T00:00:00&end_time=2026-06-01T23:59:59
  &auto_send=1&source=monitoring-dashboard

# Defect closure — ticket system
/workspace/agents/defect-closure/chats/new
  ?ticket_id=TCKT-0042&action=view
  &auto_send=1&source=jira

# Daily report — scheduling system
/workspace/agents/ai-report--daily/chats/new
  ?template_id=daily-equipment-report&date=2026-06-01
  &auto_send=1&source=report-scheduler

# CRM — ERP system
/workspace/agents/crm-analyst/chats/new
  ?query_type=service_events&date_range=last_30d
  &auto_send=1&prompt=查询服务事件并检测异常模式
  &source=sap-erp

# General chat with just a prompt (no agent)
/workspace/chats/new
  ?prompt=分析全厂本月设备可用率&auto_send=1&source=portal
```

## Risks / Trade-offs

- **Prompt injection via URL**: Crafted URLs could contain malicious prompts. Mitigation: AI's guardrails still apply. No elevated privileges.
- **Spam**: URLs could generate many threads. Mitigation: Auth required, API rate limiting.
- **Parameter leakage**: URL params visible in browser history. Mitigation: Accepted trade-off — operational parameters are not secrets.
- **Agent SOUL.md must be updated to consume params**: If an agent doesn't read `additional_kwargs`, params are silently ignored. This is graceful degradation — the agent simply follows its normal flow. Each agent team owns their SOUL.md updates.
- **No type safety for passthrough params**: Values are always strings (URL limitation). Agent SOUL.md must parse/coerce types as needed (e.g., `"8"` → integer, `"true"` → boolean).

## Migration Plan

1. Implement `useDeepLinkChat` hook — generic passthrough design
2. Integrate into both chat page components
3. Deploy frontend — no behavior change (params are optional)
4. Per-agent SOUL.md updates (independent workstreams):
   - Fault diagnosis agents: read `device_id`, `component_id`, `diagnosis_date`, `diagnosis_hour` → skip GenUI forms
   - Monitoring agents: read `device_id`, `analysis_type`, time range → auto-configure analysis
   - Report agents: read `template_id`, `date` → auto-generate report
   - Defect closure: read `ticket_id` → auto-navigate to ticket
   - CRM: read `query_type`, `date_range` → auto-execute query

No rollback plan needed — removing URL params falls back to normal chat.
