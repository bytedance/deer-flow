# Plan: Subagent Card Runtime Metadata

> Source PRD: Conversation request approved on 2026-07-10 — show live token usage and the effective LLM name on collapsed subagent cards.

## Architectural decisions

- **Runtime identity**: Every metadata update is keyed by the existing subagent `task_id`, so parallel delegations in one lead-agent turn remain isolated.
- **Usage schema**: Runtime payloads carry cumulative `input_tokens`, `output_tokens`, and `total_tokens`. They are snapshots, not deltas, so replayed or out-of-order stream frames cannot double-count usage.
- **Update cadence**: “Live” means after each completed subagent LLM response. Providers generally do not expose authoritative usage before a response completes.
- **Model identity**: The wire contract carries the effective DeerFlow model name resolved for the subagent. The UI prefers the configured display name and falls back to the raw model name. Provider deployment identifiers remain observability data, not the primary card label.
- **Live and durable sources**: Custom task lifecycle events drive in-flight updates. Terminal ToolMessage metadata restores the same values from checkpointed chat history. `subagent.end` events retain the terminal snapshot for audit/debug consumers.
- **Compatibility**: All protocol additions are optional. Older runs render without runtime metadata, missing provider usage renders as unavailable rather than zero, and no database migration is required because existing JSON payloads are extended additively.
- **Existing totals**: Parent-run and thread token accounting remains unchanged; card metadata is a presentation projection and must not report usage to `RunJournal` a second time.
- **Feature gate**: Token rendering follows the existing `token_usage.enabled` setting. Model identity may still be shown when token rendering is disabled.

---

## Phase 1: Live Model Identity

**User stories**: A user can collapse a running subagent card and immediately see which configured LLM is executing it.

### What to build

Carry the effective subagent model name through the task-start lifecycle event and merge it into the task state by `task_id`. Resolve the friendly model display name in the workspace and render it in the collapsed-card header without displacing the existing status indicator.

### Acceptance criteria

- [ ] A running collapsed card shows its effective model as soon as the task-start event arrives.
- [ ] Parallel subagents using different models display the correct model on their own cards.
- [ ] The configured display name is preferred; an unknown model falls back to the raw identifier.
- [ ] Older task events without a model continue to render normally.

---

## Phase 2: Live Cumulative Token Usage

**User stories**: A user watching a collapsed running subagent card sees its token total increase after each completed subagent LLM call.

### What to build

Publish the collector’s latest cumulative usage snapshot while the subagent is running and attach it to task progress events. Merge snapshots into frontend task state as authoritative cumulative values, then render the formatted total beside the model label. Preserve the existing parent-run accounting path without adding another accounting write.

### Acceptance criteria

- [ ] The first completed subagent LLM call updates the collapsed card from “collecting” to a non-zero token total when usage is available.
- [ ] Later calls replace the card snapshot with the new cumulative total rather than adding the total again.
- [ ] Replayed, duplicate, or older progress events never double-count or decrease the displayed total.
- [ ] Concurrent subagents maintain independent totals keyed by `task_id`.
- [ ] Providers that omit usage metadata show an unavailable/collecting state, never a fabricated zero.

---

## Phase 3: Terminal Durability and Edge Paths

**User stories**: A user sees the same final model and token usage after completion, failure, cancellation, timeout, or page reload.

### What to build

Stamp the final model and cumulative usage into the existing structured task ToolMessage metadata and the persisted `subagent.end` event. Teach history reconstruction to read the optional metadata, with live snapshots and terminal history converging on the same task model. Cover every terminal status and tolerate legacy/malformed metadata safely.

### Acceptance criteria

- [ ] Completed, failed, cancelled, and timed-out cards retain their final model and usage.
- [ ] Reloading a thread restores metadata from normal message history without one request per card.
- [ ] Persisted `subagent.end` events contain the same terminal snapshot for audit/debug use.
- [ ] Legacy cards without metadata and providers without usage remain readable and show an explicit unavailable state.
- [ ] The right-side thread Token Usage total is unchanged and still counts subagent usage exactly once.
- [ ] Backend tests, frontend unit tests, type checks, formatting, and relevant regression suites pass.
