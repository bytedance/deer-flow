## Context

The new `defect-workflow-closure` Agent already renders a local GenUI todo list when opened and preserves the selected defect task context for follow-up chat questions. EHM will add an "AI分析" action in its defect management todo table and can pass `task_id`, `defect_id`, and `defect_no` to DeerFlow when navigating to the AI workbench.

The current DeerFlow deep-link pipeline parses generic query params, can auto-send prompts, and passes arbitrary business params through `additional_kwargs`, but the defect workflow home block does not consume those params to select a todo row. Users therefore land in the right Agent but must manually locate the same defect again.

## Goals / Non-Goals

**Goals:**

- Let `defect-workflow-closure` consume EHM deep-link target params: `task_id`, `defect_id`, `defect_no`, and `auto_open`.
- Automatically select and open the matching defect todo row after the current user's todo list loads.
- Preserve the existing detail loading path so selected defect context still enters subsequent chat turns.
- Show a clear non-blocking message when the target defect is not found in the current loaded todo list.
- Document the supported EHM integration URL and behavior.

**Non-Goals:**

- Do not add a backend resolve/search endpoint in this first version.
- Do not bypass the current user's todo list or open arbitrary defect details solely because a URL contains `defect_id`.
- Do not auto-claim, auto-submit, auto-reject, or auto-cancel workflow tasks.
- Do not change EHM frontend code in this repository.

## Decisions

1. **Pass target params through the local GenUI block props.**
   - The Agent chat page already creates the `defect-workflow-todo-list` block for `defect-workflow-closure`.
   - It will read `task_id`, `defect_id`, `defect_no`, and `auto_open` from `useSearchParams()` and include them as `target_task_id`, `target_defect_id`, `target_defect_no`, and `auto_open_detail`.
   - This keeps deep-link-specific behavior local to the defect workflow home block instead of adding global routing rules.

2. **Match only against the loaded current-user todo rows.**
   - The todo list component will load `/api/defect-workflow/tasks/todo` as it does today, then attempt target matching in priority order: `task_id`, `defect_id`, `defect_no`.
   - This preserves the current authorization boundary: auto-open only happens for rows that the user can already see in "我的待办".
   - If the target row is not loaded, the UI will not call the detail endpoint directly; it will show a message asking the user to confirm whether the task still belongs to their todo list.

3. **Reuse existing select/detail/context flow.**
   - On match, the component will set `selectedTaskId`, update block props, and write the selected task to session storage through the same path used by the "详情" button.
   - The existing detail panel will fetch defect detail and form context, then emit selected context for the chat page to include in future model input.
   - This avoids a second detail loading implementation and keeps behavior consistent with manual selection.

4. **Make auto-open idempotent.**
   - The component will track the last target key it has attempted. It should not repeatedly override a user's manual selection after the first automatic selection attempt for the same target.
   - Refreshing the list can re-apply the same target only if no user selection exists or the selected task is the same target.

## Risks / Trade-offs

- **Target not on first loaded page** -> The first version may show "not found" even if the task exists on a later page. Mitigation: document the limitation and keep the code structured so a future backend resolve or filtered todo query can replace the local-only lookup.
- **Backend row shape variability** -> Defect IDs and numbers may appear under several names. Mitigation: match against existing normalized fields already used by the table (`taskId`, `defect.id`, `defect.defectId`, `defect.defectNo`, `defect.defectCode`, `defect.code`).
- **Deep-link can contain stale task IDs** -> A task may already have been claimed/submitted. Mitigation: no direct open by URL; show a not-found/stale hint while preserving the todo list.
- **User selection overwritten** -> Auto-selection could be annoying if it runs after manual selection. Mitigation: apply auto-open once per target key and skip repeated selection once the user has selected a different row.

## Migration Plan

1. Deploy frontend changes with no backend migration.
2. EHM can start sending URLs with `task_id`, `defect_id`, `defect_no`, `mode=view`, and `auto_open=1`.
3. Rollback is frontend-only: removing the query params or reverting the frontend change returns behavior to "open Agent and show todo list".

## Open Questions

- If EHM needs reliable matching beyond the first loaded page, a follow-up change should add either filtered `/tasks/todo` query support or a DeerFlow gateway resolve endpoint constrained to the current user's todo scope.
