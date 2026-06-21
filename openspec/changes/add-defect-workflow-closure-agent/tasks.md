## 1. Agent Assets And Legacy Visibility

- [x] 1.1 Add builtin `defect-workflow-closure` config and SOUL files for the EHM defect workflow task flow.
- [x] 1.2 Mark legacy `defect-closure` as hidden from navigation without disabling it.
- [x] 1.3 Expose agent `visibility` from backend agent models and API responses.
- [x] 1.4 Add frontend agent typing and visible-agent filtering that hides `visibility: hidden` from agent navigation/pickers while preserving legacy closed-loop workspace availability.

## 2. Backend Platform Proxy

- [x] 2.1 Add configurable EHM closed-loop and workflow base URLs with deployed-prefix defaults.
- [x] 2.2 Implement a DeerFlow gateway client that forwards the current user's authorization header, timeout, query params, and JSON bodies to EHM services.
- [x] 2.3 Add `/api/defect-workflow/tasks/todo`, `/api/defect-workflow/defects/{defectId}`, and `/api/defect-workflow/tasks/{taskId}/form-context` read endpoints.
- [x] 2.4 Add `/api/defect-workflow/defects/{defectId}/workflow-tasks/{taskId}/claim` and `/api/defect-workflow/defects/{defectId}/workflow-tasks/{taskId}/submit` mutation endpoints.
- [x] 2.5 Register the backend router and add focused backend tests for URL construction, auth forwarding, response normalization, and error mapping.

## 3. GenUI Data Model And API Client

- [x] 3.1 Add frontend API helpers for the new DeerFlow `/api/defect-workflow` endpoints.
- [x] 3.2 Add TypeScript types for defect todo rows, defect detail, workflow task context, supported VForm widgets, and submit payloads.
- [x] 3.3 Implement a VForm-to-GenUI field converter for `input`, `textarea`, `number`, `select`, and `switch`, including defaults, options, required flags, and unsupported-widget metadata.

## 4. GenUI Components And Interaction Flow

- [x] 4.1 Add a defect todo list GenUI block with detail and claim-state presentation.
- [x] 4.2 Add a defect task detail GenUI block that renders metadata, equipment context, process/current-node information, form fields, comment input, claim action, and platform-returned action buttons.
- [x] 4.3 Wire claim and submit actions to the frontend API helpers, refresh detail/todo state after success, and show platform errors without losing user-entered form data.
- [x] 4.4 Register the new GenUI blocks and ensure the new agent can auto-start by rendering the todo list when opened.

## 5. Verification

- [x] 5.1 Add or update unit tests for agent visibility filtering and VForm conversion.
- [x] 5.2 Add or update component tests for defect todo/detail claim and submit states using mocked gateway responses.
- [x] 5.3 Run OpenSpec status/validation for `add-defect-workflow-closure-agent`.
- [x] 5.4 Run relevant backend and frontend test commands or document any environment-limited verification.
- [x] 5.5 Manually verify read-only integration against `10.0.2.233` with `user02` for todo, detail, and form-context endpoints without submitting workflow state.
