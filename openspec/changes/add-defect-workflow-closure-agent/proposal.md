## Why

The current builtin `defect-closure` agent is tied to DeerFlow's internal closure-ticket subsystem, while the new business need is to handle defect workflow tasks from the external EHM closed-loop platform. The two workflows share the Chinese display name "缺陷闭环" but operate on different domain objects, so the new integration must not replace or break the existing closure-ticket behavior.

## What Changes

- Add a new builtin agent for EHM defect workflow closure tasks, with display name "缺陷闭环" and a distinct internal name.
- Hide the legacy `defect-closure` agent from the left builtin-agent navigation while keeping it enabled and directly usable for existing closure-ticket flows.
- Add DeerFlow gateway APIs that proxy authenticated requests to the deployed EHM closed-loop and workflow platforms for defect todos, details, task-form context, task claim, and task submit.
- Add GenUI blocks for the new agent to show the current user's defect todo list, render defect detail and current-node form fields, support task claim, and submit platform-returned actions such as `SUBMIT`, `REJECT`, and `CANCEL`.
- Keep exception workflows out of scope; the new agent handles defect tasks only.

## Capabilities

### New Capabilities
- `defect-workflow-closure-agent`: Covers the new builtin defect workflow agent, platform API proxy, todo/detail/form/action flow, and GenUI interaction.
- `agent-navigation-visibility`: Covers hiding builtin agents from navigation without disabling their runtime availability or related legacy features.

### Modified Capabilities
- None. Existing closure-ticket capabilities remain intact.

## Impact

- Affected backend areas:
  - `backend/app/gateway/routers`
  - `backend/app/gateway/app.py`
  - `backend/packages/harness/deerflow/config/agents_config.py`
  - `backend/app/gateway/routers/agents.py`
- Affected frontend areas:
  - `frontend/src/core/agents`
  - `frontend/src/components/workspace/workspace-nav-chat-list.tsx`
  - `frontend/src/core/genui`
  - `frontend/src/components/genui`
- Affected agent assets:
  - `agents/builtin/defect-closure/config.yaml`
  - `agents/builtin/<new-defect-workflow-agent>/config.yaml`
  - `agents/builtin/<new-defect-workflow-agent>/SOUL.md`
- External systems:
  - EHM closed-loop platform at `/closed-loop-api/api/v1`
  - EHM workflow platform at `/workflow-api`
