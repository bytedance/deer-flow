## ADDED Requirements

### Requirement: New builtin agent for EHM defect workflow closure
The system SHALL provide a builtin agent with internal name `defect-workflow-closure` and display name "缺陷闭环" for processing EHM closed-loop platform defect workflow tasks.

#### Scenario: Agent is distinct from legacy closure-ticket agent
- **WHEN** the builtin agent catalog is loaded
- **THEN** `defect-workflow-closure` is available as a separate agent from `defect-closure`
- **AND** the legacy `defect-closure` agent remains enabled unless explicitly disabled by user configuration

#### Scenario: New agent does not use closure-ticket tools
- **WHEN** the `defect-workflow-closure` agent receives a user request about defect workflow todos
- **THEN** it MUST treat EHM closed-loop platform defect task APIs as the source of truth
- **AND** it MUST NOT call `create_closure_ticket`, `list_closure_tickets`, `update_closure_ticket`, or `close_closure_ticket` for this workflow

### Requirement: Defect-only platform task list
The system SHALL load the current user's defect todo list from the EHM defect todo endpoint and SHALL NOT mix exception todo items into the new agent's primary todo list.

#### Scenario: Agent opens with defect todos
- **WHEN** a user opens a new chat with `defect-workflow-closure`
- **THEN** the chat SHALL render a defect todo list sourced from `GET /closed-loop-api/api/v1/defects/tasks/todo`
- **AND** the list SHALL include each row's defect summary, equipment identity, current node, assignment/claim state, task id, and available actions when present

#### Scenario: Exception tasks are excluded
- **WHEN** the EHM workbench aggregate endpoint contains exception tasks
- **THEN** the new defect closure agent SHALL still render only defect tasks from `/defects/tasks/todo`

### Requirement: Defect detail and form context
The system SHALL show detail for a selected defect task by combining EHM defect detail and workflow task-form context.

#### Scenario: User opens detail
- **WHEN** the user clicks a defect todo row's detail action
- **THEN** the system SHALL fetch `GET /closed-loop-api/api/v1/defects/{defectId}`
- **AND** if a current task id exists, fetch `GET /workflow-api/task-forms/tasks/{taskId}/context`
- **AND** render defect metadata, equipment metadata, current node, timeline or process steps when available, and editable current-node form fields when the task is actionable

#### Scenario: VForm subset is converted
- **WHEN** task-form context contains VForm widgets of type `input`, `textarea`, `number`, `select`, or `switch`
- **THEN** the system SHALL convert them to supported GenUI form fields while preserving field names, labels, default/effective values, options, and required flags

#### Scenario: Unsupported form widgets are not silently submitted
- **WHEN** task-form context contains an unsupported required widget
- **THEN** the system SHALL show that the field is unsupported
- **AND** prevent task submission until the field can be handled or the platform marks it optional

### Requirement: Claim and submit platform workflow tasks
The system SHALL support claiming candidate defect tasks and submitting current-node actions returned by the EHM platform.

#### Scenario: Candidate task requires claim
- **WHEN** a defect task has `claimRequired=true` and `claimable=true`
- **THEN** the detail UI SHALL show a claim action instead of submit/reject/cancel actions
- **AND** successful claim SHALL call `POST /closed-loop-api/api/v1/defects/{defectId}/workflow-tasks/{taskId}/claim`
- **AND** refresh the defect detail after success

#### Scenario: Current task actions are rendered from platform data
- **WHEN** a current task has `allowedActions` containing `SUBMIT`, `REJECT`, or `CANCEL`
- **THEN** the detail UI SHALL render corresponding action buttons
- **AND** the available actions SHALL come from the platform response, not from hard-coded workflow assumptions

#### Scenario: Submitting an action sends form data and comment
- **WHEN** the user submits an available action for a defect task
- **THEN** the system SHALL call `POST /closed-loop-api/api/v1/defects/{defectId}/workflow-tasks/{taskId}/submit`
- **AND** include `{ action, formData, comment }` in the request body
- **AND** refresh todo/detail state after a successful response

### Requirement: Equipment context assistance remains conversational
The new defect workflow closure agent SHALL allow the user to ask for equipment-related information to help fill the current form, without making equipment lookup mandatory for every task action.

#### Scenario: User asks for equipment context
- **WHEN** the user asks for information about the defect's bound equipment
- **THEN** the agent SHALL use the defect's equipment id/code/name from platform data as context for available equipment, monitoring, diagnosis, or knowledge tools
- **AND** the user can continue editing or submitting the task form after reviewing that information
