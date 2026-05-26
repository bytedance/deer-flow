## ADDED Requirements

### Requirement: Industrial-first landing experience
The system SHALL present industrial intelligence workflows as the default landing experience for all new users. Upon first login, users SHALL be directed to the industrial workspace view without requiring opt-in or selection.

#### Scenario: New user first login
- **WHEN** a new user logs in for the first time
- **THEN** the system displays the industrial workspace view with device management, monitoring analysis, and diagnosis reports as primary navigation items

#### Scenario: Returning user without industrial history
- **WHEN** a returning user with no industrial workflow usage logs in
- **THEN** the system displays the industrial workspace view and prompts the user to complete industrial onboarding if not already completed

### Requirement: No foundation-first fallback path
The system SHALL NOT provide a "skip to foundation" or "switch to general mode" option during onboarding or in the main workspace. Foundation tools SHALL remain accessible as secondary utilities but SHALL NOT be presented as an alternative primary path.

#### Scenario: Onboarding overlay skip option
- **WHEN** a user is viewing the industrial onboarding overlay
- **THEN** the overlay displays only "Complete Onboarding" and "Skip Onboarding" options, with no "Skip to Foundation Tools" option

#### Scenario: Workspace mode switcher
- **WHEN** a user is in the main workspace
- **THEN** there is no mode switcher or toggle to switch between "Industrial Mode" and "General Mode"

### Requirement: Industrial context in empty states
The system SHALL display industrial-focused example prompts, suggestions, and help text in all empty states (new chat, no history, no templates). Generic examples SHALL NOT be shown when industrial examples are available.

#### Scenario: New chat empty state
- **WHEN** a user opens a new chat with no message history
- **THEN** the system displays example prompts focused on industrial scenarios (e.g., "Diagnose pump vibration", "Analyze monitoring data", "Generate trend report")

#### Scenario: Template list empty state
- **WHEN** a user views the report templates list with no custom templates
- **THEN** the system displays industrial template recommendations (equipment diagnosis, monitoring analysis, trend reports) as suggested starting points

### Requirement: Industrial-first documentation
The system SHALL present industrial intelligence use cases as the primary narrative in all user-facing documentation, help text, and tooltips. Foundation tool documentation SHALL be accessible but secondary.

#### Scenario: Help documentation navigation
- **WHEN** a user opens the help documentation
- **THEN** the documentation table of contents lists industrial workflows (Device Management, Monitoring, Diagnosis) before general tools (Research, Data Analysis)

#### Scenario: Skill tooltip
- **WHEN** a user hovers over an industrial skill in the skill selector
- **THEN** the tooltip describes the industrial use case and typical workflow, with no mention of "alternative foundation tools"
