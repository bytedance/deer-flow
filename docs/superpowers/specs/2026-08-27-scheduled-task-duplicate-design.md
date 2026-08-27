# Scheduled Task Duplicate Design

## Goal

Let users reuse an existing scheduled task as the starting point for a new task without creating it immediately or changing the source task.

## User Experience

- Add a **Duplicate** action to the selected task's detail actions.
- Clicking it copies the source task into the existing create form at the top of the page.
- The draft title gains a localized suffix: ` (Copy)` in English and `（副本）` in Chinese.
- The page scrolls the create form into view and focuses the title field so the user can review and edit the draft.
- No network request is made until the user clicks the existing **Create** button.
- The source task remains selected and unchanged.

## Field Mapping

The duplicate draft copies:

- `prompt`
- `context_mode`
- `thread_id` when `context_mode` is `reuse_thread`
- `schedule_type`
- `timezone`
- cron expression for recurring tasks

For one-time tasks, copy `run_at` only when it is a valid future timestamp. If it is missing, invalid, or no longer in the future, clear it so the existing form validation requires the user to choose a new time.

The implementation will clone schedule data rather than reuse the source object's nested references.

## Components and Data Flow

The change stays in the frontend:

1. The task detail action calls a small pure helper that converts a `ScheduledTask` into create-form draft values.
2. The page applies those values to the existing title, prompt, context, thread, and schedule state.
3. Incrementing the existing schedule-form nonce remounts `ScheduledTaskScheduleInput` with the duplicated values.
4. The existing `useCreateScheduledTask` mutation remains the only creation path.

No backend route, persistence model, or API payload changes are required.

## Error Handling

- Invalid or expired one-time timestamps degrade to an empty `run_at` instead of creating an invalid request.
- Missing cron fields are copied as empty values and remain blocked by the existing create-form validation.
- Duplication itself is local and cannot fail due to Gateway availability.

## Testing

- Unit-test the draft helper for cron tasks, future one-time tasks, expired/invalid one-time tasks, context modes, and non-mutation of source data.
- Extend the scheduled-tasks page E2E coverage to verify that Duplicate fills the create form, adds the localized title suffix, does not issue a create request, and leaves final creation to the existing button.
- Run the focused scheduled-task unit tests, frontend `check`, and the scheduled-task Playwright spec when the local browser runtime is available.

## Out of Scope

- Creating the duplicate immediately.
- Copying run history, status, run counters, last error, or task identifiers.
- A backend clone endpoint.
- Bulk duplication or cross-user sharing.
