## ADDED Requirements

### Requirement: Greeting API endpoint
The system SHALL expose a `GET /api/threads/{thread_id}/greeting` endpoint that returns a personalized greeting message based on user memory and recent activity.

#### Scenario: New thread with existing user memory
- **WHEN** a user opens a new thread and has stored memory facts (e.g., `workContext` or `recentMonths`)
- **THEN** the greeting API SHALL return a JSON response containing a personalized greeting text and 2-3 suggested actions derived from the user's recent work

#### Scenario: New thread without user memory
- **WHEN** a user opens a new thread and has no stored memory facts
- **THEN** the greeting API SHALL return a warm welcome message with generic suggested actions (e.g., "查看设备状态", "生成今日报告", "分析异常趋势")

#### Scenario: Greeting API timeout
- **WHEN** the greeting API takes longer than 2 seconds to respond
- **THEN** the system SHALL return a default greeting within the timeout window

### Requirement: Personalized greeting content

The greeting API SHALL generate content that references the user's recent work context when available.

#### Scenario: Greeting references recent analysis

- **WHEN** the user's memory contains a recent analysis of a specific device from the last 7 days
- **THEN** the greeting SHALL include a suggestion to follow up on that device (e.g., "您上次分析了2号泵组的振动数据，需要我帮您看看最新趋势吗？")

#### Scenario: Greeting references time of day

- **WHEN** the greeting API is called
- **THEN** the greeting text SHALL include a time-appropriate salutation (e.g., "早上好"/"下午好" based on the server's local time or user timezone)

### Requirement: Alert-aware greeting

The greeting API SHALL check for active anomalies or alarms on the user's monitored equipment. When active alerts exist, the greeting SHALL prioritize the alert over casual suggestions.

#### Scenario: Active alarm overrides casual greeting

- **WHEN** the user has monitored equipment with an active alarm or critical anomaly at the time the greeting API is called
- **THEN** the greeting SHALL lead with the alert (e.g., "2号泵组当前振动值超标，需要立即查看吗？") and SHALL NOT include casual pleasantries

#### Scenario: No active alarm uses normal greeting

- **WHEN** no active alarms exist on the user's monitored equipment
- **THEN** the greeting SHALL use the standard warm greeting flow with suggestions

### Requirement: Equipment-priority-ordered suggestions

Suggestion chips in the greeting SHALL be ordered by equipment criticality. The greeting API SHALL query equipment metadata to determine priority levels (critical > important > general).

#### Scenario: Suggestions sorted by equipment priority

- **WHEN** the greeting API generates suggestion chips for multiple devices
- **THEN** suggestions referencing critical equipment SHALL appear before suggestions referencing important or general equipment

#### Scenario: Recent anomaly boosts suggestion priority

- **WHEN** a device has recent anomalies (within 7 days) even if it is not classified as critical
- **THEN** that device's suggestion SHALL be promoted in the suggestion list

### Requirement: Greeting language detection

The greeting API SHALL determine the response language based on the user's most recent message or memory language preference. If no language context exists, it SHALL default to zh-CN.

#### Scenario: Greeting matches user's recent message language

- **WHEN** the user's most recent message in the thread is in English
- **THEN** the greeting text and suggestions SHALL be in English

#### Scenario: Greeting defaults to zh-CN when no language context

- **WHEN** the thread is new and no user messages exist
- **THEN** the greeting SHALL default to zh-CN unless memory indicates a language preference

### Requirement: Frontend greeting card display
The frontend SHALL display a greeting card in the empty conversation state instead of the generic "No messages yet" placeholder.

#### Scenario: Greeting card renders on new thread
- **WHEN** a user opens a new thread with no messages
- **THEN** the UI SHALL display a greeting card with the assistant's avatar, a personalized greeting text, and clickable suggestion chips

#### Scenario: Suggestion chip triggers message
- **WHEN** the user clicks a suggestion chip on the greeting card
- **THEN** the system SHALL populate the chat input with the suggestion text and submit it as a user message

#### Scenario: Greeting card loading state
- **WHEN** the greeting API is still loading
- **THEN** the UI SHALL display a skeleton version of the greeting card (avatar placeholder + text shimmer)
