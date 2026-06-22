## 1. Deep-Link Target Propagation

- [x] 1.1 Parse `task_id`, `defect_id`, `defect_no`, and `auto_open` for `defect-workflow-closure` chats.
- [x] 1.2 Pass parsed target params into the local `defect-workflow-todo-list` UIBlock as `target_task_id`, `target_defect_id`, `target_defect_no`, and `auto_open_detail`.
- [x] 1.3 Preserve target params when a `/chats/new` deep-link transitions to the created thread id.

## 2. Todo List Auto-Open Behavior

- [x] 2.1 Extend `DefectWorkflowTodoListBlock` props to accept target params and an auto-open flag.
- [x] 2.2 Implement matching helpers that compare loaded rows by task id, defect id, then defect number.
- [x] 2.3 Auto-select the matching row once the loaded current-user todo list contains the target.
- [x] 2.4 Show a non-blocking not-found message when target params are present but no loaded row matches.
- [x] 2.5 Ensure auto-open reuses the existing selected task storage, detail panel loading, and selected-context event flow.

## 3. Tests And Documentation

- [x] 3.1 Add or update unit tests for target matching priority and not-found behavior.
- [x] 3.2 Add or update unit/component tests proving deep-link target props cause the correct row to be selected.
- [x] 3.3 Update `docs/deep-link-api.md` to document supported auto-open behavior and limitations.
- [x] 3.4 Run OpenSpec status/validation for `auto-open-defect-workflow-deep-link`.
- [x] 3.5 Run relevant frontend tests and type checks, or document any environment-limited verification.
