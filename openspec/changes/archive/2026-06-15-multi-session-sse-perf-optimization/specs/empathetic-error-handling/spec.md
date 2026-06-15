## MODIFIED Requirements

### Requirement: Empathetic error messages in frontend

The frontend SHALL display user-friendly, empathetic error messages instead of raw technical error details. Each error category SHALL have bilingual (zh-CN / en-US) message templates. Errors that occur while a thread is in background-paused state (stream suspended due to tab invisibility) SHALL NOT be displayed as toast notifications; instead, they SHALL be silently recorded and surfaced when the user returns to the thread. Additionally, when a run completes or fails during the background-paused period, the `onFinish` equivalent logic SHALL execute upon the user's return.

#### Scenario: Network error displayed to user

- **WHEN** the assistant receives an error with `error_category: "network_issue"` AND the thread is in active (visible) state
- **THEN** the frontend SHALL display: "抱歉，网络连接似乎遇到了一些问题。请检查网络后重试，或者稍后再试。" (zh-CN) / "Sorry, there seems to be a network issue. Please check your connection and try again." (en-US)

#### Scenario: Error message includes next action

- **WHEN** any categorized error is displayed AND the thread is in active state
- **THEN** the error message SHALL include at least one actionable suggestion (e.g., a "重试" button or a text suggestion)

#### Scenario: Technical details available on demand

- **WHEN** an error is displayed with an empathetic message
- **THEN** the user SHALL be able to expand a "查看详情" section to see the original technical error for debugging purposes

#### Scenario: Background thread error suppressed from toast

- **WHEN** an error occurs on a thread that is in background-paused state (SSE suspended due to tab invisibility)
- **THEN** the frontend SHALL NOT display a toast notification
- **AND** the error SHALL be recorded in the thread's error state
- **AND** when the user returns to the thread, the error SHALL be displayed inline in the message list

#### Scenario: Critical errors break through background suppression

- **WHEN** an error with `error_category: "permission_denied"` (quota exhaustion, authentication failure) occurs on a thread in background-paused state
- **THEN** the frontend SHALL display a toast notification immediately, even though the thread is in background
- **AND** the toast SHALL use the empathetic error message (not raw technical details)
- **Rationale**: Critical errors like quota exhaustion or auth failure affect the entire account/session, not just the current thread. Delaying notification until the user returns could lead to repeated failed runs and wasted resources.

#### Scenario: Background error surfaced on return

- **WHEN** the user returns to a thread that encountered errors while in background-paused state
- **THEN** the frontend SHALL display the accumulated errors inline in the message list with an empathetic message and retry option

#### Scenario: onFinish fallback on background completion

- **WHEN** a run completes or fails during the background-paused period
- **AND** the `onFinish` callback was not triggered (because SSE was suspended)
- **THEN** upon the user returning to the thread, the system SHALL detect `thread.status` is terminal (`completed` or `error`)
- **AND** execute `onFinish`-equivalent finalization: fetch complete state, append messages, invalidate sidebar queries
- **AND** if the run ended with an error, display the error inline (not as toast) following the empathetic error display rules
