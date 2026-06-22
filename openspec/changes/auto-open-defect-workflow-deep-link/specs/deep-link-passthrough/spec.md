## ADDED Requirements

### Requirement: Defect workflow deep links can target a todo row
The `defect-workflow-closure` Agent SHALL accept `task_id`, `defect_id`, `defect_no`, and `auto_open` deep-link parameters from EHM and use them to target a defect todo row in the current user's loaded todo list.

#### Scenario: Deep link target params are passed to the defect todo block
- **WHEN** a user opens `/workspace/agents/defect-workflow-closure/chats/new?task_id=90055&defect_id=1781744317660016&defect_no=QX20260618-678EC4CF&auto_open=1`
- **THEN** the local `defect-workflow-todo-list` block receives `target_task_id=90055`, `target_defect_id=1781744317660016`, `target_defect_no=QX20260618-678EC4CF`, and `auto_open_detail=true`

#### Scenario: Auto-open is scoped to the current user's todo list
- **WHEN** the target params refer to a defect that is not present in the loaded current-user todo list
- **THEN** the system SHALL NOT call the defect detail endpoint solely from the URL params
- **AND** the todo list remains visible
- **AND** the UI shows a non-blocking message that the target defect was not found in the current user's todo list

### Requirement: Defect workflow target matching uses stable priority
The defect todo list SHALL match deep-link target params against loaded todo rows using a stable priority: task id first, defect id second, and defect number third.

#### Scenario: Task id match wins over other target params
- **WHEN** `target_task_id` matches one row and `target_defect_id` or `target_defect_no` could match another row
- **THEN** the system SHALL select the row whose `taskId` matches `target_task_id`

#### Scenario: Defect id match is used when task id is unavailable
- **WHEN** `target_task_id` is absent or does not match any loaded row
- **AND** `target_defect_id` matches a loaded row's `defect.id` or `defect.defectId`
- **THEN** the system SHALL select that row

#### Scenario: Defect number match is used as fallback
- **WHEN** neither `target_task_id` nor `target_defect_id` matches a loaded row
- **AND** `target_defect_no` matches a loaded row's `defect.defectNo`, `defect.defectCode`, or `defect.code`
- **THEN** the system SHALL select that row

### Requirement: Auto-open reuses manual detail behavior
When a deep-link target matches a loaded defect todo row, the system SHALL open the same detail panel and selected-context flow used by the manual "详情" action.

#### Scenario: Matching target opens detail
- **WHEN** the todo list loads and finds a row matching the deep-link target
- **THEN** the system SHALL set that row as the selected task
- **AND** the detail panel SHALL load the defect detail and task form context using the existing detail flow
- **AND** later chat messages SHALL include the selected defect context in the same way as after a manual detail click

#### Scenario: Auto-open does not perform workflow mutations
- **WHEN** a deep link contains `auto_open=1`
- **THEN** the system SHALL NOT automatically claim, submit, reject, cancel, or otherwise mutate a workflow task
