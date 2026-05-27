# empathetic-error-handling Specification

## Purpose
TBD - created by archiving change personal-assistant-ux. Update Purpose after archive.
## Requirements
### Requirement: Error category mapping in backend
The `LLMErrorHandlingMiddleware` SHALL map technical errors to user-friendly error categories before they reach the assistant. The categories SHALL be: `network_issue`, `timeout`, `service_unavailable`, `data_not_found`, `permission_denied`, `rate_limited`.

#### Scenario: Network error mapped to category
- **WHEN** an LLM provider call fails with a connection error or DNS resolution failure
- **THEN** the error ToolMessage SHALL include `error_category: "network_issue"` and a suggested next action

#### Scenario: Timeout error mapped to category
- **WHEN** an LLM provider call exceeds its timeout threshold
- **THEN** the error ToolMessage SHALL include `error_category: "timeout"` and a suggested next action ("请稍等一下再试，或者缩小分析的时间范围")

#### Scenario: Unknown error mapped to generic category
- **WHEN** an error does not match any known category
- **THEN** the error ToolMessage SHALL include `error_category: "service_unavailable"` with a generic empathetic message

### Requirement: Empathetic error messages in frontend
The frontend SHALL display user-friendly, empathetic error messages instead of raw technical error details. Each error category SHALL have bilingual (zh-CN / en-US) message templates.

#### Scenario: Network error displayed to user
- **WHEN** the assistant receives an error with `error_category: "network_issue"`
- **THEN** the frontend SHALL display: "抱歉，网络连接似乎遇到了一些问题。请检查网络后重试，或者稍后再试。" (zh-CN) / "Sorry, there seems to be a network issue. Please check your connection and try again." (en-US)

#### Scenario: Error message includes next action
- **WHEN** any categorized error is displayed
- **THEN** the error message SHALL include at least one actionable suggestion (e.g., a "重试" button or a text suggestion)

#### Scenario: Technical details available on demand
- **WHEN** an error is displayed with an empathetic message
- **THEN** the user SHALL be able to expand a "查看详情" section to see the original technical error for debugging purposes

### Requirement: Error messages do not blame the user
All error message templates SHALL use language that takes responsibility ("我们遇到了一些问题") rather than blaming the user ("您的操作有误").

#### Scenario: Permission error phrasing
- **WHEN** the user lacks permission for an operation
- **THEN** the error message SHALL say "这个功能目前还没有开放给您，需要联系管理员开通" rather than "权限不足" or "Access denied"

