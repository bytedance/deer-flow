## 1. Core hook — `useDeepLinkChat`

- [x] 1.1 Create `src/components/workspace/chats/use-deep-link-chat.ts`
- [x] 1.2 Define reserved param keys: `RESERVED_PARAMS = ["prompt", "auto_send", "source", "context"]`
- [x] 1.3 Implement reserved param parsing with per-key validation:
  - `prompt`: trim, max 2000 chars, strip control chars, empty→null
  - `auto_send`: return true only for exactly `"1"`
  - `source`: max 100 chars, trim
  - `context`: max 500 chars, trim
- [x] 1.4 Implement passthrough param collection: iterate `searchParams.entries()`, skip reserved keys, validate each value (trim, max 500 chars, strip control chars, skip empty)
- [x] 1.5 Use `useRef` sentinel to fire exactly once per mount
- [x] 1.6 Only activate when `isNewThread === true` (return all nulls/empty for existing threads)
- [x] 1.7 Return `{ prompt, autoSend, source, context, passthroughParams }`
- [x] 1.8 Export from `src/components/workspace/chats/index.ts`

## 2. Integrate into general chat page

- [x] 2.1 In `src/app/workspace/chats/[thread_id]/page.tsx`, call `useDeepLinkChat()`
- [x] 2.2 When `autoSend && prompt` and `isNewThread`: call `sendMessage` once with `additionalKwargs: { source, context, ...passthroughParams }`
- [x] 2.3 When `prompt && !autoSend`: pre-fill input via `usePromptInputController`
- [x] 2.4 Log `source` to console when present: `[DeepLink] source=<value>`

## 3. Integrate into agent chat page

- [x] 3.1 In `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`, call `useDeepLinkChat()`
- [x] 3.2 When `autoSend && prompt`: send with deep-link `prompt` as message text and all params in `additionalKwargs`, skip agent `auto_start`
- [x] 3.3 When `autoSend && !prompt && (passthroughParams non-empty)`: send using agent's first `auto_start` starter prompt as text, with passthrough params in `additionalKwargs`
- [x] 3.4 When `autoSend && !prompt && (passthroughParams empty)`: fall back to agent's configured `auto_start` starter
- [x] 3.5 When `prompt && !autoSend`: pre-fill input, show agent welcome as normal
- [x] 3.6 Ensure deep-link and agent auto_start don't double-fire (single `useRef` guard shared between both)

## 4. Tests

- [x] 4.1 Create `tests/unit/components/workspace/chats/use-deep-link-chat.test.ts`:
  - Reserved params: normal pre-fill, auto-send, source+context in additionalKwargs
  - Passthrough: single param, multiple params, unknown params go through
  - Validation: empty prompt, whitespace-only, >2000 truncation, >500 passthrough truncation, auto_send="true"→false, control chars stripped
  - Existing thread: all params ignored (returns nulls/empty)
  - Edge: empty searchParams → no-op, reserved-only (no passthrough), passthrough-only (no reserved)
- [x] 4.2 Run `pnpm check && pnpm test` to verify no regressions

## 5. Manual smoke tests

- [x] 5.1 General chat auto-send: `/workspace/chats/new?prompt=hello&auto_send=1&source=smoke-test` → auto-sends
- [x] 5.2 Agent passthrough: `/workspace/agents/fault-diagnosis--pump/chats/new?device_id=P-203A&component_id=Bearing-1&diagnosis_date=2026-06-01&diagnosis_hour=8&auto_send=1` → opens pump diagnosis with structured params
- [x] 5.3 Monitoring agent: `/workspace/agents/monitoring-analysis/chats/new?device_id=V-401&analysis_type=trend&auto_send=1` → auto-sends with params
- [x] 5.4 Defect closure: `/workspace/agents/defect-closure/chats/new?ticket_id=TCKT-0042&action=view&auto_send=1` → auto-sends with params

## 6. Agent SOUL.md updates (independent follow-up per agent)

- [x] 6.1 `fault-diagnosis--pump/SOUL.md`: add rule — if `additional_kwargs` has all 4 diagnosis params, validate them and skip GenUI forms, go directly to rule execution
- [x] 6.2 `fault-diagnosis--rotating/SOUL.md`: same pattern
- [x] 6.3 `fault-diagnosis--reciprocating/SOUL.md`: same pattern
- [x] 6.4 `monitoring-analysis/SOUL.md`: read `device_id`, `analysis_type`, time range from `additional_kwargs` when present
- [x] 6.5 `defect-closure/SOUL.md`: read `ticket_id`, `action` from `additional_kwargs` when present
- [x] 6.6 `ai-report--daily/SOUL.md`: read `template_id`, `date` from `additional_kwargs` when present
