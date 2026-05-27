## ADDED Requirements

### Requirement: Industrial intelligence featured category
The system SHALL create a dedicated "Industrial Intelligence" featured category in the template marketplace. Templates in this category SHALL appear first in search results and listing pages.

#### Scenario: Marketplace landing page
- **WHEN** a user navigates to the template marketplace landing page
- **THEN** the page displays a "Featured: Industrial Intelligence" section at the top with curated industrial templates (equipment diagnosis, monitoring analysis, trend reports)

#### Scenario: Search result ordering
- **WHEN** a user searches for templates in the marketplace
- **THEN** search results display templates with `category=industrial` before other categories, with a "Featured" badge on industrial templates

### Requirement: Industrial template discovery landing page
The system SHALL provide a dedicated landing page for industrial intelligence templates at `/workspace/template-marketplace/industrial`. This page SHALL showcase industrial template categories and provide curated recommendations.

#### Scenario: Navigate to industrial landing page
- **WHEN** a user clicks the "Industrial Intelligence" link in the marketplace navigation
- **THEN** the system displays the industrial templates landing page with sections: "Equipment Diagnosis", "Monitoring Analysis", "Trend Reports", "Failure Analysis"

#### Scenario: Industrial template categories
- **WHEN** a user views the industrial templates landing page
- **THEN** the page displays template cards organized by industrial category, each with description, usage count, and "Install" button

### Requirement: Industrial template auto-tagging
The system SHALL automatically tag templates with `category=industrial` when they contain industrial-specific form fields (device selectors, monitoring point selectors, equipment type fields) or reference industrial skills.

#### Scenario: Template creation with industrial fields
- **WHEN** a user creates a template with form steps containing device selector fields (`type=device-selector`)
- **THEN** the system automatically sets `category=industrial` and `is_featured=true` on the template metadata

#### Scenario: Template with industrial skill references
- **WHEN** a user creates a template that references industrial skills (e.g., `vibration-fault-diagnosis`, `monitoring-analysis`)
- **THEN** the system automatically sets `category=industrial` and `is_featured=true` on the template metadata

### Requirement: Industrial template usage analytics
The system SHALL track industrial template usage separately from general templates. Analytics SHALL include installation count, run count, and average completion rate for industrial templates.

#### Scenario: Industrial template usage tracking
- **WHEN** a user installs an industrial template from the marketplace
- **THEN** the system increments the template's `install_count` and records the installation in industrial template analytics

#### Scenario: Industrial template run tracking
- **WHEN** a user runs a report using an industrial template
- **THEN** the system records the run in industrial template analytics with template ID, run ID, duration, and completion status

### Requirement: Industrial template recommendations
The system SHALL recommend industrial templates to users based on their skill usage patterns. Users who frequently use industrial skills SHALL see industrial template recommendations in the chat interface.

#### Scenario: Skill-based template recommendation
- **WHEN** a user has used industrial skills (e.g., `vibration-fault-diagnosis`) in the last 7 days
- **THEN** the system displays a "Recommended Templates" section in the chat sidebar with industrial templates matching the user's skill usage

#### Scenario: New user template recommendation
- **WHEN** a new user completes industrial onboarding
- **THEN** the system displays a "Get Started with Templates" prompt recommending 3 starter industrial templates (daily equipment report, monitoring analysis, trend report)
