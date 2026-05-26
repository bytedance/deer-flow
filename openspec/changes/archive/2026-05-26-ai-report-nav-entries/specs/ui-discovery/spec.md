# UI Discovery Entry Points

## ADDED Requirements

### Requirement: Template page header actions
The report templates list page SHALL provide "创建模板" (primary button) and "模板市场" (text link) in the page header.

#### Scenario: User navigates to report templates page
- **WHEN** user visits `/workspace/report-templates`
- **THEN** the page header SHALL display a "创建模板" button and a "模板市场" link

#### Scenario: User clicks create template
- **WHEN** user clicks "创建模板"
- **THEN** the system SHALL navigate to `/workspace/report-templates/new`

#### Scenario: User clicks template marketplace
- **WHEN** user clicks "模板市场"
- **THEN** the system SHALL navigate to `/workspace/template-marketplace`
