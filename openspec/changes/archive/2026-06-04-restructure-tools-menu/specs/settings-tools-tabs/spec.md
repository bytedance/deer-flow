## ADDED Requirements

### Requirement: Tools settings page uses tabs

The system SHALL organize the tools settings page using a tabbed layout containing tool management, platform capabilities, and A2UI debug sections.

#### Scenario: Default tab shows MCP tool management

- **WHEN** user navigates to Settings → Tools
- **THEN** the "工具管理" (Tool Management) tab is active by default
- **AND** the existing MCP server list with enable/disable toggles is displayed

#### Scenario: Platform capabilities tab

- **WHEN** user selects the "平台能力" (Capabilities) tab
- **THEN** a description of platform capabilities is shown with a link to open `/workspace/capabilities`

#### Scenario: A2UI debug tab

- **WHEN** user selects the "A2UI 调试" (A2UI Debug) tab
- **THEN** a description of A2UI debug tools is shown with a link to open `/workspace/debug/a2ui`

### Requirement: Tool settings tabs have i18n keys

The system SHALL provide localized labels for each tool settings tab.

#### Scenario: Chinese labels

- **WHEN** locale is zh-CN
- **THEN** tabs display "工具管理", "平台能力", "A2UI 调试"

#### Scenario: English labels

- **WHEN** locale is en-US
- **THEN** tabs display "Tool Management", "Capabilities", "A2UI Debug"
