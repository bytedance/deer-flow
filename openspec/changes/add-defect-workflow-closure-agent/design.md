## Context

DeerFlow already has a builtin `defect-closure` agent and a `/workspace/closed-loop` workspace for its internal `closure_tickets` subsystem. That subsystem is used by diagnosis/report agents and must continue to work.

The new business workflow is different: users in the AI workbench need to process defect tasks owned by the deployed EHM closed-loop platform. The relevant external endpoints are:

- `/closed-loop-api/api/v1/defects/tasks/todo`
- `/closed-loop-api/api/v1/defects/{defectId}`
- `/closed-loop-api/api/v1/defects/{defectId}/workflow-tasks/{taskId}/claim`
- `/closed-loop-api/api/v1/defects/{defectId}/workflow-tasks/{taskId}/submit`
- `/workflow-api/task-forms/tasks/{taskId}/context`

The EHM task list returns assignment and claim state. Candidate tasks can have `claimRequired=true` and no `allowedActions`; claimed tasks return actionable values such as `SUBMIT`, `REJECT`, and `CANCEL`. Workflow form context returns VForm `widgetList` schemas, currently including controls such as `input`, `textarea`, `number`, `select`, and `switch`.

## Goals / Non-Goals

**Goals:**

- Add a new builtin agent with display name "缺陷闭环" and a distinct internal name for EHM defect workflow tasks.
- Keep legacy `defect-closure` enabled and available for existing closure-ticket integrations.
- Hide the legacy agent from the left builtin-agent navigation without hiding legacy `/workspace/closed-loop`.
- Add gateway APIs that proxy the current user's authenticated platform requests to EHM closed-loop/workflow services.
- Add GenUI components for todo list, detail display, current-node VForm-derived fields, claim, and submit.
- Keep the implementation defect-only.

**Non-Goals:**

- Do not migrate or remove DeerFlow `closure_tickets`.
- Do not make the new agent compatible with existing `defect-closure` deep links, SOUL behavior, or closure-ticket tools.
- Do not implement exception workflow todos or exception form submission.
- Do not implement a full VForm renderer for every possible widget in the first pass; unsupported widgets must degrade safely.

## Decisions

### 1. Add a new agent instead of replacing `defect-closure`

Use a new internal name, `defect-workflow-closure`, while keeping the display name "缺陷闭环".

Rationale: the existing `defect-closure` agent is part of the closure-ticket ecosystem. Reusing the same name would conflate old closure tickets with external EHM defect workflow tasks and could break report/diagnosis flows.

Alternative considered: rewrite `defect-closure` in place. Rejected because existing specs and SOUL content define closure-ticket behavior.

### 2. Use `visibility` for navigation hiding, not `enabled=false`

Expose `visibility` from the agents API and frontend type model. Filter `visibility: hidden` agents out of the builtin-agent navigation and general agent pickers, while retaining their enabled state.

Rationale: disabling the old agent would also interfere with existing runtime access and the current navigation gate for `/workspace/closed-loop`.

Alternative considered: hard-code `agent.name !== "defect-closure"` in the sidebar. Rejected because `visibility` already exists in backend config and is more reusable.

### 3. Route business actions through DeerFlow gateway APIs

Add a DeerFlow gateway router, tentatively `/api/defect-workflow`, with endpoints:

- `GET /tasks/todo`
- `GET /defects/{defectId}`
- `GET /tasks/{taskId}/form-context`
- `POST /defects/{defectId}/workflow-tasks/{taskId}/claim`
- `POST /defects/{defectId}/workflow-tasks/{taskId}/submit`

The gateway forwards the user's bearer token to EHM services and returns normalized JSON. The frontend GenUI blocks call these DeerFlow endpoints instead of calling EHM services directly.

Rationale: keeps external platform URLs, auth forwarding, timeouts, and error mapping in one backend boundary.

Alternative considered: let GenUI components call `/closed-loop-api` and `/workflow-api` directly. Rejected because it duplicates external integration concerns in browser UI and makes future auth changes harder.

### 4. Convert the supported VForm subset to GenUI form fields

For the first implementation, support `input`, `textarea`, `number`, `select`, and `switch`. Unknown widgets render as read-only unsupported notices and are excluded from submit unless explicitly represented in existing effective form data.

Rationale: the observed defect forms currently use this subset. A converter is faster and lower risk than porting the full Vue VForm runtime into React.

Alternative considered: implement a full React VForm runtime. Deferred until the platform returns widgets that the subset cannot safely handle.

### 5. Keep deterministic UI actions separate from assistant reasoning

The agent may summarize, explain, and help users gather equipment-related context, but claim and submit operations are performed by GenUI buttons calling gateway APIs. The UI refreshes todo/detail state after successful actions.

Rationale: business-state transitions must be explicit user actions, not inferred LLM tool calls.

## Risks / Trade-offs

- [Risk] External endpoint prefix differs between environments. → Use configurable backend settings/env with defaults matching deployed `/closed-loop-api` and `/workflow-api`.
- [Risk] Workflow form schemas include unsupported VForm widgets. → Render unsupported fields clearly, prevent silent data loss, and keep the converter isolated for extension.
- [Risk] Hiding the old agent accidentally hides `/workspace/closed-loop`. → Compute visible agent lists separately from legacy closed-loop availability checks.
- [Risk] User token forwarding fails for external services. → Preserve `Authorization` header forwarding and map 401/403 responses to clear gateway errors.
- [Risk] Claim/submit changes production workflow state during tests. → Use read-only tests for list/detail/form context and mock submit/claim in automated unit tests.

## Migration Plan

1. Add the new agent and visibility metadata without removing legacy files.
2. Deploy backend gateway APIs with read-only routes first; verify todo/detail/form context using `user02`.
3. Enable GenUI todo/detail rendering.
4. Enable claim/submit buttons after successful mocked and manual verification.
5. Rollback by hiding/disabling only the new agent; legacy `defect-closure` and `/workspace/closed-loop` remain unchanged.

## Open Questions

- Which environment variable names should be used for EHM closed-loop and workflow base URLs in production config?
- Should unsupported VForm widgets block submit entirely, or allow submit when they are optional? The first implementation should block only required unsupported widgets.
